"""Global daily cost guard for anonymous scan endpoints."""

from datetime import datetime, timedelta, timezone
from typing import Any


class ScanBudgetExceeded(Exception):
    """Raised when a public scan endpoint exhausts its daily budget."""


def consume_scan_budget(
    dynamodb: Any,
    app_state_table_name: str,
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
    table = dynamodb.Table(app_state_table_name)
    try:
        table.update_item(
            Key={"pk": f"scan-counter/{operation}/{date}"},
            UpdateExpression="SET #ttl = if_not_exists(#ttl, :ttl), updated_at = :now ADD #count :one",
            ConditionExpression="attribute_not_exists(#count) OR #count < :limit",
            ExpressionAttributeNames={"#count": "count", "#ttl": "ttl"},
            ExpressionAttributeValues={
                ":one": 1,
                ":limit": daily_limit,
                ":ttl": ttl,
                ":now": current.isoformat().replace("+00:00", "Z"),
            },
        )
    except table.meta.client.exceptions.ConditionalCheckFailedException as exc:
        raise ScanBudgetExceeded from exc
