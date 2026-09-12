"""Daily fail-closed reconciliation for drink-log records and image objects."""

from __future__ import annotations

import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

try:
    from whiskey_common.clients import get_dynamodb_resource, get_s3_client
    from whiskey_common.logger import get_logger
    from whiskey_common.normalize import UUID_TEXT
    from whiskey_common.scan_utils import scan_all_pages
    from whiskey_common.timeutils import rfc3339, utc_now
except ModuleNotFoundError as exc:
    if exc.name != "whiskey_common":
        raise
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common" / "python"))
    from whiskey_common.clients import get_dynamodb_resource, get_s3_client
    from whiskey_common.logger import get_logger
    from whiskey_common.normalize import UUID_TEXT
    from whiskey_common.scan_utils import scan_all_pages
    from whiskey_common.timeutils import rfc3339, utc_now

from lifecycle import DrinkLogLifecycle, derive_drink_log_id


LOG_KEY_RE = re.compile(rf"^logs/([^/]+)/({UUID_TEXT})-[0-9a-fA-F]+\.jpg$")
MAX_BATCH_GET_ATTEMPTS = 3
RECONCILER_MAX_SCAN_PAGES = 10_000


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


def _scan_all_or_raise(table: Any, **kwargs: Any) -> list[dict[str, Any]]:
    items, continuation_token = scan_all_pages(
        table,
        max_pages=RECONCILER_MAX_SCAN_PAGES,
        **kwargs,
    )
    if continuation_token is not None:
        raise RuntimeError("Drink-log reconciliation scan exceeded its page limit")
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


def reconcile_log_objects(
    dynamodb: Any,
    s3: Any,
    drinklogs_table_name: str,
    bucket_name: str,
    cutoff: datetime,
) -> int:
    table = dynamodb.Table(drinklogs_table_name)
    lifecycle = DrinkLogLifecycle(
        dynamodb, s3, drinklogs_table_name, "", bucket_name, rfc3339
    )
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
        parsed.append((obj, key, user_id, derive_drink_log_id(user_id, upload_uuid)))
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
            lifecycle.delete_and_confirm(key)
            deleted += 1
            continue
        if record and record.get("status") == "pending":
            acquired = lifecycle.acquire_pending_for_deletion(record)
            if acquired is None:
                current = lifecycle.get(record_id)
                if not current or current.get("user_id") != user_id:
                    continue
                if current.get("status") == "complete" and current.get("s3_image_key") == key:
                    continue
                if current.get("status") not in {"complete", "deleting"}:
                    continue
            lifecycle.delete_and_confirm(key)
            deleted += 1
            continue
        if record and record.get("status") == "deleting":
            lifecycle.delete_and_confirm(key)
            deleted += 1
            continue
        if record:
            continue

        last_modified = _parse_time(obj.get("LastModified"))
        if last_modified is None:
            continue
        tombstone = lifecycle.create_tombstone(record_id, user_id, key, last_modified)
        if tombstone is None:
            current = lifecycle.get(record_id)
            if not current or current.get("user_id") != user_id:
                continue
            if current.get("status") == "complete" and current.get("s3_image_key") == key:
                continue
            if current.get("status") not in {"complete", "deleting"}:
                continue
        lifecycle.delete_and_confirm(key)
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
    lifecycle = DrinkLogLifecycle(
        dynamodb,
        s3,
        drinklogs_table_name,
        app_state_table_name,
        bucket_name,
        rfc3339,
    )
    records = _scan_all_or_raise(
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
        lifecycle.delete_record_image(item)
        if lifecycle.finalize_delete(item, now=utc_now()):
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
    lifecycle = DrinkLogLifecycle(
        dynamodb,
        s3,
        drinklogs_table_name,
        app_state_table_name,
        bucket_name,
        rfc3339,
    )
    records = _scan_all_or_raise(
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
        acquired = lifecycle.acquire_pending_for_deletion(item)
        if not acquired:
            continue
        lifecycle.delete_record_image(acquired)
        if lifecycle.finalize_delete(acquired, now=utc_now()):
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
    lifecycle = DrinkLogLifecycle(
        dynamodb, s3, drinklogs_table_name, "", bucket_name, rfc3339
    )
    records = _scan_all_or_raise(
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
        lifecycle.delete_and_confirm(key)
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
    lifecycle = DrinkLogLifecycle(
        dynamodb, s3, drinklogs_table_name, "", bucket_name, rfc3339
    )
    records = _scan_all_or_raise(
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
        lifecycle.delete_and_confirm(key)
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
    cutoff = utc_now() - timedelta(
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
