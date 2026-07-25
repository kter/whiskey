"""Whiskey list Lambda function."""

import os
import sys
from pathlib import Path
from typing import Any

try:
    from whiskey_common.clients import get_dynamodb_resource
    from whiskey_common.cost_guard import ScanBudgetExceeded, consume_scan_budget
    from whiskey_common.logger import extract_correlation_id, get_logger
    from whiskey_common.responses import create_response, get_cors_headers
    from whiskey_common.scan_utils import decode_next_token, scan_all_pages
except ModuleNotFoundError as exc:
    if exc.name != "whiskey_common":
        raise
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common" / "python"))
    from whiskey_common.clients import get_dynamodb_resource
    from whiskey_common.cost_guard import ScanBudgetExceeded, consume_scan_budget
    from whiskey_common.logger import extract_correlation_id, get_logger
    from whiskey_common.responses import create_response, get_cors_headers
    from whiskey_common.scan_utils import decode_next_token, scan_all_pages


def _parse_request(query: dict[str, Any]) -> tuple[int, dict[str, Any] | None]:
    try:
        limit = int(query.get("limit", "100"))
    except (TypeError, ValueError) as exc:
        raise ValueError("limit must be an integer") from exc
    if not 1 <= limit <= 100:
        raise ValueError("limit must be from 1 to 100")
    return limit, decode_next_token(query.get("next_token"))


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    request_id = (
        getattr(context, "aws_request_id", None)
        or (event.get("requestContext") or {}).get("requestId")
        or "unknown"
    )
    logger = get_logger("whiskeys-list", correlation_id=extract_correlation_id(event) or request_id)
    headers = get_cors_headers(event)
    logger.log_api_request(
        method=event.get("httpMethod", "UNKNOWN"),
        path=event.get("path", "UNKNOWN"),
        query_params=event.get("queryStringParameters"),
    )
    try:
        query = event.get("queryStringParameters") or {}
        limit, start_key = _parse_request(query)
        dynamodb = get_dynamodb_resource()
        consume_scan_budget(
            dynamodb,
            os.environ["APP_STATE_TABLE"],
            "list",
            int(os.environ.get("PUBLIC_SCAN_DAILY_LIMIT", "10000")),
        )
        kwargs: dict[str, Any] = {"Limit": limit}
        if start_key:
            kwargs["ExclusiveStartKey"] = start_key
        items, next_token = scan_all_pages(
            dynamodb.Table(os.environ["WHISKEYS_TABLE"]),
            max_pages=int(os.environ.get("PUBLIC_SCAN_MAX_PAGES", "1")),
            **kwargs,
        )
        whiskeys = [
            {
                "id": item["id"],
                "name": item.get("name_en", item.get("name", "")),
                "distillery": item.get("distillery_en", item.get("distillery", "")),
                "created_at": item.get("created_at", ""),
                "updated_at": item.get("updated_at", ""),
            }
            for item in items
        ]
        whiskeys.sort(key=lambda whiskey: whiskey["name"])
        return create_response(
            200,
            {"whiskeys": whiskeys, "count": len(whiskeys), "next_token": next_token},
            headers,
        )
    except ValueError as exc:
        return create_response(400, {"error": str(exc)}, headers)
    except ScanBudgetExceeded:
        return create_response(429, {"error": "Daily scan budget exceeded"}, headers)
    except Exception as exc:
        logger.error("Unhandled whiskey list error", error=str(exc), request_id=request_id)
        return create_response(500, {"error": "Internal server error", "request_id": request_id}, headers)
