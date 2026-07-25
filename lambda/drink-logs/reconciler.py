"""Daily fail-closed reconciliation for drink-log records and image objects."""

from __future__ import annotations

import os
import re
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from botocore.exceptions import ClientError

try:
    from whiskey_common.clients import get_dynamodb_resource, get_s3_client
    from whiskey_common.logger import get_logger
except ModuleNotFoundError as exc:
    if exc.name != "whiskey_common":
        raise
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common" / "python"))
    from whiskey_common.clients import get_dynamodb_resource, get_s3_client
    from whiskey_common.logger import get_logger


NAMESPACE_DRINKLOG = uuid.UUID("7df1920f-5929-51ee-9860-164c1d4bc388")
UUID_TEXT = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}"
LOG_KEY_RE = re.compile(rf"^logs/([^/]+)/({UUID_TEXT})-[0-9a-fA-F]+\.jpg$")
MAX_BATCH_GET_ATTEMPTS = 3


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _rfc3339(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _derive_id(user_id: str, upload_uuid: str) -> str:
    return str(uuid.uuid5(NAMESPACE_DRINKLOG, f"{user_id}\0{str(uuid.UUID(upload_uuid))}"))


def _parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return None
        return value.astimezone(timezone.utc)
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _record_is_old(item: Mapping[str, Any], cutoff: datetime) -> bool:
    timestamp = _parse_time(
        item.get("delete_started_at")
        if item.get("status") == "deleting" and item.get("delete_started_at")
        else item.get("updated_at") or item.get("created_at") or item.get("datetime")
    )
    return timestamp is not None and timestamp < cutoff


def _object_is_old(item: Mapping[str, Any], cutoff: datetime) -> bool:
    timestamp = _parse_time(item.get("LastModified"))
    return timestamp is not None and timestamp < cutoff


def _scan_all(table: Any, **kwargs: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    cursor = None
    while True:
        request = dict(kwargs)
        if cursor:
            request["ExclusiveStartKey"] = cursor
        response = table.scan(**request)
        items.extend(response.get("Items", []))
        cursor = response.get("LastEvaluatedKey")
        if not cursor:
            return items


def _list_all_objects(s3: Any, bucket_name: str, prefix: str) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket_name, Prefix=prefix):
        objects.extend(page.get("Contents", []))
    return objects


def _batch_get_records(
    dynamodb: Any,
    table_name: str,
    record_ids: Iterable[str],
) -> dict[str, dict[str, Any]]:
    unique_ids = list(dict.fromkeys(record_ids))
    records: dict[str, dict[str, Any]] = {}
    for offset in range(0, len(unique_ids), 100):
        request_items: dict[str, Any] = {
            table_name: {
                "Keys": [{"id": record_id} for record_id in unique_ids[offset : offset + 100]],
                "ConsistentRead": True,
            }
        }
        for _ in range(MAX_BATCH_GET_ATTEMPTS):
            response = dynamodb.batch_get_item(RequestItems=request_items)
            for item in response.get("Responses", {}).get(table_name, []):
                records[item["id"]] = item
            unprocessed = response.get("UnprocessedKeys", {})
            if not unprocessed:
                break
            request_items = unprocessed
        else:
            raise RuntimeError("DynamoDB BatchGetItem remained unprocessed")
    return records


def _is_missing_s3_error(exc: ClientError) -> bool:
    return exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}


def _object_absent(s3: Any, bucket_name: str, key: str) -> bool:
    try:
        s3.head_object(Bucket=bucket_name, Key=key)
    except ClientError as exc:
        if _is_missing_s3_error(exc):
            return True
        raise
    return False


def _delete_and_confirm(s3: Any, bucket_name: str, key: str) -> None:
    s3.delete_object(Bucket=bucket_name, Key=key)
    if not _object_absent(s3, bucket_name, key):
        raise RuntimeError(f"S3 deletion was not confirmed for {key}")


def _quota_counter_decrement(table_name: str, key: str, now: str) -> dict[str, Any]:
    return {
        "Update": {
            "TableName": table_name,
            "Key": {"pk": key},
            "UpdateExpression": "SET updated_at = :updated_at ADD #count :minus_one",
            "ConditionExpression": "#count >= :one",
            "ExpressionAttributeNames": {"#count": "count"},
            "ExpressionAttributeValues": {":minus_one": -1, ":one": 1, ":updated_at": now},
        }
    }


def _get_record(table: Any, record_id: str) -> dict[str, Any] | None:
    return table.get_item(Key={"id": record_id}, ConsistentRead=True).get("Item")


def _acquire_pending(table: Any, item: Mapping[str, Any]) -> dict[str, Any] | None:
    try:
        response = table.update_item(
            Key={"id": item["id"]},
            UpdateExpression="SET #status = :deleting",
            ConditionExpression="#status = :pending AND #owner = :owner",
            ExpressionAttributeNames={"#status": "status", "#owner": "user_id"},
            ExpressionAttributeValues={
                ":pending": "pending",
                ":deleting": "deleting",
                ":owner": item["user_id"],
            },
            ReturnValues="ALL_NEW",
        )
        return response.get("Attributes")
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        return None


def _create_tombstone(
    table: Any,
    record_id: str,
    user_id: str,
    key: str,
    timestamp: datetime,
) -> dict[str, Any] | None:
    object_time = _rfc3339(timestamp)
    item = {
        "id": record_id,
        "user_id": user_id,
        "status": "deleting",
        "datetime": _rfc3339(timestamp),
        "s3_image_key": key,
        "quota_allocated": False,
        "created_at": object_time,
        "updated_at": object_time,
    }
    try:
        table.put_item(Item=item, ConditionExpression="attribute_not_exists(id)")
        return item
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        return None


def _finalize_deleting(
    dynamodb: Any,
    drinklogs_table_name: str,
    app_state_table_name: str,
    item: Mapping[str, Any],
) -> bool:
    delete = {
        "Delete": {
            "TableName": drinklogs_table_name,
            "Key": {"id": item["id"]},
            "ConditionExpression": (
                "#status = :deleting AND #owner = :owner AND quota_allocated = :allocated"
            ),
            "ExpressionAttributeNames": {"#status": "status", "#owner": "user_id"},
            "ExpressionAttributeValues": {
                ":deleting": "deleting",
                ":owner": item["user_id"],
                ":allocated": bool(item.get("quota_allocated")),
            },
        }
    }
    transaction: list[dict[str, Any]] = [delete]
    if item.get("quota_allocated") is True:
        now = _rfc3339(_utc_now())
        transaction.extend(
            [
                _quota_counter_decrement(
                    app_state_table_name,
                    f"drinklog-quota#user#{item['user_id']}",
                    now,
                ),
                _quota_counter_decrement(app_state_table_name, "drinklog-quota#global", now),
            ]
        )
    client = dynamodb.meta.client
    try:
        client.transact_write_items(TransactItems=transaction)
        return True
    except client.exceptions.TransactionCanceledException:
        if _get_record(dynamodb.Table(drinklogs_table_name), item["id"]) is None:
            return True
        raise RuntimeError("Deleting record transaction did not converge")


def _delete_record_image(s3: Any, bucket_name: str, item: Mapping[str, Any]) -> None:
    key = item.get("s3_image_key")
    if not key:
        return
    if not isinstance(key, str) or not key.startswith(f"logs/{item['user_id']}/"):
        raise RuntimeError("Refusing to reconcile an image outside its owner prefix")
    _delete_and_confirm(s3, bucket_name, key)


def reconcile_log_objects(
    dynamodb: Any,
    s3: Any,
    drinklogs_table_name: str,
    bucket_name: str,
    cutoff: datetime,
) -> int:
    table = dynamodb.Table(drinklogs_table_name)
    objects = [
        item
        for item in _list_all_objects(s3, bucket_name, "logs/")
        if _object_is_old(item, cutoff)
    ]
    parsed: list[tuple[dict[str, Any], str, str, str]] = []
    for obj in objects:
        key = obj.get("Key")
        match = LOG_KEY_RE.fullmatch(key) if isinstance(key, str) else None
        if not match:
            continue
        user_id, upload_uuid = match.groups()
        parsed.append((obj, key, user_id, _derive_id(user_id, upload_uuid)))
    records = _batch_get_records(
        dynamodb,
        drinklogs_table_name,
        (record_id for _obj, _key, _user, record_id in parsed),
    )

    deleted = 0
    for obj, key, user_id, record_id in parsed:
        record = records.get(record_id)
        if record and record.get("user_id") != user_id:
            continue
        if record and record.get("status") == "complete":
            if record.get("s3_image_key") == key:
                continue
            _delete_and_confirm(s3, bucket_name, key)
            deleted += 1
            continue
        if record and record.get("status") == "pending":
            acquired = _acquire_pending(table, record)
            if acquired is None:
                current = _get_record(table, record_id)
                if not current or current.get("user_id") != user_id:
                    continue
                if current.get("status") == "complete" and current.get("s3_image_key") == key:
                    continue
                if current.get("status") not in {"complete", "deleting"}:
                    continue
            _delete_and_confirm(s3, bucket_name, key)
            deleted += 1
            continue
        if record and record.get("status") == "deleting":
            _delete_and_confirm(s3, bucket_name, key)
            deleted += 1
            continue
        if record:
            continue

        last_modified = _parse_time(obj.get("LastModified"))
        if last_modified is None:
            continue
        tombstone = _create_tombstone(table, record_id, user_id, key, last_modified)
        if tombstone is None:
            current = _get_record(table, record_id)
            if not current or current.get("user_id") != user_id:
                continue
            if current.get("status") == "complete" and current.get("s3_image_key") == key:
                continue
            if current.get("status") not in {"complete", "deleting"}:
                continue
        _delete_and_confirm(s3, bucket_name, key)
        deleted += 1
    return deleted


def reconcile_deleting_records(
    dynamodb: Any,
    s3: Any,
    drinklogs_table_name: str,
    app_state_table_name: str,
    bucket_name: str,
    cutoff: datetime,
) -> int:
    table = dynamodb.Table(drinklogs_table_name)
    records = _scan_all(
        table,
        ConsistentRead=True,
        FilterExpression="#status = :deleting",
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={":deleting": "deleting"},
    )
    completed = 0
    for item in records:
        if not _record_is_old(item, cutoff):
            continue
        _delete_record_image(s3, bucket_name, item)
        if _finalize_deleting(dynamodb, drinklogs_table_name, app_state_table_name, item):
            completed += 1
    return completed


def reconcile_pending_records(
    dynamodb: Any,
    s3: Any,
    drinklogs_table_name: str,
    app_state_table_name: str,
    bucket_name: str,
    cutoff: datetime,
) -> int:
    table = dynamodb.Table(drinklogs_table_name)
    records = _scan_all(
        table,
        ConsistentRead=True,
        FilterExpression="#status = :pending",
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={":pending": "pending"},
    )
    completed = 0
    for item in records:
        if not _record_is_old(item, cutoff):
            continue
        acquired = _acquire_pending(table, item)
        if not acquired:
            continue
        _delete_record_image(s3, bucket_name, acquired)
        if _finalize_deleting(dynamodb, drinklogs_table_name, app_state_table_name, acquired):
            completed += 1
    return completed


def reconcile_tmp_objects(
    dynamodb: Any,
    s3: Any,
    drinklogs_table_name: str,
    bucket_name: str,
    cutoff: datetime,
) -> int:
    table = dynamodb.Table(drinklogs_table_name)
    records = _scan_all(
        table,
        ConsistentRead=True,
        ProjectionExpression="id, tmp_s3_key",
    )
    referenced = {
        item["tmp_s3_key"]
        for item in records
        if isinstance(item.get("tmp_s3_key"), str)
    }
    deleted = 0
    for obj in _list_all_objects(s3, bucket_name, "tmp/"):
        key = obj.get("Key")
        if not isinstance(key, str) or key in referenced or not _object_is_old(obj, cutoff):
            continue
        _delete_and_confirm(s3, bucket_name, key)
        deleted += 1
    return deleted


def reconcile_complete_tmp_references(
    dynamodb: Any,
    s3: Any,
    drinklogs_table_name: str,
    bucket_name: str,
    cutoff: datetime,
) -> int:
    table = dynamodb.Table(drinklogs_table_name)
    records = _scan_all(
        table,
        ConsistentRead=True,
        FilterExpression="#status = :complete AND attribute_exists(tmp_s3_key)",
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={":complete": "complete"},
    )
    cleaned = 0
    for item in records:
        if not _record_is_old(item, cutoff):
            continue
        key = item.get("tmp_s3_key")
        if not isinstance(key, str) or not key.startswith(f"tmp/{item['user_id']}/"):
            continue
        _delete_and_confirm(s3, bucket_name, key)
        try:
            table.update_item(
                Key={"id": item["id"]},
                UpdateExpression="REMOVE tmp_s3_key",
                ConditionExpression="#status = :complete AND tmp_s3_key = :key",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={":complete": "complete", ":key": key},
            )
            cleaned += 1
        except table.meta.client.exceptions.ConditionalCheckFailedException:
            continue
    return cleaned


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    del event, context
    logger = get_logger("drink-log-reconciler")
    dynamodb = get_dynamodb_resource()
    s3 = get_s3_client()
    drinklogs_table_name = os.environ["DRINKLOGS_TABLE"]
    app_state_table_name = os.environ["APP_STATE_TABLE"]
    bucket_name = os.environ["IMAGES_BUCKET"]
    cutoff = _utc_now() - timedelta(
        hours=max(1, int(os.environ.get("RECONCILE_AGE_HOURS", "48")))
    )

    try:
        result = {
            "logs_deleted": reconcile_log_objects(
                dynamodb, s3, drinklogs_table_name, bucket_name, cutoff
            ),
            "deleting_completed": reconcile_deleting_records(
                dynamodb,
                s3,
                drinklogs_table_name,
                app_state_table_name,
                bucket_name,
                cutoff,
            ),
            "pending_completed": reconcile_pending_records(
                dynamodb,
                s3,
                drinklogs_table_name,
                app_state_table_name,
                bucket_name,
                cutoff,
            ),
            "tmp_deleted": reconcile_tmp_objects(
                dynamodb, s3, drinklogs_table_name, bucket_name, cutoff
            ),
            "complete_tmp_cleaned": reconcile_complete_tmp_references(
                dynamodb, s3, drinklogs_table_name, bucket_name, cutoff
            ),
        }
    except Exception as exc:
        logger.error("Drink-log reconciliation failed", error=str(exc))
        raise
    logger.info("Drink-log reconciliation completed", **result)
    return {"status": "reconciled", **result}
