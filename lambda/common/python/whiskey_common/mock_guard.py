"""Runtime guard for local-only external-service adapters."""

from __future__ import annotations

import os


def _environment_flag_is_set(name: str) -> bool:
    """Return whether an environment flag exists with a non-empty value."""
    return name in os.environ and os.environ[name] != ""


def local_fixture_enabled(flag_name: str) -> bool:
    """Return whether a local-only fixture adapter is selected."""
    return os.environ.get("ENVIRONMENT") == "local" and _environment_flag_is_set(
        flag_name
    )


def validate_mock_guard() -> None:
    """Reject local fixture flags outside the local environment."""
    if os.environ.get("ENVIRONMENT", "dev") != "local" and any(
        _environment_flag_is_set(name) for name in ("MOCK_AI", "MOCK_PLACES")
    ):
        raise RuntimeError("MOCK_AI and MOCK_PLACES are permitted only in local")
