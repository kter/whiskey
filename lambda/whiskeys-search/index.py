"""Whiskey name search and precomputed ranking API."""

import os
import sys
import time
from datetime import datetime, timezone
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


RANKING_META_KEY = "ranking-cache/meta"
RANKING_PAGE_PREFIX = "ranking-cache/generation"
MAX_RANKING_STALE_SECONDS = 45 * 60


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


def _aggregating_response() -> dict[str, str]:
    return {"status": "aggregating"}


def _parse_iso8601(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _ranking_available(meta: dict[str, Any], now: datetime) -> bool:
    if not meta.get("generation_id") or meta.get("invalidated_at"):
        return False
    dirty_since = meta.get("dirty_since")
    if dirty_since and (now - _parse_iso8601(dirty_since)).total_seconds() > MAX_RANKING_STALE_SECONDS:
        return False
    return True


def _ranking_page_key(generation_id: str, page_number: int) -> str:
    return f"{RANKING_PAGE_PREFIX}/{generation_id}/page/{page_number}"


def _read_ranking_slice(
    table: Any,
    meta: dict[str, Any],
    page: int,
    limit: int,
) -> list[dict] | None:
    total_items = int(meta.get("total_items", 0))
    start = (page - 1) * limit
    if start >= total_items:
        return []
    end = min(start + limit, total_items)
    page_sizes = [int(size) for size in meta.get("page_sizes", [])]
    if not page_sizes:
        cache_page_size = int(meta["cache_page_size"])
        page_sizes = [
            min(cache_page_size, max(0, total_items - page * cache_page_size))
            for page in range(int(meta.get("page_count", (total_items + cache_page_size - 1) // cache_page_size)))
        ]
    first_cache_page = 0
    first_page_start = 0
    while first_cache_page < len(page_sizes) and first_page_start + page_sizes[first_cache_page] <= start:
        first_page_start += page_sizes[first_cache_page]
        first_cache_page += 1
    if first_cache_page >= len(page_sizes):
        return None
    last_cache_page = first_cache_page
    covered_until = first_page_start + page_sizes[first_cache_page]
    while covered_until < end and last_cache_page + 1 < len(page_sizes):
        last_cache_page += 1
        covered_until += page_sizes[last_cache_page]
    if covered_until < end:
        return None
    combined: list[dict] = []
    for cache_page in range(first_cache_page, last_cache_page + 1):
        response = table.get_item(
            Key={"pk": _ranking_page_key(meta["generation_id"], cache_page)},
            ConsistentRead=True,
        )
        item = response.get("Item")
        if not item:
            return None
        combined.extend(item.get("rankings", []))
    offset = start - first_page_start
    return combined[offset : offset + (end - start)]


def handle_ranking_endpoint(query_params: dict[str, Any], logger: Any) -> Any:
    try:
        page = int(query_params.get("page", 1))
        limit = int(query_params.get("limit", 20))
    except (TypeError, ValueError) as exc:
        raise ValueError("page and limit must be integers") from exc
    if page < 1 or not 1 <= limit <= 100:
        raise ValueError("page must be positive and limit must be from 1 to 100")

    table = get_dynamodb_resource().Table(os.environ["APP_STATE_TABLE"])
    meta = table.get_item(Key={"pk": RANKING_META_KEY}, ConsistentRead=True).get("Item")
    if not meta or not _ranking_available(meta, datetime.now(timezone.utc)):
        return _aggregating_response()
    rankings = _read_ranking_slice(table, meta, page, limit)
    if rankings is None:
        logger.warning("Ranking generation page is missing", generation_id=meta.get("generation_id"))
        return _aggregating_response()
    if "page" not in query_params and "limit" not in query_params:
        return rankings
    total_items = int(meta.get("total_items", 0))
    total_pages = max(1, (total_items + limit - 1) // limit)
    return {
        "rankings": rankings,
        "pagination": {
            "page": page,
            "limit": limit,
            "total_items": total_items,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_prev": page > 1,
        },
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
        if "/ranking" in event.get("path", ""):
            body = handle_ranking_endpoint(query_params, logger)
        else:
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
