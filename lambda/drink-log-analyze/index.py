"""Authenticated, budget-bounded drink-log image analysis."""

from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

try:
    from whiskey_common.clients import get_dynamodb_resource, get_s3_client
    from whiskey_common.images import ImageNormalizationError, normalize_image, sniff_format
    from whiskey_common.jwt_utils import extract_user_id_from_event
    from whiskey_common.logger import extract_correlation_id, get_logger
    from whiskey_common.normalize import normalize_text
    from whiskey_common.responses import create_response
    from whiskey_common.transactions import transact_write_with_retry
except ModuleNotFoundError as exc:
    if exc.name != "whiskey_common":
        raise
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common" / "python"))
    from whiskey_common.clients import get_dynamodb_resource, get_s3_client
    from whiskey_common.images import ImageNormalizationError, normalize_image, sniff_format
    from whiskey_common.jwt_utils import extract_user_id_from_event
    from whiskey_common.logger import extract_correlation_id, get_logger
    from whiskey_common.normalize import normalize_text
    from whiskey_common.responses import create_response
    from whiskey_common.transactions import transact_write_with_retry


SERVING_STYLES = {"NEAT", "ROCKS", "WATER", "SODA", "COCKTAIL"}
SERVING_STYLE_ALIASES = {"HIGHBALL": "SODA", "SODA": "SODA"}
UUID_TEXT = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}"
UPLOAD_KEY_RE = re.compile(rf"^tmp/([^/]+)/({UUID_TEXT})\.(jpg|jpeg|png|webp)$")
MAX_CANDIDATES = 5
MASTER_SNAPSHOT_TTL_SECONDS = 300
MASTER_SNAPSHOT_MAX_PAGES = 20
MASTER_SNAPSHOT_MAX_ITEMS = 5000
ANALYSIS_TTL_SECONDS = 30 * 60
HANDLER_BUDGET_MS = 24_000
INVOKE_SAFETY_MS = 4_000
MIN_INVOKE_BUDGET_MS = 2_000
PROMPT = (
    "この写真に写っているウイスキーと飲み方を判定してください。"
    "日本で一般に流通している正式な日本語表記で答えてください。"
    "熟成年数が読み取れる場合は必ず名前に含めてください。"
    "判別できなければ whiskeys は空配列にし、推測しないでください。"
    "複数のボトルが写っている場合は全て列挙してください（最大5件）。"
    "ラベルに書かれていないカスク種別や熟成年数などの情報を補完しないでください。"
    "brand_ja と brand_en は蒸留所またはブランドの名前だけにしてください。"
    "熟成年数・カスク・限定表記・シングルモルト等の種別語は含めないでください。"
    "ラベルで最も大きい文字ではなく、蒸留所またはブランドを特定してください。"
    "ハイボールは serving_style を SODA にしてください。"
    "次のキーだけを持つ厳密な JSON を返してください: "
    '{"whiskeys":[{"name_ja":"カリラ 12年","name_en":"Caol Ila 12 Year Old",'
    '"brand_ja":"カリラ","brand_en":"Caol Ila","confidence":0.95}],'
    '"serving_style":"NEAT|ROCKS|WATER|SODA|COCKTAIL",'
    '"glass_type":""}. '
    "confidence は0以上1以下にしてください。Markdownや説明は含めないでください。"
)

_MASTER_CACHE_LOCK = threading.Lock()
_MASTER_CACHE: dict[str, Any] | None = None

_BRAND_PREFIX_RE = re.compile(r"^the\s+", re.IGNORECASE)
_BRAND_SUFFIX_RE = re.compile(
    r"(?:蒸溜所|蒸留所|蒸溜|蒸留|\s+(?:distillery|distillers))$",
    re.IGNORECASE,
)


def _normalized_brand_name_variants(name: str) -> tuple[str, ...]:
    """Return normalized brand names with distillery affixes removed."""
    variants = [name]
    without_prefix = _BRAND_PREFIX_RE.sub("", name)
    if without_prefix != name:
        variants.append(without_prefix)
    for variant in tuple(variants):
        without_suffix = _BRAND_SUFFIX_RE.sub("", variant)
        if without_suffix != variant:
            variants.append(without_suffix)
    return tuple(
        dict.fromkeys(
            normalized
            for variant in variants
            if (normalized := normalize_text(variant))
        )
    )


def _load_brand_catalog() -> tuple[dict[str, Any], ...]:
    """Load the brand layer shipped with the analysis Lambda."""
    path = Path(__file__).with_name("brands.json")
    with path.open(encoding="utf-8") as source_file:
        document = json.load(source_file)
    if not isinstance(document, dict):
        raise RuntimeError("brands.json must use catalog version 1")
    brands = document.get("brands")
    if document.get("version") != 1 or not isinstance(brands, list):
        raise RuntimeError("brands.json must use catalog version 1")

    records: list[dict[str, Any]] = []
    for brand in brands:
        if not isinstance(brand, dict):
            raise RuntimeError("brands.json contains an invalid brand")
        names = [
            brand.get("brand_ja"),
            brand.get("brand_en"),
        ]
        aliases = brand.get("aliases")
        if isinstance(aliases, list):
            names.extend(aliases)
        distillery_names = [
            brand.get("distillery_ja"),
            brand.get("distillery_en"),
        ]
        normalized_names = tuple(
            dict.fromkeys(
                normalized
                for name in names
                if isinstance(name, str)
                for normalized in _normalized_brand_name_variants(name)
            )
        )
        normalized_distillery_names = tuple(
            dict.fromkeys(
                normalized
                for name in distillery_names
                if isinstance(name, str)
                for normalized in _normalized_brand_name_variants(name)
            )
        )
        if (
            not isinstance(brand.get("brand_key"), str)
            or not isinstance(brand.get("distillery_ja"), str)
            or not normalized_names
        ):
            raise RuntimeError("brands.json contains an invalid brand")
        records.append(
            {
                **brand,
                "_normalized_names": normalized_names,
                "_normalized_distillery_names": normalized_distillery_names,
            }
        )

    brand_name_owners: dict[str, set[str]] = {}
    distillery_name_owners: dict[str, set[str]] = {}
    for record in records:
        for normalized_name in record["_normalized_names"]:
            brand_name_owners.setdefault(normalized_name, set()).add(record["brand_key"])
        for normalized_name in record["_normalized_distillery_names"]:
            distillery_name_owners.setdefault(normalized_name, set()).add(
                record["brand_key"]
            )

    # Intentionally omit distillery names shared by multiple brands: a distillery
    # alone cannot identify one brand. Real examples include Midleton shared by
    # jameson/redbreast and Nikka Whisky shared by nikka/taketsuru. A shared name
    # is retained only when it is also the current brand's own unique name.
    return tuple(
        {
            **{
                key: value
                for key, value in record.items()
                if key != "_normalized_distillery_names"
            },
            "_normalized_names": tuple(
                dict.fromkeys(
                    (
                        *record["_normalized_names"],
                        *(
                            name
                            for name in record["_normalized_distillery_names"]
                            if brand_name_owners.get(name) == {record["brand_key"]}
                            or (
                                name not in brand_name_owners
                                and distillery_name_owners[name]
                                == {record["brand_key"]}
                            )
                        ),
                    )
                )
            ),
        }
        for record in records
    )


BRAND_CATALOG = _load_brand_catalog()


class ValidationError(ValueError):
    """Raised for caller-controlled invalid input."""

    def __init__(self, fields: Mapping[str, str]):
        super().__init__("Validation failed")
        self.fields = dict(fields)


class OwnershipError(Exception):
    """Raised when an upload key is outside the caller's namespace."""


class BudgetExceeded(Exception):
    """Raised when a configured cost ceiling rejects a reservation."""

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _rfc3339(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _env_flag_is_set(name: str) -> bool:
    return name in os.environ and os.environ[name] != ""


def _validate_runtime_config() -> str:
    environment = os.environ.get("ENVIRONMENT", "dev")
    if environment != "local" and any(
        _env_flag_is_set(name) for name in ("MOCK_AI", "MOCK_PLACES")
    ):
        raise RuntimeError("MOCK_AI and MOCK_PLACES are permitted only in local")
    model_id = os.environ.get("BEDROCK_MODEL_ID", "")
    allowlist = {
        value.strip()
        for value in os.environ.get("BEDROCK_MODEL_ALLOWLIST", "").split(",")
        if value.strip()
    }
    if not model_id or model_id not in allowlist:
        raise RuntimeError("BEDROCK_MODEL_ID is not in BEDROCK_MODEL_ALLOWLIST")
    if model_id.startswith("global."):
        raise RuntimeError("Global Bedrock inference profiles are not permitted")
    return model_id


def _parse_input(event: Mapping[str, Any]) -> str:
    raw = event.get("body")
    if not isinstance(raw, str):
        raise ValidationError({"body": "A JSON object is required"})
    try:
        body = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValidationError({"body": "Malformed JSON"}) from exc
    if not isinstance(body, dict):
        raise ValidationError({"body": "A JSON object is required"})
    if set(body) != {"s3_key"}:
        fields = {name: "Field is not accepted" for name in sorted(set(body) - {"s3_key"})}
        if "s3_key" not in body:
            fields["s3_key"] = "Field is required"
        raise ValidationError(fields)
    s3_key = body.get("s3_key")
    if not isinstance(s3_key, str) or not UPLOAD_KEY_RE.fullmatch(s3_key):
        raise ValidationError({"s3_key": "Must be a supported temporary upload key"})
    return s3_key


def _upload_identity(s3_key: str, user_id: str) -> str:
    match = UPLOAD_KEY_RE.fullmatch(s3_key)
    if not match or match.group(1) != user_id:
        raise OwnershipError
    return str(uuid.UUID(match.group(2)))


def _read_body(response: Mapping[str, Any]) -> bytes:
    body = response["Body"]
    try:
        return body.read()
    finally:
        close = getattr(body, "close", None)
        if close:
            close()


def _counter_update(table_name: str, key: str, limit: int, ttl: int, now: str) -> dict[str, Any]:
    return {
        "Update": {
            "TableName": table_name,
            "Key": {"pk": key},
            "UpdateExpression": (
                "SET #ttl = if_not_exists(#ttl, :ttl), updated_at = :now ADD #count :one"
            ),
            "ConditionExpression": "attribute_not_exists(#count) OR #count < :limit",
            "ExpressionAttributeNames": {"#count": "count", "#ttl": "ttl"},
            "ExpressionAttributeValues": {
                ":one": 1,
                ":limit": limit,
                ":ttl": ttl,
                ":now": now,
            },
        }
    }


def _reserve_analysis_budget(
    dynamodb: Any,
    table_name: str,
    user_id: str,
    *,
    user_request: bool,
    now_dt: datetime | None = None,
    remaining_ms: Callable[[], int] | None = None,
) -> None:
    current = now_dt or _utc_now()
    date = current.strftime("%Y-%m-%d")
    month = current.strftime("%Y-%m")
    daily_ttl = int((current + timedelta(days=2)).timestamp())
    monthly_ttl = int((current + timedelta(days=35)).timestamp())
    now = _rfc3339(current)
    writes: list[dict[str, Any]] = []
    labels: list[str] = []
    if user_request:
        writes.append(
            _counter_update(
                table_name,
                f"drinklog-counter#analyze#user#{user_id}#{date}",
                int(os.environ.get("ANALYZE_USER_DAILY_LIMIT", "20")),
                daily_ttl,
                now,
            )
        )
        labels.append("daily")
    else:
        writes.extend(
            [
                _counter_update(
                    table_name,
                    f"drinklog-counter#analyze#global#{date}",
                    int(os.environ.get("ANALYZE_GLOBAL_DAILY_LIMIT", "50")),
                    daily_ttl,
                    now,
                ),
                _counter_update(
                    table_name,
                    f"drinklog-counter#analyze#global-month#{month}",
                    int(os.environ.get("ANALYZE_GLOBAL_MONTHLY_LIMIT", "1000")),
                    monthly_ttl,
                    now,
                ),
            ]
        )
        labels.extend(("daily", "monthly"))
    client = dynamodb.meta.client
    try:
        transact_write_with_retry(client, writes, remaining_ms=remaining_ms)
    except client.exceptions.TransactionCanceledException as exc:
        reasons = exc.response.get("CancellationReasons", [])
        for index, label in enumerate(labels):
            if index < len(reasons) and reasons[index].get("Code") == "ConditionalCheckFailed":
                if label == "monthly":
                    raise BudgetExceeded(503, "Monthly analysis budget exhausted") from exc
                raise BudgetExceeded(429, "Daily analysis limit exceeded") from exc
        raise


def strip_json_code_fence(text: str) -> str:
    """Remove a single leading/trailing Markdown JSON fence."""
    stripped = text.strip()
    match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", stripped, flags=re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else stripped


def _decimal_confidence(value: Any) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not result.is_finite() or result < 0 or result > 1:
        return None
    return result


def _validate_model_output(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict) or set(payload) != {
        "whiskeys",
        "serving_style",
        "glass_type",
    }:
        return None
    raw_whiskeys = payload.get("whiskeys")
    if not isinstance(raw_whiskeys, list) or len(raw_whiskeys) > MAX_CANDIDATES:
        return None
    whiskeys: list[dict[str, Any]] = []
    for whiskey in raw_whiskeys:
        required_keys = {"name_ja", "name_en", "confidence"}
        allowed_keys = required_keys | {"brand_ja", "brand_en"}
        if (
            not isinstance(whiskey, dict)
            or not required_keys <= set(whiskey)
            or not set(whiskey) <= allowed_keys
        ):
            return None
        name_ja = whiskey.get("name_ja")
        name_en = whiskey.get("name_en")
        confidence = _decimal_confidence(whiskey.get("confidence"))
        if (
            not isinstance(name_ja, str)
            or not isinstance(name_en, str)
            or len(name_ja) > 200
            or len(name_en) > 200
            or not name_ja.strip()
            or confidence is None
        ):
            return None
        validated_whiskey = {
            "name_ja": name_ja,
            "name_en": name_en,
            "confidence": confidence,
        }
        for brand_field in ("brand_ja", "brand_en"):
            if brand_field in whiskey:
                brand_name = whiskey[brand_field]
                if not isinstance(brand_name, str) or len(brand_name) > 200:
                    return None
                if brand_name.strip():
                    validated_whiskey[brand_field] = brand_name
        whiskeys.append(validated_whiskey)
    serving_raw = payload.get("serving_style")
    if not isinstance(serving_raw, str):
        return None
    serving_style = SERVING_STYLE_ALIASES.get(serving_raw.upper(), serving_raw.upper())
    if serving_style not in SERVING_STYLES:
        return None
    glass_type = payload.get("glass_type")
    if not isinstance(glass_type, str) or len(glass_type) > 200:
        return None
    return {
        "whiskeys": whiskeys,
        "serving_style": serving_style,
        "glass_type": glass_type,
    }


def _extract_response_text(response: Mapping[str, Any]) -> str:
    content = (((response.get("output") or {}).get("message") or {}).get("content") or [])
    texts = [block.get("text") for block in content if isinstance(block, Mapping)]
    if not texts or any(not isinstance(text, str) for text in texts):
        raise ValueError("Bedrock response did not contain text")
    return "".join(texts)


def _remaining_budget_ms(context: Any, started: float) -> int:
    wall_remaining = HANDLER_BUDGET_MS - int((time.monotonic() - started) * 1000)
    get_remaining = getattr(context, "get_remaining_time_in_millis", None)
    lambda_remaining = int(get_remaining()) if callable(get_remaining) else wall_remaining
    return min(wall_remaining, lambda_remaining) - INVOKE_SAFETY_MS


def _bedrock_client(read_timeout: float):
    config = Config(
        connect_timeout=min(2.0, read_timeout),
        read_timeout=read_timeout,
        retries={"mode": "standard", "total_max_attempts": 1},
    )
    kwargs: dict[str, Any] = {"config": config}
    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
    if region:
        kwargs["region_name"] = region
    return boto3.client("bedrock-runtime", **kwargs)


def _invoke_model(model_id: str, image: bytes, context: Any, started: float) -> dict[str, Any] | None:
    remaining_ms = _remaining_budget_ms(context, started)
    if remaining_ms < MIN_INVOKE_BUDGET_MS:
        return None
    if os.environ.get("ENVIRONMENT") == "local" and _env_flag_is_set("MOCK_AI"):
        return {
            "whiskeys": [
                {"name_ja": "モックウイスキー", "name_en": "Mock Whisky", "confidence": Decimal("0.9")}
            ],
            "serving_style": "NEAT",
            "glass_type": "tumbler",
        }
    client = _bedrock_client(max(0.1, remaining_ms / 1000))
    try:
        response = client.converse(
            modelId=model_id,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"image": {"format": "jpeg", "source": {"bytes": image}}},
                        {"text": PROMPT},
                    ],
                }
            ],
            inferenceConfig={"maxTokens": 512, "temperature": 0},
        )
        parsed = json.loads(strip_json_code_fence(_extract_response_text(response)))
    except (BotoCoreError, ClientError):
        return None
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}
    return _validate_model_output(parsed) or {}


def _whiskey_names(whiskey: Mapping[str, Any]) -> list[str]:
    return [
        value
        for value in (whiskey.get("name_ja"), whiskey.get("name_en"))
        if isinstance(value, str) and value
    ]


def _whiskey_id(item: Mapping[str, Any]) -> str | None:
    value = item.get("id")
    return value if isinstance(value, str) and value else None


def _snapshot_record(item: Mapping[str, Any]) -> dict[str, Any]:
    record = dict(item)
    names = [
        value
        for value in (
            item.get("name_ja"),
            item.get("name_en"),
            item.get("name"),
            item.get("normalized_name"),
        )
        if isinstance(value, str) and value
    ]
    normalized_names = tuple(
        dict.fromkeys(normalized for name in names if (normalized := normalize_text(name)))
    )
    record["_normalized_names"] = normalized_names
    return record


def _reset_master_cache() -> None:
    """Clear the module-level master snapshot cache for tests."""
    global _MASTER_CACHE
    with _MASTER_CACHE_LOCK:
        _MASTER_CACHE = None


def _build_master_snapshot(table: Any, table_name: str, logger: Any = None) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    last_key = None
    page_count = 0
    complete = True
    incomplete_reason = None
    while page_count < MASTER_SNAPSHOT_MAX_PAGES:
        kwargs: dict[str, Any] = {
            "ProjectionExpression": "id, #name, name_ja, name_en, normalized_name",
            "ExpressionAttributeNames": {"#name": "name"},
        }
        if last_key:
            kwargs["ExclusiveStartKey"] = last_key
        try:
            response = table.scan(**kwargs)
        except (BotoCoreError, ClientError) as exc:
            complete = False
            incomplete_reason = "scan_error"
            if logger is not None:
                logger.warning(
                    "Master snapshot scan failed",
                    error_type=type(exc).__name__,
                )
            break
        page_count += 1
        page_items = response.get("Items", [])
        if not isinstance(page_items, list):
            page_items = []
        remaining = MASTER_SNAPSHOT_MAX_ITEMS - len(items)
        items.extend(_snapshot_record(item) for item in page_items[:remaining])
        last_key = response.get("LastEvaluatedKey")
        if len(page_items) > remaining or (
            len(items) >= MASTER_SNAPSHOT_MAX_ITEMS and last_key
        ):
            complete = False
            incomplete_reason = "max_items"
            break
        if not last_key:
            break
    else:
        complete = not bool(last_key)
        if not complete:
            incomplete_reason = "max_pages"

    snapshot = {
        "table_name": table_name,
        "expires_at": time.monotonic() + MASTER_SNAPSHOT_TTL_SECONDS,
        "items": tuple(items),
        "complete": complete,
        "incomplete_reason": incomplete_reason,
        "page_count": page_count,
    }
    if not complete and incomplete_reason != "scan_error" and logger is not None:
        logger.warning(
            "Master snapshot incomplete",
            master_snapshot_size=len(items),
            page_count=page_count,
            incomplete_reason=incomplete_reason,
        )
    return snapshot


def _get_master_snapshot(table: Any, table_name: str, logger: Any = None) -> dict[str, Any]:
    global _MASTER_CACHE
    now = time.monotonic()
    cached = _MASTER_CACHE
    if (
        cached is not None
        and cached["table_name"] == table_name
        and cached["expires_at"] > now
    ):
        return cached
    with _MASTER_CACHE_LOCK:
        cached = _MASTER_CACHE
        now = time.monotonic()
        if (
            cached is not None
            and cached["table_name"] == table_name
            and cached["expires_at"] > now
        ):
            return cached
        snapshot = _build_master_snapshot(table, table_name, logger)
        if snapshot.get("incomplete_reason") != "scan_error":
            _MASTER_CACHE = snapshot
        return snapshot


def _cached_master_snapshot(table_name: str) -> dict[str, Any] | None:
    """Return the warm cache for this table, if any."""
    cached = _MASTER_CACHE
    if (
        cached is not None
        and cached["table_name"] == table_name
        and cached["expires_at"] > time.monotonic()
    ):
        return cached
    return None


def _master_snapshot_within_budget(
    table: Any,
    table_name: str,
    context: Any,
    started: float,
    logger: Any = None,
) -> dict[str, Any]:
    """Skip the catalog scan when there is not enough time left to afford it.

    The scan runs after the model call and can take up to
    MASTER_SNAPSHOT_MAX_PAGES sequential round trips on a cold container. With
    no guard it can push the handler past the Lambda timeout, which surfaces as
    a 502 instead of a graceful degradation. A warm cache costs nothing, so it
    is always used; only an actual scan is gated.
    """
    cached = _cached_master_snapshot(table_name)
    if cached is not None:
        return cached
    if _remaining_budget_ms(context, started) >= MIN_INVOKE_BUDGET_MS:
        return _get_master_snapshot(table, table_name, logger)
    if logger is not None:
        logger.warning("Skipped master snapshot scan", reason="insufficient_budget")
    # An incomplete snapshot makes every candidate fall back to match_source
    # "ai": the record still saves, it just carries no catalog id.
    return {
        "table_name": table_name,
        "expires_at": 0.0,
        "items": (),
        "complete": False,
        "incomplete_reason": "insufficient_budget",
        "page_count": 0,
    }


def _unique_records(records: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    unique: dict[str, Mapping[str, Any]] = {}
    for record in records:
        record_id = _whiskey_id(record)
        if record_id:
            unique[record_id] = record
    return list(unique.values())


def _catalog_match(
    snapshot: Mapping[str, Any],
    whiskey: Mapping[str, Any],
) -> Mapping[str, Any] | None:
    if not snapshot.get("complete"):
        return None

    normalized_names = tuple(
        dict.fromkeys(
            normalized
            for name in _whiskey_names(whiskey)
            if (normalized := normalize_text(name))
        )
    )
    exact_matches = _unique_records(
        [
            item
            for item in snapshot.get("items", ())
            if set(normalized_names).intersection(item.get("_normalized_names", ()))
        ]
    )
    return exact_matches[0] if len(exact_matches) == 1 else None


def _brand_catalog_match(whiskey: Mapping[str, Any]) -> Mapping[str, Any] | None:
    normalized_names = {
        normalized
        for field in ("brand_ja", "brand_en")
        if isinstance(name := whiskey.get(field), str)
        for normalized in _normalized_brand_name_variants(name)
    }
    matches = [
        brand
        for brand in BRAND_CATALOG
        if normalized_names.intersection(brand["_normalized_names"])
    ]
    return matches[0] if len(matches) == 1 else None


def _build_candidates(
    snapshot: Mapping[str, Any],
    analysis: Mapping[str, Any],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for whiskey in analysis.get("whiskeys", []):
        matched = _catalog_match(snapshot, whiskey)
        brand_matched = _brand_catalog_match(whiskey)
        candidate = {
            "brand_text": whiskey["name_ja"],
            "name_ja": whiskey["name_ja"],
            "name_en": whiskey["name_en"],
            "confidence": whiskey["confidence"],
            "match_source": "catalog" if matched is not None else "ai",
        }
        if matched is not None and (whiskey_id := _whiskey_id(matched)):
            candidate["whiskey_id"] = whiskey_id
        for brand_field in ("brand_ja", "brand_en"):
            if whiskey.get(brand_field):
                candidate[brand_field] = whiskey[brand_field]
        if brand_matched is not None:
            candidate["brand_key"] = brand_matched["brand_key"]
            if brand_matched["distillery_ja"]:
                candidate["distillery_ja"] = brand_matched["distillery_ja"]
        candidates.append(candidate)
    return candidates


def analyze_upload(
    dynamodb: Any,
    s3: Any,
    *,
    app_state_table_name: str,
    whiskey_table_name: str,
    bucket_name: str,
    user_id: str,
    s3_key: str,
    model_id: str,
    context: Any,
    started: float,
    logger: Any = None,
) -> dict[str, Any]:
    upload_uuid = _upload_identity(s3_key, user_id)
    head = s3.head_object(Bucket=bucket_name, Key=s3_key)
    content_length = head.get("ContentLength")
    etag = head.get("ETag")
    if (
        isinstance(content_length, bool)
        or not isinstance(content_length, int)
        or content_length <= 0
        or content_length > int(os.environ.get("UPLOAD_MAX_BYTES", "3670016"))
        or not isinstance(etag, str)
        or not etag
    ):
        raise ValidationError({"s3_key": "Uploaded image size or ETag is invalid"})

    prefix = _read_body(s3.get_object(Bucket=bucket_name, Key=s3_key, Range="bytes=0-15"))
    if sniff_format(prefix) not in {"jpeg", "png", "webp"}:
        raise ValidationError({"s3_key": "Uploaded file is not a supported image"})
    raw = _read_body(s3.get_object(Bucket=bucket_name, Key=s3_key, IfMatch=etag))
    normalized = normalize_image(raw, max_bytes=int(os.environ.get("IMAGE_MAX_BYTES", "1572864")))

    _reserve_analysis_budget(
        dynamodb,
        app_state_table_name,
        user_id,
        user_request=True,
        remaining_ms=lambda: _remaining_budget_ms(context, started),
    )
    analysis: dict[str, Any] | None = None
    for _attempt in range(2):
        if _remaining_budget_ms(context, started) < MIN_INVOKE_BUDGET_MS:
            break
        _reserve_analysis_budget(
            dynamodb,
            app_state_table_name,
            user_id,
            user_request=False,
            remaining_ms=lambda: _remaining_budget_ms(context, started),
        )
        analysis = _invoke_model(model_id, normalized, context, started)
        if analysis is None or analysis:
            break
    if not analysis:
        analysis = {
            "whiskeys": [],
            "serving_style": "NEAT",
            "glass_type": "",
        }

    snapshot = _master_snapshot_within_budget(
        dynamodb.Table(whiskey_table_name),
        whiskey_table_name,
        context,
        started,
        logger,
    )
    candidates = _build_candidates(snapshot, analysis)
    if logger is not None:
        catalog_count = sum(
            candidate["match_source"] == "catalog" for candidate in candidates
        )
        logger.info(
            "Brand candidates resolved",
            detected_count=len(candidates),
            match_source_counts={
                "catalog": catalog_count,
                "ai": len(candidates) - catalog_count,
            },
            whiskey_id_present_count=sum(
                "whiskey_id" in candidate for candidate in candidates
            ),
            model_id=model_id,
            master_snapshot_complete=snapshot["complete"],
            master_snapshot_size=len(snapshot["items"]),
        )
    expires_at = int((_utc_now() + timedelta(seconds=ANALYSIS_TTL_SECONDS)).timestamp())
    analysis_id = f"ai-result:{user_id}:{upload_uuid}"
    item: dict[str, Any] = {
        "pk": analysis_id,
        "user": user_id,
        "s3_key": s3_key,
        "ETag": etag,
        "candidates": candidates,
        "serving_style": analysis["serving_style"],
        "model_id": model_id,
        "expires_at": expires_at,
        "ttl": expires_at,
    }
    if candidates:
        item["confidence"] = candidates[0]["confidence"]
        if candidates[0].get("whiskey_id"):
            item["whiskey_id"] = candidates[0]["whiskey_id"]
    dynamodb.Table(app_state_table_name).put_item(Item=item)
    response = {
        "analysis_id": analysis_id,
        "candidates": candidates,
        "serving_style": item["serving_style"],
        "model_id": model_id,
        "confidence": item.get("confidence"),
        "multiple_detected": len(candidates) > 1,
    }
    return response


def _request_id(event: Mapping[str, Any], context: Any) -> str:
    return (
        getattr(context, "aws_request_id", None)
        or (event.get("requestContext") or {}).get("requestId")
        or "unknown"
    )


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Handle POST /api/drink-logs/analyze."""
    started = time.monotonic()
    model_id = _validate_runtime_config()
    request_id = _request_id(event, context)
    logger = get_logger("drink-log-analyze", correlation_id=extract_correlation_id(event) or request_id)
    logger.log_api_request(
        method=event.get("httpMethod", "UNKNOWN"),
        path=event.get("path", "UNKNOWN"),
        body={"s3_key": "present"} if event.get("body") else None,
    )
    user_id = extract_user_id_from_event(event)
    if not user_id:
        return create_response(401, {"error": "Authentication required"}, event=event, private=True)
    try:
        s3_key = _parse_input(event)
        upload_uuid = _upload_identity(s3_key, user_id)
        del upload_uuid
        result = analyze_upload(
            get_dynamodb_resource(),
            get_s3_client(),
            app_state_table_name=os.environ["APP_STATE_TABLE"],
            whiskey_table_name=os.environ["WHISKEY_SEARCH_TABLE"],
            bucket_name=os.environ["IMAGES_BUCKET"],
            user_id=user_id,
            s3_key=s3_key,
            model_id=model_id,
            context=context,
            started=started,
            logger=logger,
        )
        return create_response(200, result, event=event, private=True)
    except ValidationError as exc:
        return create_response(
            400,
            {"error": "Validation failed", "fields": exc.fields},
            event=event,
            private=True,
        )
    except OwnershipError:
        return create_response(403, {"error": "Upload does not belong to caller"}, event=event, private=True)
    except BudgetExceeded as exc:
        return create_response(exc.status_code, {"error": str(exc)}, event=event, private=True)
    except ImageNormalizationError:
        return create_response(400, {"error": "Uploaded image is invalid"}, event=event, private=True)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        if code in {"404", "NoSuchKey", "NotFound", "PreconditionFailed", "412"}:
            return create_response(400, {"error": "Uploaded image is missing or changed"}, event=event, private=True)
        logger.error("AWS operation failed", error_code=code, request_id=request_id)
    except Exception as exc:
        logger.error("Unhandled analysis error", error_type=type(exc).__name__, request_id=request_id)
    return create_response(
        500,
        {"error": "Internal server error", "request_id": request_id},
        event=event,
        private=True,
    )
