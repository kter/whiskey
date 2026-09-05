"""Drink Log persistence state transitions shared by request and repair adapters."""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping

from botocore.exceptions import ClientError

from whiskey_common.transactions import transact_write_with_retry


NAMESPACE_DRINKLOG = uuid.UUID("7df1920f-5929-51ee-9860-164c1d4bc388")


class RateLimitExceeded(Exception):
    pass


class CreateConflict(Exception):
    pass


class TransientConflict(Exception):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def rfc3339(value: datetime) -> str:
    return (
        value.astimezone(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def derive_drink_log_id(user_id: str, upload_uuid: str) -> str:
    """Derive a stable record ID bound to both the owner and upload UUID."""
    parsed = str(uuid.UUID(upload_uuid))
    return str(uuid.uuid5(NAMESPACE_DRINKLOG, f"{user_id}\0{parsed}"))


def _rate_counter_update(
    table_name: str,
    key: str,
    limit: int,
    ttl: int,
    now: str,
) -> dict[str, Any]:
    return {
        "Update": {
            "TableName": table_name,
            "Key": {"pk": key},
            "UpdateExpression": (
                "SET #ttl = if_not_exists(#ttl, :ttl), updated_at = :updated_at "
                "ADD #count :one"
            ),
            "ConditionExpression": "attribute_not_exists(#count) OR #count < :limit",
            "ExpressionAttributeNames": {"#count": "count", "#ttl": "ttl"},
            "ExpressionAttributeValues": {
                ":one": 1,
                ":limit": limit,
                ":ttl": ttl,
                ":updated_at": now,
            },
        }
    }


def _quota_counter_update(
    table_name: str,
    key: str,
    limit: int,
    now: str,
) -> dict[str, Any]:
    return {
        "Update": {
            "TableName": table_name,
            "Key": {"pk": key},
            "UpdateExpression": "SET updated_at = :updated_at ADD #count :one",
            "ConditionExpression": "attribute_not_exists(#count) OR #count < :limit",
            "ExpressionAttributeNames": {"#count": "count"},
            "ExpressionAttributeValues": {":one": 1, ":limit": limit, ":updated_at": now},
        }
    }


def _quota_counter_decrement(table_name: str, key: str, now: str) -> dict[str, Any]:
    return {
        "Update": {
            "TableName": table_name,
            "Key": {"pk": key},
            "UpdateExpression": "SET updated_at = :updated_at ADD #count :minus_one",
            "ConditionExpression": "#count >= :one",
            "ExpressionAttributeNames": {"#count": "count"},
            "ExpressionAttributeValues": {
                ":minus_one": -1,
                ":one": 1,
                ":updated_at": now,
            },
        }
    }


def _is_missing_s3_error(exc: ClientError) -> bool:
    return exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}


@dataclass(frozen=True)
class DrinkLogLifecycle:
    """Own persistence transitions and convergence for one Drink Log store."""

    dynamodb: Any
    s3: Any
    drinklogs_table_name: str
    app_state_table_name: str
    bucket_name: str
    timestamp_format: Callable[[datetime], str] = rfc3339

    @property
    def table(self) -> Any:
        return self.dynamodb.Table(self.drinklogs_table_name)

    @property
    def client(self) -> Any:
        return self.dynamodb.meta.client

    def get(self, record_id: str) -> dict[str, Any] | None:
        return self.table.get_item(Key={"id": record_id}, ConsistentRead=True).get("Item")

    def object_absent(self, key: str) -> bool:
        try:
            self.s3.head_object(Bucket=self.bucket_name, Key=key)
        except ClientError as exc:
            if _is_missing_s3_error(exc):
                return True
            raise
        return False

    def delete_and_confirm(self, key: str) -> None:
        self.s3.delete_object(Bucket=self.bucket_name, Key=key)
        if not self.object_absent(key):
            raise RuntimeError(f"S3 deletion was not confirmed for {key}")

    def start_create(
        self,
        pending: Mapping[str, Any],
        consume_analysis: Mapping[str, Any],
        *,
        now: datetime,
    ) -> None:
        timestamp = self.timestamp_format(now)
        utc_date = now.astimezone(timezone.utc).strftime("%Y-%m-%d")
        ttl = int((now + timedelta(days=2)).timestamp())
        user_id = pending["user_id"]
        transaction = [
            {
                "Put": {
                    "TableName": self.drinklogs_table_name,
                    "Item": dict(pending),
                    "ConditionExpression": "attribute_not_exists(id)",
                }
            },
            _rate_counter_update(
                self.app_state_table_name,
                f"drinklog-counter#create#user#{user_id}#{utc_date}",
                int(os.environ.get("CREATE_USER_DAILY_LIMIT", "30")),
                ttl,
                timestamp,
            ),
            _rate_counter_update(
                self.app_state_table_name,
                f"drinklog-counter#create#global#{utc_date}",
                int(os.environ.get("CREATE_GLOBAL_DAILY_LIMIT", "100")),
                ttl,
                timestamp,
            ),
            _quota_counter_update(
                self.app_state_table_name,
                f"drinklog-quota#user#{user_id}",
                int(os.environ.get("STORAGE_USER_LIMIT", "2000")),
                timestamp,
            ),
            _quota_counter_update(
                self.app_state_table_name,
                "drinklog-quota#global",
                int(os.environ.get("STORAGE_GLOBAL_LIMIT", "20000")),
                timestamp,
            ),
            dict(consume_analysis),
        ]
        transact_write_with_retry(self.client, transaction)

    def compensate_create(self, record: Mapping[str, Any], *, now: datetime) -> bool:
        timestamp = self.timestamp_format(now)
        try:
            transact_write_with_retry(
                self.client,
                [
                    {
                        "Delete": {
                            "TableName": self.drinklogs_table_name,
                            "Key": {"id": record["id"]},
                            "ConditionExpression": (
                                "#owner = :caller AND #status = :pending "
                                "AND quota_allocated = :true"
                            ),
                            "ExpressionAttributeNames": {
                                "#owner": "user_id",
                                "#status": "status",
                            },
                            "ExpressionAttributeValues": {
                                ":caller": record["user_id"],
                                ":pending": "pending",
                                ":true": True,
                            },
                        }
                    },
                    _quota_counter_decrement(
                        self.app_state_table_name,
                        f"drinklog-quota#user#{record['user_id']}",
                        timestamp,
                    ),
                    _quota_counter_decrement(
                        self.app_state_table_name,
                        "drinklog-quota#global",
                        timestamp,
                    ),
                ],
            )
            return True
        except self.client.exceptions.TransactionCanceledException:
            return False

    def complete_create(
        self,
        record: Mapping[str, Any],
        final_key: str,
        *,
        now: datetime,
    ) -> dict[str, Any] | None:
        completion = record.get("_completion")
        if not isinstance(completion, Mapping):
            raise CreateConflict("Pending record is missing completion metadata")
        names = {
            "#owner": "user_id",
            "#status": "status",
            "#brand_text": "brand_text",
            "#brand_source": "brand_source",
            "#serving_style": "serving_style",
            "#store": "store",
            "#updated_at": "updated_at",
            "#completion": "_completion",
            "#content_type": "content_type",
            "#tmp_etag": "tmp_etag",
        }
        values: dict[str, Any] = {
            ":caller": record["user_id"],
            ":pending": "pending",
            ":complete": "complete",
            ":final_key": final_key,
            ":brand_text": completion["brand_text"],
            ":brand_source": completion["brand_source"],
            ":serving_style": completion["serving_style"],
            ":store": completion["store"],
            ":updated_at": self.timestamp_format(now),
        }
        sets = [
            "#status = :complete",
            "s3_image_key = :final_key",
            "#brand_text = :brand_text",
            "#brand_source = :brand_source",
            "#serving_style = :serving_style",
            "#store = :store",
            "#updated_at = :updated_at",
        ]
        for field in ("whiskey_id", "ai", "rating", "notes"):
            if field in completion:
                names[f"#{field}"] = field
                values[f":{field}"] = completion[field]
                sets.append(f"#{field} = :{field}")
        try:
            response = self.table.update_item(
                Key={"id": record["id"]},
                UpdateExpression=(
                    f"SET {', '.join(sets)} "
                    "REMOVE #completion, #content_type, #tmp_etag"
                ),
                ConditionExpression="#owner = :caller AND #status = :pending",
                ExpressionAttributeNames=names,
                ExpressionAttributeValues=values,
                ReturnValues="ALL_NEW",
            )
            return response.get("Attributes")
        except self.table.meta.client.exceptions.ConditionalCheckFailedException:
            return None

    def remove_tmp_reference(
        self,
        record_id: str,
        user_id: str,
        tmp_key: str,
    ) -> dict[str, Any] | None:
        try:
            response = self.table.update_item(
                Key={"id": record_id},
                UpdateExpression="REMOVE tmp_s3_key",
                ConditionExpression=(
                    "#owner = :caller AND #status = :complete AND tmp_s3_key = :tmp"
                ),
                ExpressionAttributeNames={"#owner": "user_id", "#status": "status"},
                ExpressionAttributeValues={
                    ":caller": user_id,
                    ":complete": "complete",
                    ":tmp": tmp_key,
                },
                ReturnValues="ALL_NEW",
            )
            return response.get("Attributes")
        except self.table.meta.client.exceptions.ConditionalCheckFailedException:
            return None

    def acquire_pending_for_deletion(
        self,
        item: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        try:
            response = self.table.update_item(
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
        except self.table.meta.client.exceptions.ConditionalCheckFailedException:
            return None

    def create_tombstone(
        self,
        record_id: str,
        user_id: str,
        key: str,
        timestamp: datetime,
    ) -> dict[str, Any] | None:
        object_time = self.timestamp_format(timestamp)
        item = {
            "id": record_id,
            "user_id": user_id,
            "status": "deleting",
            "datetime": object_time,
            "s3_image_key": key,
            "quota_allocated": False,
            "created_at": object_time,
            "updated_at": object_time,
        }
        try:
            self.table.put_item(Item=item, ConditionExpression="attribute_not_exists(id)")
            return item
        except self.table.meta.client.exceptions.ConditionalCheckFailedException:
            return None

    def begin_delete(
        self,
        user_id: str,
        record_id: str,
        *,
        now: datetime,
    ) -> dict[str, Any] | None:
        try:
            response = self.table.update_item(
                Key={"id": record_id},
                UpdateExpression=(
                    "SET #status = :deleting, "
                    "delete_started_at = if_not_exists(delete_started_at, :started_at)"
                ),
                ConditionExpression=(
                    "#owner = :caller AND (#status = :complete OR #status = :deleting)"
                ),
                ExpressionAttributeNames={"#owner": "user_id", "#status": "status"},
                ExpressionAttributeValues={
                    ":caller": user_id,
                    ":complete": "complete",
                    ":deleting": "deleting",
                    ":started_at": self.timestamp_format(now),
                },
                ReturnValues="ALL_NEW",
            )
            item = response.get("Attributes")
            if not item:
                raise RuntimeError("Deleting record was not returned")
            return item
        except self.table.meta.client.exceptions.ConditionalCheckFailedException:
            return None

    def delete_record_image(self, item: Mapping[str, Any]) -> None:
        key = item.get("s3_image_key")
        if not key:
            return
        if not isinstance(key, str) or not key.startswith(f"logs/{item['user_id']}/"):
            raise RuntimeError("Refusing to delete an image outside its owner prefix")
        self.delete_and_confirm(key)

    def finalize_delete(self, item: Mapping[str, Any], *, now: datetime) -> bool:
        delete = {
            "Delete": {
                "TableName": self.drinklogs_table_name,
                "Key": {"id": item["id"]},
                "ConditionExpression": (
                    "#status = :deleting AND #owner = :owner "
                    "AND quota_allocated = :allocated"
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
            timestamp = self.timestamp_format(now)
            transaction.extend(
                [
                    _quota_counter_decrement(
                        self.app_state_table_name,
                        f"drinklog-quota#user#{item['user_id']}",
                        timestamp,
                    ),
                    _quota_counter_decrement(
                        self.app_state_table_name,
                        "drinklog-quota#global",
                        timestamp,
                    ),
                ]
            )
        try:
            transact_write_with_retry(self.client, transaction)
            return True
        except self.client.exceptions.TransactionCanceledException:
            if self.get(item["id"]) is None:
                return True
            raise RuntimeError("Drink log deletion transaction did not converge")

    def delete(self, user_id: str, record_id: str, *, now: datetime) -> bool:
        item = self.begin_delete(user_id, record_id, now=now)
        if item is None:
            return False
        self.delete_record_image(item)
        return self.finalize_delete(item, now=now)
