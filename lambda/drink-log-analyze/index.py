"""Authenticated, budget-bounded drink-log image analysis."""

from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
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


SERVING_STYLES = {"NEAT", "ROCKS", "WATER", "SODA", "COCKTAIL"}
SERVING_STYLE_ALIASES = {"HIGHBALL": "SODA", "SODA": "SODA"}
UUID_TEXT = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}"
UPLOAD_KEY_RE = re.compile(rf"^tmp/([^/]+)/({UUID_TEXT})\.(jpg|jpeg|png|webp)$")
MAX_CANDIDATES = 5
MASTER_SNAPSHOT_TTL_SECONDS = 300
MASTER_SNAPSHOT_MAX_PAGES = 20
MASTER_SNAPSHOT_MAX_ITEMS = 5000
FUZZY_SHORTLIST_SIZE = 10
ANALYSIS_TTL_SECONDS = 30 * 60
HANDLER_BUDGET_MS = 20_000
INVOKE_SAFETY_MS = 4_000
MIN_INVOKE_BUDGET_MS = 2_000
PROMPT = (
    "Analyze this drink photo. Return only strict JSON with exactly these keys: "
    '{"brand_candidates":[{"name_ja":"","name_en":"","confidence":0.0}],'
    '"serving_style":"NEAT|ROCKS|WATER|SODA|COCKTAIL","glass_type":"","label_text":""}. '
    "Return at most 5 candidates. Confidence must be between 0 and 1. "
    "Set label_text to the text printed on the label exactly as shown. Do not transliterate, "
    "translate, or infer it; use an empty string if it is unreadable. "
    "Use SODA for highballs. Do not include markdown or commentary."
)

_MASTER_CACHE_LOCK = threading.Lock()
_MASTER_CACHE: dict[str, Any] | None = None


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
        client.transact_write_items(TransactItems=writes)
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
        "brand_candidates",
        "serving_style",
        "glass_type",
        "label_text",
    }:
        return None
    raw_candidates = payload.get("brand_candidates")
    if not isinstance(raw_candidates, list) or len(raw_candidates) > MAX_CANDIDATES:
        return None
    candidates: list[dict[str, Any]] = []
    for candidate in raw_candidates:
        if not isinstance(candidate, dict) or set(candidate) != {"name_ja", "name_en", "confidence"}:
            return None
        name_ja = candidate.get("name_ja")
        name_en = candidate.get("name_en")
        confidence = _decimal_confidence(candidate.get("confidence"))
        if (
            not isinstance(name_ja, str)
            or not isinstance(name_en, str)
            or len(name_ja) > 200
            or len(name_en) > 200
            or not (name_ja or name_en)
            or confidence is None
        ):
            return None
        candidates.append(
            {"name_ja": name_ja, "name_en": name_en, "confidence": confidence}
        )
    serving_raw = payload.get("serving_style")
    if not isinstance(serving_raw, str):
        return None
    serving_style = SERVING_STYLE_ALIASES.get(serving_raw.upper(), serving_raw.upper())
    if serving_style not in SERVING_STYLES:
        return None
    glass_type = payload.get("glass_type")
    if not isinstance(glass_type, str) or len(glass_type) > 200:
        return None
    label_text = payload.get("label_text")
    if not isinstance(label_text, str):
        return None
    return {
        "brand_candidates": candidates,
        "serving_style": serving_style,
        "glass_type": glass_type,
        "label_text": label_text[:200],
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
            "brand_candidates": [
                {"name_ja": "モックウイスキー", "name_en": "Mock Whisky", "confidence": Decimal("0.9")}
            ],
            "serving_style": "NEAT",
            "glass_type": "tumbler",
            "label_text": "",
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


def _candidate_names(candidate: Mapping[str, Any]) -> list[str]:
    return [
        value
        for value in (candidate.get("name_ja"), candidate.get("name_en"))
        if isinstance(value, str) and value
    ]


def _whiskey_id(item: Mapping[str, Any]) -> str | None:
    value = item.get("id")
    return value if isinstance(value, str) and value else None


_YEAR_NOISE_RE = re.compile(
    r"aged\d+(?:years?old|years?|yearold|yo)|\d+(?:years?old|years?|yearold|yo|年)"
)
_MEASURE_NOISE_RE = re.compile(r"\d+(?:\.\d+)?(?:ml|cl|l|%|度)")
_GENERAL_NOISE = (
    "しんぐるもると",
    "ぶれんでっど",
    "ういすきー",
    "うぃすきー",
    "singlemalt",
    "blended",
    "whiskey",
    "whisky",
    "scotch",
    "blend",
    "純米",
    "原酒",
    "新酒",
    "古酒",
    "蒸溜所",
    "蒸留所",
)
_CORE_SEPARATOR_RE = re.compile(r"[^0-9a-z\u3040-\u309f\u30fc\u3400-\u9fff]+")
_CJK_RE = re.compile(r"[\u3040-\u309f\u30fc\u3400-\u9fff]")
# Japanese labels separate words with \u3001and \u30fb rather than spaces. Without these
# the separator strip glues neighbours together ("\u30b5\u30f3\u30c8\u30ea\u30fc\u3001\u5c71\u5d0e" -> "\u3055\u3093\u3068\u308a\u30fc\u5c71\u5d0e")
# and manufactures substrings that were never printed side by side.
_LABEL_TOKEN_RE = re.compile(r"[\s\u3001\u3002\uff0c\uff0e\u30fb\uff0f/|\\]+")


def _brand_core(value: str) -> str:
    """Return a normalized brand-only comparison string.

    A value made up entirely of generic words collapses to an empty string
    rather than falling back to the original text. Keeping the fallback let a
    master row named only "ブレンデッドウイスキー" match a bare "ウイスキー"
    token on the label, which is printed on practically every bottle.
    """
    normalized = normalize_text(value)
    if not normalized:
        return ""
    core = _YEAR_NOISE_RE.sub("", normalized)
    core = _MEASURE_NOISE_RE.sub("", core)
    for noise in _GENERAL_NOISE:
        core = core.replace(noise, "")
    return _CORE_SEPARATOR_RE.sub("", core)


def _usable_match_core(value: str, *, allow_cjk_pair: bool = True) -> bool:
    """Reject comparison fragments too short to identify a brand.

    Latin fragments need three characters, but Japanese brand names are
    routinely two characters (山崎, 白州, 余市) and carry as much signal as a
    longer romanized spelling, so direct candidate comparisons may allow a CJK
    pair. Label-text callers disable that relaxation.
    """
    if len(value) >= 3:
        return True
    return (
        allow_cjk_pair
        and len(value) == 2
        and all(_CJK_RE.fullmatch(character) for character in value)
    )


def _snapshot_record(item: Mapping[str, Any]) -> dict[str, Any]:
    record = dict(item)
    names = [
        value
        for value in (item.get("name_ja"), item.get("name_en"), item.get("name"))
        if isinstance(value, str) and value
    ]
    normalized_names = tuple(
        dict.fromkeys(normalized for name in names if (normalized := normalize_text(name)))
    )
    brand_cores = tuple(
        dict.fromkeys(core for name in names if (core := _brand_core(name)))
    )
    record["_normalized_names"] = normalized_names
    record["_brand_cores"] = brand_cores
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


def _unique_records(records: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    unique: dict[str, Mapping[str, Any]] = {}
    for record in records:
        record_id = _whiskey_id(record)
        if record_id:
            unique[record_id] = record
    return list(unique.values())


def _match_whiskey(
    snapshot: Mapping[str, Any],
    candidate: Mapping[str, Any],
    label_text: str = "",
) -> dict[str, Any]:
    if not snapshot.get("complete"):
        return {"source": "ai", "item": None, "ambiguous_items": []}

    normalized_names = tuple(
        dict.fromkeys(
            normalized
            for name in _candidate_names(candidate)
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
    if len(exact_matches) == 1:
        return {
            "source": "master:exact",
            "item": exact_matches[0],
            "ambiguous_items": [],
        }
    if len(exact_matches) > 1:
        return {
            "source": "ambiguous",
            "item": None,
            "ambiguous_items": exact_matches,
        }

    candidate_cores = tuple(
        dict.fromkeys(
            core
            for name in _candidate_names(candidate)
            if (core := _brand_core(name))
        )
    )
    label_cores = tuple(
        dict.fromkeys(
            core
            for token in _LABEL_TOKEN_RE.split(label_text)
            if token and (core := _brand_core(token))
        )
    )

    def is_substring_match(
        item: Mapping[str, Any], cores: tuple[str, ...], *, allow_cjk_pair: bool
    ) -> bool:
        master_cores = item.get("_brand_cores", ())
        return any(
            _usable_match_core(core, allow_cjk_pair=allow_cjk_pair)
            and _usable_match_core(master_core, allow_cjk_pair=allow_cjk_pair)
            and (core in master_core or master_core in core)
            for core in cores
            for master_core in master_cores
        )

    # The candidate names and the label text are separate evidence classes and
    # must not be pooled. Label tokens are noisy — "SINGLE" and "MALT" off a
    # Caol Ila bottle also hit 竹鶴ピュアモルト and フォアローゼズ — so pooling
    # them let weak evidence dilute an otherwise unique name match into
    # "ambiguous". The label is only consulted when the names match nothing.
    substring_matches = _unique_records(
        [
            item
            for item in snapshot.get("items", ())
            if is_substring_match(item, candidate_cores, allow_cjk_pair=True)
        ]
    )
    if not substring_matches:
        substring_matches = _unique_records(
            [
                item
                for item in snapshot.get("items", ())
                if is_substring_match(item, label_cores, allow_cjk_pair=False)
            ]
        )
    if len(substring_matches) == 1:
        return {
            "source": "master:substring",
            "item": substring_matches[0],
            "ambiguous_items": [],
        }
    if len(substring_matches) > 1:
        return {
            "source": "ambiguous",
            "item": None,
            "ambiguous_items": substring_matches,
        }
    return {"source": "ai", "item": None, "ambiguous_items": []}


def _resolved_candidate(
    candidate: Mapping[str, Any],
    match: Mapping[str, Any],
) -> dict[str, Any]:
    name_ja = candidate["name_ja"]
    name_en = candidate["name_en"]
    matched = match.get("item")
    if isinstance(matched, Mapping):
        canonical_names = [
            value
            for value in (
                matched.get("name_ja"),
                matched.get("name"),
                matched.get("name_en"),
            )
            if isinstance(value, str) and value and len(value) <= 200
        ]
        master_name_ja = matched.get("name_ja")
        if not isinstance(master_name_ja, str):
            master_name_ja = ""
        elif len(master_name_ja) > 200:
            master_name_ja = name_ja
        master_name_en = matched.get("name_en")
        if not isinstance(master_name_en, str):
            master_name_en = ""
        elif len(master_name_en) > 200:
            master_name_en = name_en
        return {
            "brand_text": next(iter(canonical_names), name_ja or name_en),
            "name_ja": master_name_ja,
            "name_en": master_name_en,
            "confidence": candidate["confidence"],
            "whiskey_id": _whiskey_id(matched),
            "match_source": match["source"],
            "ai_name_ja": name_ja,
            "ai_name_en": name_en,
        }
    return {
        "brand_text": name_ja or name_en,
        "name_ja": name_ja,
        "name_en": name_en,
        "confidence": candidate["confidence"],
        "match_source": match["source"],
        "ai_name_ja": name_ja,
        "ai_name_en": name_en,
    }


def _resolve_candidates(
    snapshot: Mapping[str, Any],
    analysis: Mapping[str, Any],
    label_text: str,
) -> tuple[list[dict[str, Any]], list[Mapping[str, Any]], list[Mapping[str, Any]]]:
    results: list[dict[str, Any]] = []
    unresolved: list[Mapping[str, Any]] = []
    ambiguous_items: list[Mapping[str, Any]] = []
    for candidate in analysis.get("brand_candidates", []):
        match = _match_whiskey(snapshot, candidate, label_text)
        results.append(_resolved_candidate(candidate, match))
        if match["source"] in {"ambiguous", "ai"}:
            unresolved.append(candidate)
            ambiguous_items.extend(match["ambiguous_items"])
    return results, unresolved, _unique_records(ambiguous_items)


def _build_candidates(
    snapshot: Mapping[str, Any],
    analysis: Mapping[str, Any],
    label_text: str = "",
) -> list[dict[str, Any]]:
    return _resolve_candidates(snapshot, analysis, label_text)[0]


def _build_fuzzy_shortlist(
    snapshot: Mapping[str, Any],
    candidates: list[Mapping[str, Any]],
    label_text: str,
    ambiguous_items: list[Mapping[str, Any]] | None = None,
    max_comparison_cores: int = 10,
) -> list[dict[str, Any]]:
    """Build Phase 3 input; these scores are never used to auto-confirm a match."""
    if not snapshot.get("complete") or not candidates:
        return []
    if max_comparison_cores <= 0:
        return []
    candidate_cores = list(
        dict.fromkeys(
            core
            for candidate in candidates
            for name in _candidate_names(candidate)
            if (core := _brand_core(name))
        )
    )[:max_comparison_cores]
    label_cores = list(
        dict.fromkeys(
            core
            for token in _LABEL_TOKEN_RE.split(label_text)
            if token and (core := _brand_core(token))
        )
    )[:max_comparison_cores]
    comparison_cores = candidate_cores + label_cores
    if not comparison_cores:
        return []

    scored: list[tuple[float, str, Mapping[str, Any]]] = []
    for item in snapshot.get("items", ()):
        item_id = _whiskey_id(item)
        master_cores = item.get("_brand_cores", ())
        if not item_id or not master_cores:
            continue
        score = max(
            SequenceMatcher(None, query_core, master_core).ratio()
            for query_core in comparison_cores
            for master_core in master_cores
        )
        scored.append((score, item_id, item))
    scored.sort(key=lambda entry: (-entry[0], entry[1]))

    forced_ids = {
        item_id
        for item in (ambiguous_items or [])
        if (item_id := _whiskey_id(item))
    }
    selected = [entry for entry in scored if entry[1] in forced_ids]
    selected.extend(
        entry
        for entry in scored
        if entry[1] not in forced_ids
    )
    forced_entry_count = sum(entry[1] in forced_ids for entry in scored)
    selected = selected[: max(FUZZY_SHORTLIST_SIZE, forced_entry_count)]
    return [
        {
            "id": item_id,
            "name_ja": item.get("name_ja", ""),
            "name_en": item.get("name_en", ""),
            "score": score,
        }
        for score, item_id, item in selected
    ]


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
        )
        analysis = _invoke_model(model_id, normalized, context, started)
        if analysis is None or analysis:
            break
    if not analysis:
        analysis = {
            "brand_candidates": [],
            "serving_style": "NEAT",
            "glass_type": "",
            "label_text": "",
        }

    snapshot = _get_master_snapshot(
        dynamodb.Table(whiskey_table_name),
        whiskey_table_name,
        logger,
    )
    label_text = analysis["label_text"]
    candidates, unresolved, ambiguous_items = _resolve_candidates(
        snapshot,
        analysis,
        label_text,
    )
    if _remaining_budget_ms(context, started) < MIN_INVOKE_BUDGET_MS:
        shortlist = []
    else:
        shortlist = _build_fuzzy_shortlist(
            snapshot,
            unresolved,
            label_text,
            ambiguous_items,
        )
    if logger is not None:
        logger.info(
            "Brand candidates resolved",
            candidate_count=len(candidates),
            matched_count=sum("whiskey_id" in candidate for candidate in candidates),
            match_sources=[candidate["match_source"] for candidate in candidates],
            top_match_source=candidates[0]["match_source"] if candidates else None,
            model_id=model_id,
            label_text_length=len(label_text),
            master_snapshot_complete=snapshot["complete"],
            master_snapshot_size=len(snapshot["items"]),
            shortlist_size=len(shortlist),
            ambiguous_count=sum(
                candidate["match_source"] == "ambiguous"
                for candidate in candidates
            ),
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
