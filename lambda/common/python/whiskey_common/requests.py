"""Shared API Gateway request helpers."""

import json
from typing import Any, Mapping

from .errors import ValidationError


def parse_json_body(event: Mapping[str, Any]) -> dict[str, Any]:
    raw_body = event.get("body")
    if not isinstance(raw_body, str):
        raise ValidationError({"body": "A JSON object is required"})
    try:
        body = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise ValidationError({"body": "Malformed JSON"}) from exc
    if not isinstance(body, dict):
        raise ValidationError({"body": "A JSON object is required"})
    return body


def request_id(event: Mapping[str, Any], context: Any) -> str:
    return (
        getattr(context, "aws_request_id", None)
        or (event.get("requestContext") or {}).get("requestId")
        or "unknown"
    )
