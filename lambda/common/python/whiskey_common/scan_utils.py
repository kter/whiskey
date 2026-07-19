"""Bounded DynamoDB scan pagination helpers."""

import base64
import binascii
import json
from typing import Any, Mapping

from .decimal_utils import decimal_default


def encode_next_token(last_evaluated_key: Mapping[str, Any] | None) -> str | None:
    if not last_evaluated_key:
        return None
    payload = json.dumps(last_evaluated_key, default=decimal_default, separators=(",", ":"), sort_keys=True)
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")


def decode_next_token(next_token: str | None) -> dict[str, Any] | None:
    if not next_token:
        return None
    try:
        padded = next_token + "=" * (-len(next_token) % 4)
        value = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError, binascii.Error) as exc:
        raise ValueError("Invalid next_token") from exc
    if not isinstance(value, dict):
        raise ValueError("Invalid next_token")
    return value


def scan_all_pages(table: Any, *, max_pages: int = 100, **scan_kwargs: Any) -> tuple[list[dict], str | None]:
    """Scan up to max_pages, returning all items and a continuation token."""
    if max_pages < 1:
        raise ValueError("max_pages must be at least 1")
    items: list[dict] = []
    last_evaluated_key = scan_kwargs.pop("ExclusiveStartKey", None)
    for _ in range(max_pages):
        if last_evaluated_key:
            scan_kwargs["ExclusiveStartKey"] = last_evaluated_key
        response = table.scan(**scan_kwargs)
        items.extend(response.get("Items", []))
        last_evaluated_key = response.get("LastEvaluatedKey")
        if not last_evaluated_key:
            return items, None
    return items, encode_next_token(last_evaluated_key)
