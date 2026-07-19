"""JSON conversion helpers for DynamoDB values."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any


def decimal_default(value: Any) -> Any:
    """Convert DynamoDB and date values into JSON-compatible values."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")
