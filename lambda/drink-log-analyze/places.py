"""Authenticated Google Places lookup with strict cost and data-retention guards."""

from __future__ import annotations

import concurrent.futures
import json
import math
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import quote

import requests

try:
    from whiskey_common.clients import get_boto3_client, get_dynamodb_resource
    from whiskey_common.jwt_utils import extract_user_id_from_event
    from whiskey_common.logger import extract_correlation_id, get_logger
    from whiskey_common.responses import create_response
    from whiskey_common.transactions import transact_write_with_retry
except ModuleNotFoundError as exc:
    if exc.name != "whiskey_common":
        raise
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common" / "python"))
    from whiskey_common.clients import get_boto3_client, get_dynamodb_resource
    from whiskey_common.jwt_utils import extract_user_id_from_event
    from whiskey_common.logger import extract_correlation_id, get_logger
    from whiskey_common.responses import create_response
    from whiskey_common.transactions import transact_write_with_retry


PLACES_BASE_URL = "https://places.googleapis.com/v1"
NEARBY_FIELD_MASK = "places.id,places.displayName,places.formattedAddress,places.attributions"
DETAIL_FIELD_MASK = "displayName,attributions"
MAX_RESOLVE_ITEMS = 10
MAX_BATCH_ATTEMPTS = 3
HANDLER_DEADLINE_SECONDS = 8.5
DEADLINE_SAFETY_SECONDS = 0.5
PLACEHOLDER_NAME = "店舗情報を取得できません"
_PLACES_API_KEY: str | None = None


class ValidationError(ValueError):
    """Raised for caller-controlled invalid input."""

    def __init__(self, fields: Mapping[str, str]):
        super().__init__("Validation failed")
        self.fields = dict(fields)


class BudgetExceeded(Exception):
    """Raised when a Places request would exceed a cost ceiling."""


class OwnershipError(Exception):
    """Raised when a requested log is absent, foreign, or bound to another place."""


class UpstreamError(Exception):
    """Raised for invalid or unsuccessful Places responses."""


class UpstreamTimeout(UpstreamError):
    """Raised when the Places deadline is exhausted."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _rfc3339(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _env_flag_is_set(name: str) -> bool:
    return name in os.environ and os.environ[name] != ""


def _validate_mock_guard() -> None:
    if os.environ.get("ENVIRONMENT", "dev") != "local" and any(
        _env_flag_is_set(name) for name in ("MOCK_AI", "MOCK_PLACES")
    ):
        raise RuntimeError("MOCK_AI and MOCK_PLACES are permitted only in local")


def _mock_places_enabled() -> bool:
    return os.environ.get("ENVIRONMENT") == "local" and _env_flag_is_set("MOCK_PLACES")


def _load_api_key() -> str:
    global _PLACES_API_KEY
    if _PLACES_API_KEY is not None:
        return _PLACES_API_KEY
    secret_name = os.environ.get("PLACES_SECRET_NAME")
    if not secret_name:
        raise RuntimeError("PLACES_SECRET_NAME is required")
    response = get_boto3_client("secretsmanager").get_secret_value(SecretId=secret_name)
    secret_string = response.get("SecretString")
    if not isinstance(secret_string, str):
        raise RuntimeError("Places secret must contain SecretString JSON")
    try:
        secret = json.loads(secret_string)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Places secret is not valid JSON") from exc
    if (
        not isinstance(secret, dict)
        or set(secret) != {"apiKey"}
        or not isinstance(secret.get("apiKey"), str)
        or not secret["apiKey"].strip()
    ):
        raise RuntimeError("Places secret must have exactly one non-empty apiKey")
    _PLACES_API_KEY = secret["apiKey"]
    return _PLACES_API_KEY


def _api_key() -> str:
    if _mock_places_enabled():
        return "local-mock-not-sent"
    return _load_api_key()


def _parse_json_body(event: Mapping[str, Any]) -> dict[str, Any]:
    raw = event.get("body")
    if not isinstance(raw, str):
        raise ValidationError({"body": "A JSON object is required"})
    try:
        body = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValidationError({"body": "Malformed JSON"}) from exc
    if not isinstance(body, dict):
        raise ValidationError({"body": "A JSON object is required"})
    return body


def _finite_coordinate(value: Any, minimum: float, maximum: float) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or number < minimum or number > maximum:
        return None
    return number


def validate_nearby_input(body: Mapping[str, Any]) -> tuple[float, float]:
    errors: dict[str, str] = {}
    for name in sorted(set(body) - {"lat", "lng"}):
        errors[name] = "Field is not accepted"
    lat = _finite_coordinate(body.get("lat"), -90, 90)
    lng = _finite_coordinate(body.get("lng"), -180, 180)
    if lat is None:
        errors["lat"] = "Must be a finite number from -90 to 90"
    if lng is None:
        errors["lng"] = "Must be a finite number from -180 to 180"
    if errors:
        raise ValidationError(errors)
    return lat, lng


def _valid_identifier(value: Any, *, maximum: int) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= maximum
        and all(0x20 <= ord(character) <= 0x7E for character in value)
    )


def validate_resolve_input(body: Mapping[str, Any]) -> list[dict[str, str]]:
    if set(body) != {"items"}:
        errors = {name: "Field is not accepted" for name in sorted(set(body) - {"items"})}
        if "items" not in body:
            errors["items"] = "Field is required"
        raise ValidationError(errors)
    items = body.get("items")
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_RESOLVE_ITEMS:
        raise ValidationError({"items": "Must contain from 1 to 10 items"})
    validated: list[dict[str, str]] = []
    errors: dict[str, str] = {}
    for index, item in enumerate(items):
        if not isinstance(item, dict) or set(item) != {"log_id", "place_id"}:
            errors[f"items[{index}]"] = "Must contain exactly log_id and place_id"
            continue
        if not _valid_identifier(item.get("log_id"), maximum=200):
            errors[f"items[{index}].log_id"] = "Must be a printable non-empty identifier"
        if not _valid_identifier(item.get("place_id"), maximum=1000):
            errors[f"items[{index}].place_id"] = "Must be a printable non-empty identifier"
        if not any(key.startswith(f"items[{index}]") for key in errors):
            validated.append({"log_id": item["log_id"], "place_id": item["place_id"]})
    if errors:
        raise ValidationError(errors)
    return validated


def _counter_update(
    table_name: str,
    key: str,
    *,
    amount: int,
    limit: int,
    ttl: int,
    now: str,
) -> dict[str, Any]:
    return {
        "Update": {
            "TableName": table_name,
            "Key": {"pk": key},
            "UpdateExpression": (
                "SET #ttl = if_not_exists(#ttl, :ttl), updated_at = :now ADD #count :amount"
            ),
            "ConditionExpression": (
                "attribute_not_exists(#count) OR #count <= :largest_existing"
            ),
            "ExpressionAttributeNames": {"#count": "count", "#ttl": "ttl"},
            "ExpressionAttributeValues": {
                ":amount": amount,
                ":largest_existing": limit - amount,
                ":ttl": ttl,
                ":now": now,
            },
        }
    }


def reserve_places_budget(
    dynamodb: Any,
    table_name: str,
    user_id: str,
    amount: int,
    *,
    now_dt: datetime | None = None,
) -> None:
    if amount < 1:
        raise ValueError("amount must be positive")
    current = now_dt or _utc_now()
    limits = (
        int(os.environ.get("PLACES_USER_DAILY_LIMIT", "30")),
        int(os.environ.get("PLACES_GLOBAL_DAILY_LIMIT", "15")),
        int(os.environ.get("PLACES_GLOBAL_MONTHLY_LIMIT", "150")),
    )
    if any(amount > limit for limit in limits):
        raise BudgetExceeded
    date = current.strftime("%Y-%m-%d")
    month = current.strftime("%Y-%m")
    now = _rfc3339(current)
    daily_ttl = int((current + timedelta(days=2)).timestamp())
    monthly_ttl = int((current + timedelta(days=35)).timestamp())
    writes = [
        _counter_update(
            table_name,
            f"drinklog-counter#places#user#{user_id}#{date}",
            amount=amount,
            limit=limits[0],
            ttl=daily_ttl,
            now=now,
        ),
        _counter_update(
            table_name,
            f"drinklog-counter#places#global#{date}",
            amount=amount,
            limit=limits[1],
            ttl=daily_ttl,
            now=now,
        ),
        _counter_update(
            table_name,
            f"drinklog-counter#places#global-month#{month}",
            amount=amount,
            limit=limits[2],
            ttl=monthly_ttl,
            now=now,
        ),
    ]
    client = dynamodb.meta.client
    try:
        transact_write_with_retry(client, writes)
    except client.exceptions.TransactionCanceledException as exc:
        reasons = exc.response.get("CancellationReasons", [])
        if any(reason.get("Code") == "ConditionalCheckFailed" for reason in reasons):
            raise BudgetExceeded from exc
        raise


def _attributions(value: Any) -> list[Any]:
    if not isinstance(value, list):
        raise UpstreamError("Places attributions are invalid")
    return value


def _display_name(value: Any) -> str:
    if not isinstance(value, dict) or not isinstance(value.get("text"), str) or not value["text"]:
        raise UpstreamError("Places displayName is invalid")
    return value["text"]


def _json_response(response: Any) -> Mapping[str, Any]:
    try:
        response.raise_for_status()
        payload = response.json()
    except requests.Timeout as exc:
        raise UpstreamTimeout from exc
    except (requests.RequestException, ValueError) as exc:
        raise UpstreamError("Places returned an invalid response") from exc
    if not isinstance(payload, dict):
        raise UpstreamError("Places returned a non-object response")
    return payload


def search_nearby(
    lat: float,
    lng: float,
    api_key: str,
    *,
    deadline: float | None = None,
) -> list[dict[str, Any]]:
    if _mock_places_enabled():
        return [
            {
                "place_id": "mock-place-1",
                "display_name": "モックバー",
                "formatted_address": "東京都モック区1-1",
                "attributions": [],
            }
        ]
    body = {
        "includedTypes": ["bar", "restaurant"],
        "rankPreference": "DISTANCE",
        "maxResultCount": 8,
        "languageCode": "ja",
        "regionCode": "JP",
        "locationRestriction": {
            "circle": {
                "center": {"latitude": lat, "longitude": lng},
                "radius": 300,
            }
        },
    }
    headers = {
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": NEARBY_FIELD_MASK,
        "Content-Type": "application/json",
    }
    remaining = (deadline - time.monotonic()) if deadline is not None else 5.0
    if remaining <= 0:
        raise UpstreamTimeout
    try:
        response = requests.post(
            f"{PLACES_BASE_URL}/places:searchNearby",
            json=body,
            headers=headers,
            timeout=(min(2, remaining), min(5, remaining)),
        )
    except requests.Timeout as exc:
        raise UpstreamTimeout from exc
    except requests.RequestException as exc:
        raise UpstreamError("Places nearby request failed") from exc
    payload = _json_response(response)
    places = payload.get("places", [])
    if not isinstance(places, list) or len(places) > 8:
        raise UpstreamError("Places nearby payload is invalid")
    results: list[dict[str, Any]] = []
    for place in places:
        if not isinstance(place, dict) or not _valid_identifier(place.get("id"), maximum=1000):
            raise UpstreamError("Places nearby item is invalid")
        address = place.get("formattedAddress", "")
        if not isinstance(address, str):
            raise UpstreamError("Places formattedAddress is invalid")
        results.append(
            {
                "place_id": place["id"],
                "display_name": _display_name(place.get("displayName")),
                "formatted_address": address,
                "attributions": _attributions(place.get("attributions", [])),
            }
        )
    return results


def _deadline(context: Any, started: float) -> float:
    deadline = started + HANDLER_DEADLINE_SECONDS
    get_remaining = getattr(context, "get_remaining_time_in_millis", None)
    if callable(get_remaining):
        deadline = min(
            deadline,
            time.monotonic() + max(0, get_remaining() / 1000 - DEADLINE_SAFETY_SECONDS),
        )
    return deadline


def _batch_get_logs(
    dynamodb: Any,
    table_name: str,
    log_ids: list[str],
    deadline: float,
) -> dict[str, dict[str, Any]]:
    request_items: dict[str, Any] = {
        table_name: {
            "Keys": [{"id": log_id} for log_id in log_ids],
            "ConsistentRead": True,
        }
    }
    found: dict[str, dict[str, Any]] = {}
    for _ in range(MAX_BATCH_ATTEMPTS):
        if time.monotonic() >= deadline:
            raise UpstreamTimeout("BatchGet deadline exhausted")
        response = dynamodb.batch_get_item(RequestItems=request_items)
        for item in response.get("Responses", {}).get(table_name, []):
            if isinstance(item, dict) and isinstance(item.get("id"), str):
                found[item["id"]] = item
        unprocessed = response.get("UnprocessedKeys", {})
        if not unprocessed:
            return found
        request_items = unprocessed
    raise UpstreamError("DrinkLogs BatchGet remained unprocessed")


def _verify_ownership(records: Mapping[str, Mapping[str, Any]], items: list[dict[str, str]], user_id: str) -> None:
    for item in items:
        record = records.get(item["log_id"])
        store = record.get("store") if isinstance(record, Mapping) else None
        if (
            not record
            or record.get("user_id") != user_id
            or not isinstance(store, Mapping)
            or store.get("place_id") != item["place_id"]
        ):
            raise OwnershipError


def _placeholder(log_id: str) -> dict[str, Any]:
    return {
        "log_id": log_id,
        "display_name": PLACEHOLDER_NAME,
        "name_source": "google",
        "attributions": [],
    }


def _place_detail(place_id: str, api_key: str, deadline: float) -> dict[str, Any] | None:
    if _mock_places_enabled():
        return {"display_name": f"モック店舗 {place_id}", "attributions": []}
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise UpstreamTimeout
    url = f"{PLACES_BASE_URL}/places/{quote(place_id, safe='')}"
    headers = {"X-Goog-Api-Key": api_key, "X-Goog-FieldMask": DETAIL_FIELD_MASK}
    try:
        response = requests.get(
            url,
            params={"languageCode": "ja", "regionCode": "JP"},
            headers=headers,
            timeout=(min(2, remaining), min(5, remaining)),
        )
    except requests.Timeout as exc:
        raise UpstreamTimeout from exc
    except requests.RequestException as exc:
        raise UpstreamError("Place Details request failed") from exc
    if response.status_code == 404:
        return None
    payload = _json_response(response)
    return {
        "display_name": _display_name(payload.get("displayName")),
        "attributions": _attributions(payload.get("attributions", [])),
    }


def resolve_places(
    dynamodb: Any,
    *,
    drinklogs_table_name: str,
    app_state_table_name: str,
    user_id: str,
    items: list[dict[str, str]],
    api_key: str,
    deadline: float,
) -> list[dict[str, Any]]:
    log_ids = list(dict.fromkeys(item["log_id"] for item in items))
    records = _batch_get_logs(dynamodb, drinklogs_table_name, log_ids, deadline)
    _verify_ownership(records, items, user_id)
    place_ids = list(dict.fromkeys(item["place_id"] for item in items))
    reserve_places_budget(dynamodb, app_state_table_name, user_id, len(place_ids))

    details: dict[str, dict[str, Any] | None] = {}
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(place_ids)))
    futures = {
        executor.submit(_place_detail, place_id, api_key, deadline): place_id
        for place_id in place_ids
    }
    try:
        wait_seconds = max(0, deadline - time.monotonic())
        done, pending = concurrent.futures.wait(futures, timeout=wait_seconds)
        for future in done:
            place_id = futures[future]
            try:
                details[place_id] = future.result()
            except Exception:
                details[place_id] = None
        for future in pending:
            future.cancel()
            details[futures[future]] = None
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    results: list[dict[str, Any]] = []
    for item in items:
        detail = details.get(item["place_id"])
        if not detail:
            results.append(_placeholder(item["log_id"]))
        else:
            results.append(
                {
                    "log_id": item["log_id"],
                    "display_name": detail["display_name"],
                    "name_source": "google",
                    "attributions": detail["attributions"],
                }
            )
    return results


def _request_id(event: Mapping[str, Any], context: Any) -> str:
    return (
        getattr(context, "aws_request_id", None)
        or (event.get("requestContext") or {}).get("requestId")
        or "unknown"
    )


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Own POST /places and POST /places/resolve exclusively."""
    started = time.monotonic()
    _validate_mock_guard()
    request_id = _request_id(event, context)
    logger = get_logger("drink-log-places", correlation_id=extract_correlation_id(event) or request_id)
    method = event.get("httpMethod", "UNKNOWN")
    path = (event.get("path") or "").rstrip("/")
    user_id = extract_user_id_from_event(event)
    if not user_id:
        return create_response(401, {"error": "Authentication required"}, event=event, private=True)
    # Fetch the Places secret only after the caller is authenticated, so
    # unauthenticated requests never trigger a Secrets Manager lookup.
    api_key = _api_key()
    try:
        request_body = _parse_json_body(event)
    except ValidationError as exc:
        return create_response(
            400,
            {"error": "Validation failed", "fields": exc.fields},
            event=event,
            private=True,
        )
    logger.log_api_request(method=method, path=path, body=request_body)
    if method != "POST":
        return create_response(405, {"error": "Method not allowed"}, event=event, private=True)

    try:
        dynamodb = get_dynamodb_resource()
        app_state_table_name = os.environ["APP_STATE_TABLE"]
        if path.endswith("/places/resolve"):
            items = validate_resolve_input(request_body)
            results = resolve_places(
                dynamodb,
                drinklogs_table_name=os.environ["DRINKLOGS_TABLE"],
                app_state_table_name=app_state_table_name,
                user_id=user_id,
                items=items,
                api_key=api_key,
                deadline=_deadline(context, started),
            )
            return create_response(200, {"results": results}, event=event, private=True)
        if path.endswith("/places"):
            lat, lng = validate_nearby_input(request_body)
            reserve_places_budget(dynamodb, app_state_table_name, user_id, 1)
            return create_response(
                200,
                search_nearby(lat, lng, api_key, deadline=_deadline(context, started)),
                event=event,
                private=True,
            )
        return create_response(404, {"error": "Not found"}, event=event, private=True)
    except ValidationError as exc:
        return create_response(
            400,
            {"error": "Validation failed", "fields": exc.fields},
            event=event,
            private=True,
        )
    except OwnershipError:
        return create_response(403, {"error": "Place binding does not belong to caller"}, event=event, private=True)
    except BudgetExceeded:
        return create_response(429, {"error": "Places request limit exceeded"}, event=event, private=True)
    except UpstreamTimeout:
        return create_response(504, {"error": "Places request timed out"}, event=event, private=True)
    except UpstreamError:
        return create_response(502, {"error": "Places returned an invalid response"}, event=event, private=True)
    except Exception as exc:
        logger.error("Unhandled Places error", error_type=type(exc).__name__, request_id=request_id)
        return create_response(
            500,
            {"error": "Internal server error", "request_id": request_id},
            event=event,
            private=True,
        )
