"""Semantic reservations that keep application usage within configured budgets."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping

from whiskey_common.transactions import transact_write_with_retry


class UsageBudgetExceeded(Exception):
    """Raised when a costly operation has exhausted its configured allowance."""

    def __init__(self, operation: str, scope: str):
        self.operation = operation
        self.scope = scope
        self.status_code = 503 if scope == "monthly" else 429
        if operation == "analysis":
            message = (
                "Monthly analysis budget exhausted"
                if scope == "monthly"
                else "Daily analysis limit exceeded"
            )
        else:
            message = f"{operation.capitalize()} usage budget exceeded"
        super().__init__(message)


class ScanBudgetExceeded(UsageBudgetExceeded):
    """Raised when a public scan endpoint exhausts its daily budget."""

    def __init__(self) -> None:
        super().__init__("scan", "daily")


class BudgetTransactionConflict(Exception):
    """Raised when a reservation cannot converge after transaction retries."""


def _rfc3339(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _counter_update(
    table_name: str,
    key: str,
    *,
    amount: int,
    limit: int,
    ttl: int,
    now: str,
) -> dict[str, Any]:
    return {
        "Update": {
            "TableName": table_name,
            "Key": {"pk": key},
            "UpdateExpression": (
                "SET #ttl = if_not_exists(#ttl, :ttl), updated_at = :now "
                "ADD #count :amount"
            ),
            "ConditionExpression": (
                "attribute_not_exists(#count) OR #count <= :largest_existing"
            ),
            "ExpressionAttributeNames": {"#count": "count", "#ttl": "ttl"},
            "ExpressionAttributeValues": {
                ":amount": amount,
                ":largest_existing": limit - amount,
                ":ttl": ttl,
                ":now": now,
            },
        }
    }


def _storage_counter_update(
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


def _storage_counter_decrement(table_name: str, key: str, now: str) -> dict[str, Any]:
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


def _transaction_conflict_only(reasons: Any) -> bool:
    if not isinstance(reasons, list) or not reasons:
        return False
    if any(not isinstance(reason, Mapping) for reason in reasons):
        return False
    codes = [reason.get("Code") for reason in reasons]
    return "TransactionConflict" in codes and all(
        code in {None, "None", "TransactionConflict"} for code in codes
    )


@dataclass(frozen=True)
class UsageBudget:
    """Reserve and release the concrete usage allowances used by Whiskey Log."""

    dynamodb: Any
    app_state_table_name: str
    timestamp_format: Callable[[datetime], str] = _rfc3339

    @property
    def client(self) -> Any:
        return self.dynamodb.meta.client

    def reserve_public_scan(
        self,
        operation: str,
        daily_limit: int,
        *,
        now: datetime | None = None,
    ) -> None:
        if daily_limit < 1:
            raise ValueError("daily_limit must be at least 1")
        current = now or datetime.now(timezone.utc)
        date = current.strftime("%Y-%m-%d")
        ttl = int((current + timedelta(days=2)).timestamp())
        table = self.dynamodb.Table(self.app_state_table_name)
        try:
            table.update_item(
                Key={"pk": f"scan-counter/{operation}/{date}"},
                UpdateExpression=(
                    "SET #ttl = if_not_exists(#ttl, :ttl), updated_at = :now "
                    "ADD #count :one"
                ),
                ConditionExpression="attribute_not_exists(#count) OR #count < :limit",
                ExpressionAttributeNames={"#count": "count", "#ttl": "ttl"},
                ExpressionAttributeValues={
                    ":one": 1,
                    ":limit": daily_limit,
                    ":ttl": ttl,
                    ":now": self.timestamp_format(current),
                },
            )
        except table.meta.client.exceptions.ConditionalCheckFailedException as exc:
            raise ScanBudgetExceeded from exc

    def reserve_analysis(
        self,
        user_id: str,
        *,
        user_request: bool,
        now: datetime | None = None,
        remaining_ms: Callable[[], int] | None = None,
    ) -> None:
        current = now or datetime.now(timezone.utc)
        date = current.strftime("%Y-%m-%d")
        month = current.strftime("%Y-%m")
        daily_ttl = int((current + timedelta(days=2)).timestamp())
        monthly_ttl = int((current + timedelta(days=35)).timestamp())
        timestamp = self.timestamp_format(current)
        if user_request:
            writes = [
                _counter_update(
                    self.app_state_table_name,
                    f"drinklog-counter#analyze#user#{user_id}#{date}",
                    amount=1,
                    limit=int(os.environ.get("ANALYZE_USER_DAILY_LIMIT", "20")),
                    ttl=daily_ttl,
                    now=timestamp,
                )
            ]
            labels = ["daily"]
        else:
            writes = [
                _counter_update(
                    self.app_state_table_name,
                    f"drinklog-counter#analyze#global#{date}",
                    amount=1,
                    limit=int(os.environ.get("ANALYZE_GLOBAL_DAILY_LIMIT", "50")),
                    ttl=daily_ttl,
                    now=timestamp,
                ),
                _counter_update(
                    self.app_state_table_name,
                    f"drinklog-counter#analyze#global-month#{month}",
                    amount=1,
                    limit=int(os.environ.get("ANALYZE_GLOBAL_MONTHLY_LIMIT", "300")),
                    ttl=monthly_ttl,
                    now=timestamp,
                ),
            ]
            labels = ["daily", "monthly"]
        try:
            transact_write_with_retry(self.client, writes, remaining_ms=remaining_ms)
        except self.client.exceptions.TransactionCanceledException as exc:
            reasons = exc.response.get("CancellationReasons", [])
            for index, label in enumerate(labels):
                if index < len(reasons) and reasons[index].get("Code") == "ConditionalCheckFailed":
                    raise UsageBudgetExceeded("analysis", label) from exc
            raise

    def reserve_places(
        self,
        user_id: str,
        amount: int,
        *,
        now: datetime | None = None,
    ) -> None:
        if amount < 1:
            raise ValueError("amount must be positive")
        current = now or datetime.now(timezone.utc)
        limits = (
            int(os.environ.get("PLACES_USER_DAILY_LIMIT", "30")),
            int(os.environ.get("PLACES_GLOBAL_DAILY_LIMIT", "15")),
            int(os.environ.get("PLACES_GLOBAL_MONTHLY_LIMIT", "150")),
        )
        if any(amount > limit for limit in limits):
            raise UsageBudgetExceeded("places", "daily")
        date = current.strftime("%Y-%m-%d")
        month = current.strftime("%Y-%m")
        timestamp = self.timestamp_format(current)
        daily_ttl = int((current + timedelta(days=2)).timestamp())
        monthly_ttl = int((current + timedelta(days=35)).timestamp())
        writes = [
            _counter_update(
                self.app_state_table_name,
                f"drinklog-counter#places#user#{user_id}#{date}",
                amount=amount,
                limit=limits[0],
                ttl=daily_ttl,
                now=timestamp,
            ),
            _counter_update(
                self.app_state_table_name,
                f"drinklog-counter#places#global#{date}",
                amount=amount,
                limit=limits[1],
                ttl=daily_ttl,
                now=timestamp,
            ),
            _counter_update(
                self.app_state_table_name,
                f"drinklog-counter#places#global-month#{month}",
                amount=amount,
                limit=limits[2],
                ttl=monthly_ttl,
                now=timestamp,
            ),
        ]
        try:
            transact_write_with_retry(self.client, writes)
        except self.client.exceptions.TransactionCanceledException as exc:
            reasons = exc.response.get("CancellationReasons", [])
            if any(reason.get("Code") == "ConditionalCheckFailed" for reason in reasons):
                raise UsageBudgetExceeded("places", "daily") from exc
            raise

    def reserve_upload(self, user_id: str, *, now: datetime) -> None:
        date = now.astimezone(timezone.utc).strftime("%Y-%m-%d")
        ttl = int((now + timedelta(days=2)).timestamp())
        timestamp = self.timestamp_format(now)
        writes = [
            _counter_update(
                self.app_state_table_name,
                f"drinklog-counter#upload#user#{user_id}#{date}",
                amount=1,
                limit=int(os.environ.get("UPLOAD_USER_DAILY_LIMIT", "30")),
                ttl=ttl,
                now=timestamp,
            ),
            _counter_update(
                self.app_state_table_name,
                f"drinklog-counter#upload#global#{date}",
                amount=1,
                limit=int(os.environ.get("UPLOAD_GLOBAL_DAILY_LIMIT", "100")),
                ttl=ttl,
                now=timestamp,
            ),
        ]
        try:
            transact_write_with_retry(self.client, writes)
        except self.client.exceptions.TransactionCanceledException as exc:
            reasons = exc.response.get("CancellationReasons", [])
            if any(reason.get("Code") == "ConditionalCheckFailed" for reason in reasons):
                raise UsageBudgetExceeded("upload", "daily") from exc
            if _transaction_conflict_only(reasons):
                raise BudgetTransactionConflict from exc
            raise

    def start_drink_log_create(
        self,
        drinklogs_table_name: str,
        pending: Mapping[str, Any],
        consume_analysis: Mapping[str, Any],
        *,
        now: datetime,
    ) -> None:
        date = now.astimezone(timezone.utc).strftime("%Y-%m-%d")
        ttl = int((now + timedelta(days=2)).timestamp())
        timestamp = self.timestamp_format(now)
        user_id = pending["user_id"]
        transaction = [
            {
                "Put": {
                    "TableName": drinklogs_table_name,
                    "Item": dict(pending),
                    "ConditionExpression": "attribute_not_exists(id)",
                }
            },
            _counter_update(
                self.app_state_table_name,
                f"drinklog-counter#create#user#{user_id}#{date}",
                amount=1,
                limit=int(os.environ.get("CREATE_USER_DAILY_LIMIT", "30")),
                ttl=ttl,
                now=timestamp,
            ),
            _counter_update(
                self.app_state_table_name,
                f"drinklog-counter#create#global#{date}",
                amount=1,
                limit=int(os.environ.get("CREATE_GLOBAL_DAILY_LIMIT", "100")),
                ttl=ttl,
                now=timestamp,
            ),
            _storage_counter_update(
                self.app_state_table_name,
                f"drinklog-quota#user#{user_id}",
                int(os.environ.get("STORAGE_USER_LIMIT", "2000")),
                timestamp,
            ),
            _storage_counter_update(
                self.app_state_table_name,
                "drinklog-quota#global",
                int(os.environ.get("STORAGE_GLOBAL_LIMIT", "20000")),
                timestamp,
            ),
            dict(consume_analysis),
        ]
        try:
            transact_write_with_retry(self.client, transaction)
        except self.client.exceptions.TransactionCanceledException as exc:
            reasons = exc.response.get("CancellationReasons", [])
            for index in (1, 2, 3, 4):
                if index < len(reasons) and reasons[index].get("Code") == "ConditionalCheckFailed":
                    scope = "storage" if index in (3, 4) else "daily"
                    raise UsageBudgetExceeded("create", scope) from exc
            if _transaction_conflict_only(reasons):
                raise BudgetTransactionConflict from exc
            raise

    def release_drink_log_storage(
        self,
        delete_write: Mapping[str, Any],
        user_id: str,
        *,
        allocated: bool,
        now: datetime,
    ) -> None:
        transaction = [dict(delete_write)]
        if allocated:
            timestamp = self.timestamp_format(now)
            transaction.extend(
                [
                    _storage_counter_decrement(
                        self.app_state_table_name,
                        f"drinklog-quota#user#{user_id}",
                        timestamp,
                    ),
                    _storage_counter_decrement(
                        self.app_state_table_name,
                        "drinklog-quota#global",
                        timestamp,
                    ),
                ]
            )
        transact_write_with_retry(self.client, transaction)
