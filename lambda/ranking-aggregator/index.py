"""Build and atomically publish paged whiskey ranking generations."""

import os
import json
import sys
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from boto3.dynamodb.conditions import Attr

try:
    from whiskey_common.clients import get_dynamodb_resource
    from whiskey_common.decimal_utils import decimal_default
    from whiskey_common.logger import get_logger
    from whiskey_common.scan_utils import scan_all_pages
except ModuleNotFoundError as exc:
    if exc.name != "whiskey_common":
        raise
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common" / "python"))
    from whiskey_common.clients import get_dynamodb_resource
    from whiskey_common.decimal_utils import decimal_default
    from whiskey_common.logger import get_logger
    from whiskey_common.scan_utils import scan_all_pages


RANKING_META_KEY = "ranking-cache/meta"
RANKING_LEASE_KEY = "ranking-cache/lease"
RANKING_PAGE_PREFIX = "ranking-cache/generation"
REVIEW_COUNTER_KEY = "review-change-counter"
WHISKEY_COUNTER_KEY = "whiskey-change-counter"
CACHE_PAGE_SIZE = 100
CACHE_PAGE_MAX_BYTES = 280_000
LEASE_SECONDS = 180
STAGING_TTL_SECONDS = 2 * 60 * 60
OLD_GENERATION_TTL_SECONDS = 24 * 60 * 60
MIN_REMAINING_MILLIS = 15_000


class AggregationDeadlineExceeded(Exception):
    """Raised before Lambda has too little time to safely publish a generation."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _page_key(generation_id: str, page_number: int) -> str:
    return f"{RANKING_PAGE_PREFIX}/{generation_id}/page/{page_number}"


def _manifest_key(generation_id: str) -> str:
    return f"{RANKING_PAGE_PREFIX}/{generation_id}/manifest"


def _ensure_remaining(context: Any) -> None:
    if context and hasattr(context, "get_remaining_time_in_millis"):
        if context.get_remaining_time_in_millis() < MIN_REMAINING_MILLIS:
            raise AggregationDeadlineExceeded("Insufficient Lambda time remaining")


def _get_item(table: Any, key: str) -> dict[str, Any] | None:
    return table.get_item(Key={"pk": key}, ConsistentRead=True).get("Item")


def _counter_snapshot(table: Any) -> dict[str, int]:
    return {
        "reviews": int((_get_item(table, REVIEW_COUNTER_KEY) or {}).get("count", 0)),
        "whiskeys": int((_get_item(table, WHISKEY_COUNTER_KEY) or {}).get("count", 0)),
    }


def _meta_matches(meta: dict[str, Any] | None, counters: dict[str, int]) -> bool:
    return bool(
        meta
        and int(meta.get("review_counter", -1)) == counters["reviews"]
        and int(meta.get("whiskey_counter", -1)) == counters["whiskeys"]
        and not meta.get("invalidated_at")
    )


def _generation_complete(table: Any, meta: dict[str, Any] | None) -> bool:
    if not meta or not meta.get("generation_id"):
        return False
    generation_id = meta["generation_id"]
    for page_number in range(int(meta.get("page_count", 0))):
        if not _get_item(table, _page_key(generation_id, page_number)):
            return False
    return True


def _mark_dirty(table: Any, dirty_since: str) -> None:
    table.update_item(
        Key={"pk": RANKING_META_KEY},
        UpdateExpression="SET dirty_since = if_not_exists(dirty_since, :dirty_since)",
        ExpressionAttributeValues={":dirty_since": dirty_since},
    )


def acquire_lease(
    table: Any,
    owner: str,
    generation_id: str,
    *,
    now_epoch: int | None = None,
) -> dict[str, Any] | None:
    """Acquire or take over the expiring owner lease; return the prior lease."""
    now = now_epoch if now_epoch is not None else int(time.time())
    try:
        response = table.update_item(
            Key={"pk": RANKING_LEASE_KEY},
            UpdateExpression=(
                "SET #owner = :owner, expires_at = :expires_at, "
                "staging_generation = :generation, staging_page_count = :zero"
            ),
            ConditionExpression=(
                "attribute_not_exists(#owner) OR expires_at < :now OR #owner = :owner"
            ),
            ExpressionAttributeNames={"#owner": "owner"},
            ExpressionAttributeValues={
                ":owner": owner,
                ":expires_at": now + LEASE_SECONDS,
                ":generation": generation_id,
                ":zero": 0,
                ":now": now,
            },
            ReturnValues="ALL_OLD",
        )
        return response.get("Attributes", {})
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        return None


def _release_lease(table: Any, owner: str) -> None:
    try:
        table.delete_item(
            Key={"pk": RANKING_LEASE_KEY},
            ConditionExpression="#owner = :owner",
            ExpressionAttributeNames={"#owner": "owner"},
            ExpressionAttributeValues={":owner": owner},
        )
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        return


def _expire_generation(table: Any, generation_id: str, page_count: int, ttl: int) -> None:
    for page_number in range(page_count):
        table.update_item(
            Key={"pk": _page_key(generation_id, page_number)},
            UpdateExpression="SET #ttl = :ttl",
            ExpressionAttributeNames={"#ttl": "ttl"},
            ExpressionAttributeValues={":ttl": ttl},
        )
    table.update_item(
        Key={"pk": _manifest_key(generation_id)},
        UpdateExpression="SET #ttl = :ttl",
        ExpressionAttributeNames={"#ttl": "ttl"},
        ExpressionAttributeValues={":ttl": ttl},
    )


def _scan_sources(dynamodb: Any, context: Any) -> tuple[list[dict], list[dict]]:
    max_pages = int(os.environ.get("AGGREGATOR_MAX_SCAN_PAGES", "1000"))
    reviews, reviews_token = scan_all_pages(
        dynamodb.Table(os.environ["REVIEWS_TABLE"]),
        max_pages=max_pages,
        before_page=lambda: _ensure_remaining(context),
        ConsistentRead=True,
        FilterExpression=Attr("is_public").eq(True),
    )
    if reviews_token:
        raise RuntimeError("Reviews scan page limit reached")
    whiskeys, whiskeys_token = scan_all_pages(
        dynamodb.Table(os.environ["WHISKEY_SEARCH_TABLE"]),
        max_pages=max_pages,
        before_page=lambda: _ensure_remaining(context),
        ConsistentRead=True,
    )
    if whiskeys_token:
        raise RuntimeError("WhiskeySearch scan page limit reached")
    return reviews, whiskeys


def _build_rankings(reviews: list[dict], whiskeys: list[dict]) -> list[dict]:
    stats: dict[str, dict[str, Any]] = {}
    for review in reviews:
        whiskey_id = review.get("whiskey_id")
        if not whiskey_id or review.get("is_public") is not True:
            continue
        entry = stats.setdefault(whiskey_id, {"sum": Decimal("0"), "count": 0})
        entry["sum"] += Decimal(str(review.get("rating", 0)))
        entry["count"] += 1

    rankings = []
    for whiskey in whiskeys:
        whiskey_id = whiskey.get("id")
        stat = stats.get(whiskey_id, {"sum": Decimal("0"), "count": 0})
        review_count = int(stat["count"])
        average = stat["sum"] / review_count if review_count else Decimal("0")
        rankings.append(
            {
                "id": whiskey_id,
                "name": whiskey.get("name") or whiskey.get("name_en") or whiskey.get("name_ja", ""),
                "distillery": (
                    whiskey.get("distillery")
                    or whiskey.get("distillery_en")
                    or whiskey.get("distillery_ja", "")
                ),
                "region": whiskey.get("region", ""),
                "avg_rating": average,
                "review_count": review_count,
            }
        )
    rankings.sort(
        key=lambda item: (
            item["review_count"] > 0,
            item["avg_rating"],
            item["review_count"],
            item["name"],
        ),
        reverse=True,
    )
    return rankings


def _write_staging_generation(
    table: Any,
    generation_id: str,
    rankings: list[dict],
    context: Any,
) -> list[int]:
    ttl = int(time.time()) + STAGING_TTL_SECONDS
    pages: list[list[dict]] = []
    current_page: list[dict] = []
    current_bytes = 0
    for ranking in rankings:
        ranking_bytes = len(
            json.dumps(ranking, default=decimal_default, ensure_ascii=False, separators=(",", ":"))
            .encode("utf-8")
        )
        if ranking_bytes > CACHE_PAGE_MAX_BYTES:
            raise ValueError("A ranking entry is too large to cache safely")
        if current_page and (
            len(current_page) >= CACHE_PAGE_SIZE
            or current_bytes + ranking_bytes > CACHE_PAGE_MAX_BYTES
        ):
            pages.append(current_page)
            current_page = []
            current_bytes = 0
        current_page.append(ranking)
        current_bytes += ranking_bytes
    if current_page:
        pages.append(current_page)
    for page_number, page in enumerate(pages):
        _ensure_remaining(context)
        table.put_item(
            Item={
                "pk": _page_key(generation_id, page_number),
                "generation_id": generation_id,
                "page_number": page_number,
                "rankings": page,
                "ttl": ttl,
            }
        )
    table.put_item(
        Item={
            "pk": _manifest_key(generation_id),
            "generation_id": generation_id,
            "page_count": len(pages),
            "page_sizes": [len(page) for page in pages],
            "ttl": ttl,
        }
    )
    table.update_item(
        Key={"pk": RANKING_LEASE_KEY},
        UpdateExpression="SET staging_page_count = :page_count",
        ExpressionAttributeValues={":page_count": len(pages)},
    )
    return [len(page) for page in pages]


def _remove_staging_ttl(table: Any, generation_id: str, page_count: int) -> None:
    for page_number in range(page_count):
        table.update_item(
            Key={"pk": _page_key(generation_id, page_number)},
            UpdateExpression="REMOVE #ttl",
            ExpressionAttributeNames={"#ttl": "ttl"},
        )
    table.update_item(
        Key={"pk": _manifest_key(generation_id)},
        UpdateExpression="REMOVE #ttl",
        ExpressionAttributeNames={"#ttl": "ttl"},
    )


def _activate_generation(
    table: Any,
    old_meta: dict[str, Any] | None,
    generation_id: str,
    page_sizes: list[int],
    total_items: int,
    counters: dict[str, int],
) -> None:
    values: dict[str, Any] = {
        ":generation": generation_id,
        ":page_count": len(page_sizes),
        ":page_sizes": page_sizes,
        ":total_items": total_items,
        ":cache_page_size": CACHE_PAGE_SIZE,
        ":generated_at": _now_iso(),
        ":review_counter": counters["reviews"],
        ":whiskey_counter": counters["whiskeys"],
    }
    old_generation = old_meta.get("generation_id") if old_meta else None
    condition = (
        "attribute_not_exists(#generation) AND attribute_not_exists(invalidated_at)"
    )
    if old_generation:
        condition = (
            "#generation = :old_generation AND attribute_not_exists(invalidated_at)"
        )
        values[":old_generation"] = old_generation
    table.update_item(
        Key={"pk": RANKING_META_KEY},
        UpdateExpression=(
            "SET #generation = :generation, page_count = :page_count, "
            "page_sizes = :page_sizes, total_items = :total_items, cache_page_size = :cache_page_size, "
            "generated_at = :generated_at, review_counter = :review_counter, "
            "whiskey_counter = :whiskey_counter "
            "REMOVE dirty_since, invalidated_at, #ttl"
        ),
        ConditionExpression=condition,
        ExpressionAttributeNames={"#generation": "generation_id", "#ttl": "ttl"},
        ExpressionAttributeValues=values,
    )


def aggregate_rankings(event: dict[str, Any], context: Any, dynamodb: Any) -> dict[str, Any]:
    table = dynamodb.Table(os.environ["APP_STATE_TABLE"])
    initial_counters = _counter_snapshot(table)
    old_meta = _get_item(table, RANKING_META_KEY)
    force = event.get("force") is True or str(event.get("force", "")).lower() == "true"
    if not force and _meta_matches(old_meta, initial_counters) and _generation_complete(table, old_meta):
        return {"status": "skipped", "generation_id": old_meta["generation_id"]}

    dirty_since = _now_iso()
    if old_meta and not _meta_matches(old_meta, initial_counters):
        _mark_dirty(table, dirty_since)
        old_meta = _get_item(table, RANKING_META_KEY)

    owner = str(uuid.uuid4())
    generation_id = str(uuid.uuid4())
    prior_lease = acquire_lease(table, owner, generation_id)
    if prior_lease is None:
        return {"status": "locked"}
    try:
        abandoned = prior_lease.get("staging_generation")
        if abandoned and abandoned != (old_meta or {}).get("generation_id"):
            _expire_generation(
                table,
                abandoned,
                int(prior_lease.get("staging_page_count", 0)),
                int(time.time()) + STAGING_TTL_SECONDS,
            )

        counters_before_scan = _counter_snapshot(table)
        if counters_before_scan != initial_counters:
            _mark_dirty(table, dirty_since)
            return {"status": "dirty"}
        reviews, whiskeys = _scan_sources(dynamodb, context)
        counters_after_scan = _counter_snapshot(table)
        if counters_after_scan != counters_before_scan:
            _mark_dirty(table, dirty_since)
            return {"status": "dirty"}

        rankings = _build_rankings(reviews, whiskeys)
        page_sizes = _write_staging_generation(table, generation_id, rankings, context)
        page_count = len(page_sizes)
        if _counter_snapshot(table) != counters_after_scan:
            _mark_dirty(table, dirty_since)
            return {"status": "dirty"}

        try:
            _activate_generation(
                table,
                old_meta,
                generation_id,
                page_sizes,
                len(rankings),
                counters_after_scan,
            )
        except table.meta.client.exceptions.ConditionalCheckFailedException:
            _expire_generation(
                table,
                generation_id,
                page_count,
                int(time.time()) + STAGING_TTL_SECONDS,
            )
            return {"status": "superseded"}

        _remove_staging_ttl(table, generation_id, page_count)

        old_generation = (old_meta or {}).get("generation_id")
        if old_generation and old_generation != generation_id:
            _expire_generation(
                table,
                old_generation,
                int((old_meta or {}).get("page_count", 0)),
                int(time.time()) + OLD_GENERATION_TTL_SECONDS,
            )
        return {
            "status": "published",
            "generation_id": generation_id,
            "total_items": len(rankings),
            "page_count": page_count,
        }
    finally:
        _release_lease(table, owner)


def lambda_handler(event: dict[str, Any] | None, context: Any) -> dict[str, Any]:
    logger = get_logger("ranking-aggregator")
    try:
        result = aggregate_rankings(event or {}, context, get_dynamodb_resource())
        logger.info("Ranking aggregation finished", **result)
        return result
    except AggregationDeadlineExceeded as exc:
        logger.warning("Ranking aggregation stopped before deadline", error=str(exc))
        return {"status": "deferred"}
    except Exception as exc:
        logger.error("Ranking aggregation failed", error=str(exc))
        raise
