"""Whiskey name search API."""

import os
import sys
import time
from pathlib import Path
from typing import Any

try:
    from whiskey_common.clients import get_dynamodb_resource
    from whiskey_common.cost_guard import ScanBudgetExceeded, consume_scan_budget
    from whiskey_common.logger import extract_correlation_id, get_logger
    from whiskey_common.responses import create_response, get_cors_headers
except ModuleNotFoundError as exc:
    if exc.name != "whiskey_common":
        raise
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common" / "python"))
    from whiskey_common.clients import get_dynamodb_resource
    from whiskey_common.cost_guard import ScanBudgetExceeded, consume_scan_budget
    from whiskey_common.logger import extract_correlation_id, get_logger
    from whiskey_common.responses import create_response, get_cors_headers

sys.path.insert(0, str(Path(__file__).resolve().parent / "python"))
from whiskey_search_service import WhiskeySearchService


def transform_whiskey_item(item: dict[str, Any]) -> dict[str, Any]:
    """Transform supported source schemas into the public search shape."""
    name = item.get("name") or item.get("name_ja") or item.get("name_en", "")
    return {
        "id": item.get("id"),
        "name": name,
        "name_en": item.get("name_en", item.get("name", "")),
        "name_ja": item.get("name_ja", ""),
        "distillery": item.get("distillery") or item.get("distillery_ja") or item.get("distillery_en", ""),
        "region": item.get("region", ""),
        "type": item.get("type", ""),
        "confidence": float(item.get("confidence", 0)),
        "source": item.get("source", ""),
        "created_at": item.get("created_at"),
        "updated_at": item.get("updated_at"),
    }


def handle_search_endpoint(query_params: dict[str, Any], logger: Any) -> dict[str, Any]:
    query = query_params.get("q", "").strip()
    try:
        limit = int(query_params.get("limit", 50))
    except (TypeError, ValueError) as exc:
        raise ValueError("limit must be an integer") from exc
    if not 1 <= limit <= 100:
        raise ValueError("limit must be from 1 to 100")

    dynamodb = get_dynamodb_resource()
    raw_results, next_token = WhiskeySearchService(dynamodb).search_whiskeys(
        query,
        limit=limit,
        next_token=query_params.get("next_token"),
        before_page=lambda: consume_scan_budget(
            dynamodb,
            os.environ["APP_STATE_TABLE"],
            "search",
            int(os.environ.get("PUBLIC_SCAN_DAILY_LIMIT", "10000")),
        ),
    )
    whiskeys = [transform_whiskey_item(item) for item in raw_results]
    whiskeys.sort(key=lambda item: item.get("name", ""))
    logger.debug("Search completed", result_count=len(whiskeys))
    return {
        "whiskeys": whiskeys,
        "count": len(whiskeys),
        "query": query,
        "distillery": "",
        "next_token": next_token,
    }


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    start_time = time.monotonic()
    request_id = (
        getattr(context, "aws_request_id", None)
        or (event.get("requestContext") or {}).get("requestId")
        or "unknown"
    )
    logger = get_logger("whiskeys-search", correlation_id=extract_correlation_id(event))
    logger.log_api_request(
        method=event.get("httpMethod", "UNKNOWN"),
        path=event.get("path", "UNKNOWN"),
        query_params=event.get("queryStringParameters"),
    )
    headers = get_cors_headers(event)
    try:
        query_params = event.get("queryStringParameters") or {}
        body = handle_search_endpoint(query_params, logger)
        return create_response(200, body, headers, start_time=start_time, logger=logger)
    except ValueError as exc:
        return create_response(400, {"error": str(exc)}, headers, start_time=start_time, logger=logger)
    except ScanBudgetExceeded:
        return create_response(
            429,
            {"error": "Daily scan budget exceeded"},
            headers,
            start_time=start_time,
            logger=logger,
        )
    except Exception as exc:
        logger.error("Unhandled error in lambda_handler", error=str(exc), request_id=request_id)
        return create_response(
            500,
            {"error": "Internal server error", "request_id": request_id},
            headers,
            start_time=start_time,
            logger=logger,
        )
