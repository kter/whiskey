"""Safe no-op placeholder for the scheduled drink log reconciler."""

from typing import Any


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, str]:
    """Succeed without side effects until Task 07 installs reconciliation logic."""
    del event, context
    return {"status": "noop"}
