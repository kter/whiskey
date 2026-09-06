"""Runtime guard for local-only external-service adapters."""

from __future__ import annotations

import os


def environment_flag_is_set(name: str) -> bool:
    """Return whether an environment flag exists with a non-empty value."""
    return name in os.environ and os.environ[name] != ""


def validate_mock_guard() -> None:
    """Reject local fixture flags outside the local environment."""
    if os.environ.get("ENVIRONMENT", "dev") != "local" and any(
        environment_flag_is_set(name) for name in ("MOCK_AI", "MOCK_PLACES")
    ):
        raise RuntimeError("MOCK_AI and MOCK_PLACES are permitted only in local")
