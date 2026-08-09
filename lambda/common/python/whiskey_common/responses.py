"""Lambda proxy response and CORS helpers."""

import json
import os
import time
from typing import Any, Mapping

from .decimal_utils import decimal_default


def _allowed_origins() -> list[str]:
    return [
        origin.strip()
        for origin in os.environ.get("ALLOWED_ORIGINS", "").split(",")
        if origin.strip()
    ]


def get_cors_headers(event: Mapping[str, Any], *, private: bool = False) -> dict[str, str]:
    """Return CORS headers and echo an origin only when it is allowed."""
    request_headers = event.get("headers") or {}
    origin = request_headers.get("origin") or request_headers.get("Origin")
    allowed_origins = _allowed_origins()

    headers = {
        "Content-Type": "application/json",
        "Access-Control-Allow-Headers": "Content-Type, Authorization",
        "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
        "Vary": "Origin",
    }
    if origin in allowed_origins:
        headers["Access-Control-Allow-Origin"] = origin
    elif allowed_origins:
        headers["Access-Control-Allow-Origin"] = allowed_origins[0]
    if private:
        headers["Cache-Control"] = "private, no-store"
    return headers


def create_response(
    status_code: int,
    body: Any,
    headers: Mapping[str, str] | None = None,
    *,
    event: Mapping[str, Any] | None = None,
    private: bool = False,
    start_time: float | None = None,
    logger: Any = None,
) -> dict[str, Any]:
    """Create a valid API Gateway Lambda proxy response."""
    if headers:
        response_headers = dict(headers)
    else:
        response_headers = get_cors_headers(event or {}, private=private)
    # Only needed on the caller-supplied-headers path: the else branch above passes
    # private=private into get_cors_headers, which already sets this. Keep that
    # argument if you touch the branch, or private responses lose no-store here.
    if private and headers:
        response_headers["Cache-Control"] = "private, no-store"
    response = {
        "statusCode": status_code,
        "headers": response_headers,
        "body": json.dumps(body, default=decimal_default, ensure_ascii=False)
        if isinstance(body, (dict, list))
        else str(body),
    }
    if start_time is not None and logger is not None:
        logger.log_api_response(
            status_code=status_code,
            response_size=len(response["body"].encode("utf-8")),
            duration_ms=(time.monotonic() - start_time) * 1000,
        )
    return response
