"""Authenticated Google Places lookup with strict cost and data-retention guards."""

from __future__ import annotations

import concurrent.futures
import json
import math
import os
import time
from pathlib import Path
from typing import Any, Mapping, Protocol
from urllib.parse import quote

import requests

try:
    from whiskey_common.clients import get_boto3_client, get_dynamodb_resource
    from whiskey_common.cost_guard import UsageBudget, UsageBudgetExceeded
    from whiskey_common.errors import ValidationError
    from whiskey_common.jwt_utils import extract_user_id_from_event
    from whiskey_common.logger import extract_correlation_id, get_logger
    from whiskey_common.mock_guard import local_fixture_enabled, validate_mock_guard
    from whiskey_common.requests import parse_json_body, request_id as shared_request_id
    from whiskey_common.responses import create_response
except ModuleNotFoundError as exc:
    if exc.name != "whiskey_common":
        raise
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common" / "python"))
    from whiskey_common.clients import get_boto3_client, get_dynamodb_resource
    from whiskey_common.cost_guard import UsageBudget, UsageBudgetExceeded
    from whiskey_common.errors import ValidationError
    from whiskey_common.jwt_utils import extract_user_id_from_event
    from whiskey_common.logger import extract_correlation_id, get_logger
    from whiskey_common.mock_guard import local_fixture_enabled, validate_mock_guard
    from whiskey_common.requests import parse_json_body, request_id as shared_request_id
    from whiskey_common.responses import create_response


PLACES_BASE_URL = "https://places.googleapis.com/v1"
NEARBY_FIELD_MASK = "places.id,places.displayName,places.formattedAddress,places.attributions"
DETAIL_FIELD_MASK = "displayName,attributions"
MAX_RESOLVE_ITEMS = 10
MAX_BATCH_ATTEMPTS = 3
HANDLER_DEADLINE_SECONDS = 8.5
DEADLINE_SAFETY_SECONDS = 0.5
# Keep in sync with tests/test_drink_log_contract.py.
PLACEHOLDER_NAME = "店舗情報を取得できません"
_PLACES_API_KEY: str | None = None


BudgetExceeded = UsageBudgetExceeded


class OwnershipError(Exception):
    """Raised when a requested log is absent, foreign, or bound to another place."""


class UpstreamError(Exception):
    """Raised for invalid or unsuccessful Places responses."""


class UpstreamTimeout(UpstreamError):
    """Raised when the Places deadline is exhausted."""


class PlaceDirectory(Protocol):
    """Directory interface used by the Places Lambda handler."""

    def prepare(self) -> None:
        """Prepare the directory before processing a request."""
        ...

    def search_nearby(
        self,
        lat: float,
        lng: float,
        *,
        deadline: float | None = None,
    ) -> list[dict[str, Any]]:
        """Return nearby places for a coordinate."""
        ...

    def place_detail(self, place_id: str, *, deadline: float) -> dict[str, Any] | None:
        """Return display details for a place, or None when it is absent."""
        ...


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


class GooglePlaceDirectory:
    """Google Places adapter with execution-environment API-key caching."""

    def __init__(self) -> None:
        self._api_key: str | None = None

    def prepare(self) -> None:
        """Load and cache the Google Places API key."""
        self._load_api_key()

    def _load_api_key(self) -> str:
        global _PLACES_API_KEY
        if self._api_key is not None:
            return self._api_key
        if _PLACES_API_KEY is not None:
            self._api_key = _PLACES_API_KEY
            return self._api_key
        secret_name = os.environ.get("PLACES_SECRET_NAME")
        if not secret_name:
            raise RuntimeError("PLACES_SECRET_NAME is required")
        response = get_boto3_client("secretsmanager").get_secret_value(
            SecretId=secret_name
        )
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
        self._api_key = _PLACES_API_KEY
        return self._api_key

    @staticmethod
    def _attributions(value: Any) -> list[Any]:
        if not isinstance(value, list):
            raise UpstreamError("Places attributions are invalid")
        return value

    @staticmethod
    def _display_name(value: Any) -> str:
        if (
            not isinstance(value, dict)
            or not isinstance(value.get("text"), str)
            or not value["text"]
        ):
            raise UpstreamError("Places displayName is invalid")
        return value["text"]

    @staticmethod
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
        self,
        lat: float,
        lng: float,
        *,
        deadline: float | None = None,
    ) -> list[dict[str, Any]]:
        """Search Google Places near a coordinate."""
        api_key = self._load_api_key()
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
        payload = self._json_response(response)
        places = payload.get("places", [])
        if not isinstance(places, list) or len(places) > 8:
            raise UpstreamError("Places nearby payload is invalid")
        results: list[dict[str, Any]] = []
        for place in places:
            if not isinstance(place, dict) or not _valid_identifier(
                place.get("id"), maximum=1000
            ):
                raise UpstreamError("Places nearby item is invalid")
            address = place.get("formattedAddress", "")
            if not isinstance(address, str):
                raise UpstreamError("Places formattedAddress is invalid")
            results.append(
                {
                    "place_id": place["id"],
                    "display_name": self._display_name(place.get("displayName")),
                    "formatted_address": address,
                    "attributions": self._attributions(place.get("attributions", [])),
                }
            )
        return results

    def place_detail(self, place_id: str, *, deadline: float) -> dict[str, Any] | None:
        """Fetch Google Places display details for one place."""
        api_key = self._load_api_key()
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
        payload = self._json_response(response)
        return {
            "display_name": self._display_name(payload.get("displayName")),
            "attributions": self._attributions(payload.get("attributions", [])),
        }


class LocalPlaceDirectory:
    """Deterministic local adapter for Places development flows."""

    def prepare(self) -> None:
        """Prepare the local fixture adapter without external work."""
        pass

    def search_nearby(
        self,
        lat: float,
        lng: float,
        *,
        deadline: float | None = None,
    ) -> list[dict[str, Any]]:
        """Return the local nearby-place fixture."""
        del lat, lng, deadline
        return [
            {
                "place_id": "mock-place-1",
                "display_name": "モックバー",
                "formatted_address": "東京都モック区1-1",
                "attributions": [],
            }
        ]

    def place_detail(self, place_id: str, *, deadline: float) -> dict[str, Any] | None:
        """Return the local place-detail fixture."""
        del deadline
        return {"display_name": f"モック店舗 {place_id}", "attributions": []}


def select_place_directory() -> PlaceDirectory:
    """Select a Places adapter from the current invocation environment."""
    validate_mock_guard()
    if local_fixture_enabled("MOCK_PLACES"):
        return LocalPlaceDirectory()
    return GooglePlaceDirectory()


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


def resolve_places(
    dynamodb: Any,
    *,
    drinklogs_table_name: str,
    app_state_table_name: str,
    user_id: str,
    items: list[dict[str, str]],
    directory: PlaceDirectory,
    deadline: float,
) -> list[dict[str, Any]]:
    log_ids = list(dict.fromkeys(item["log_id"] for item in items))
    records = _batch_get_logs(dynamodb, drinklogs_table_name, log_ids, deadline)
    _verify_ownership(records, items, user_id)
    place_ids = list(dict.fromkeys(item["place_id"] for item in items))
    UsageBudget(dynamodb, app_state_table_name).reserve_places(user_id, len(place_ids))

    details: dict[str, dict[str, Any] | None] = {}
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(place_ids)))
    futures = {
        executor.submit(directory.place_detail, place_id, deadline=deadline): place_id
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


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Own POST /places and POST /places/resolve exclusively."""
    started = time.monotonic()
    directory = select_place_directory()
    request_id = shared_request_id(event, context)
    logger = get_logger("drink-log-places", correlation_id=extract_correlation_id(event) or request_id)
    method = event.get("httpMethod", "UNKNOWN")
    path = (event.get("path") or "").rstrip("/")
    user_id = extract_user_id_from_event(event)
    if not user_id:
        return create_response(401, {"error": "Authentication required"}, event=event, private=True)
    # Prepare the Places directory only after the caller is authenticated, so
    # unauthenticated requests never trigger a Secrets Manager lookup.
    directory.prepare()
    try:
        request_body = parse_json_body(event)
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
                directory=directory,
                deadline=_deadline(context, started),
            )
            return create_response(200, {"results": results}, event=event, private=True)
        if path.endswith("/places"):
            lat, lng = validate_nearby_input(request_body)
            UsageBudget(dynamodb, app_state_table_name).reserve_places(user_id, 1)
            return create_response(
                200,
                directory.search_nearby(
                    lat,
                    lng,
                    deadline=_deadline(context, started),
                ),
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
