"""UTC timestamp helpers with explicit persisted precision."""

from datetime import datetime, timezone


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def rfc3339(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def rfc3339_millis(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
