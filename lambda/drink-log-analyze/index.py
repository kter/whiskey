"""Drink log image analysis placeholder for the Phase 4 rollout."""

from typing import Any

from whiskey_common.responses import create_response


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Return a stable placeholder until Task 08 installs analysis logic."""
    del context
    return create_response(
        501,
        {"error": "Not Implemented"},
        event=event,
        private=True,
    )
