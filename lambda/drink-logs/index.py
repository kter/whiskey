"""Authenticated drink-log image upload and CRUD API."""

from __future__ import annotations

import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Mapping

try:
    from whiskey_common.clients import get_dynamodb_resource, get_s3_client
    from whiskey_common.cost_guard import (
        BudgetTransactionConflict,
        UsageBudgetExceeded,
    )
    from whiskey_common.jwt_utils import extract_user_id_from_event
    from whiskey_common.logger import extract_correlation_id, get_logger
    from whiskey_common.requests import parse_json_body, request_id as shared_request_id
    from whiskey_common.responses import create_response
    from whiskey_common.scan_utils import decode_next_token
except ModuleNotFoundError as exc:
    if exc.name != "whiskey_common":
        raise
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common" / "python"))
    from whiskey_common.clients import get_dynamodb_resource, get_s3_client
    from whiskey_common.cost_guard import (
        BudgetTransactionConflict,
        UsageBudgetExceeded,
    )
    from whiskey_common.jwt_utils import extract_user_id_from_event
    from whiskey_common.logger import extract_correlation_id, get_logger
    from whiskey_common.requests import parse_json_body, request_id as shared_request_id
    from whiskey_common.responses import create_response
    from whiskey_common.scan_utils import decode_next_token

from drink_log_store import (
    ANALYSIS_ID_RE,
    CONTENT_TYPES,
    SERVING_STYLES,
    AnalysisConflict,
    DrinkLogStore,
    ValidationError,
)
import lifecycle as lifecycle_module
from lifecycle import (
    CreateConflict,
    DrinkLogLifecycle,
    derive_drink_log_id,
)

RateLimitExceeded = UsageBudgetExceeded
TransientConflict = BudgetTransactionConflict


UPDATE_FIELDS = {"brand_text", "store", "notes", "rating", "serving_style"}
CREATE_FIELDS = {"analysis_id", "candidate_index", "datetime"} | UPDATE_FIELDS
DEFAULT_PAGE_LIMIT = 20
MAX_PAGE_LIMIT = 50
RFC3339_WITH_OFFSET_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)


def _validate_create_datetime(value: Any) -> str | None:
    if not isinstance(value, str) or not RFC3339_WITH_OFFSET_RE.fullmatch(value):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.utcoffset() is None:
        return None
    normalized = parsed.astimezone(timezone.utc)
    if normalized < datetime(2000, 1, 1, tzinfo=timezone.utc):
        return None
    if normalized > lifecycle_module.utc_now() + timedelta(minutes=5):
        return None
    return lifecycle_module.rfc3339(normalized)


def _validate_rating(value: Any) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        return None
    try:
        rating = Decimal(str(value))
    except InvalidOperation:
        return None
    if not rating.is_finite() or rating < Decimal("1") or rating > Decimal("5"):
        return None
    return rating


def validate_upload_input(data: Mapping[str, Any]) -> str:
    if set(data) != {"content_type"}:
        errors = {field: "Field is not accepted" for field in sorted(set(data) - {"content_type"})}
        if "content_type" not in data:
            errors["content_type"] = "Field is required"
        raise ValidationError(errors)
    content_type = data.get("content_type")
    if not isinstance(content_type, str):
        raise ValidationError({"content_type": "Must be an image content type"})
    if content_type.lower() in {"image/heic", "image/heif"}:
        raise ValidationError({"content_type": "HEIC/HEIF images are not supported"})
    if content_type not in CONTENT_TYPES:
        raise ValidationError({"content_type": "Must be image/jpeg, image/png, or image/webp"})
    return content_type


def validate_create_input(data: Mapping[str, Any]) -> dict[str, Any]:
    errors: dict[str, str] = {}
    for field in sorted(set(data) - CREATE_FIELDS):
        errors[field] = "Field is not accepted"
    analysis_id = data.get("analysis_id")
    if "analysis_id" not in data:
        errors["analysis_id"] = "Field is required"
    elif not isinstance(analysis_id, str) or not ANALYSIS_ID_RE.fullmatch(analysis_id):
        errors["analysis_id"] = "Must be a valid analysis result token"
    candidate_index = data.get("candidate_index")
    if "candidate_index" in data and (
        isinstance(candidate_index, bool)
        or not isinstance(candidate_index, int)
        or candidate_index < 0
    ):
        errors["candidate_index"] = "Must be a non-negative integer"

    validated_datetime = None
    if "datetime" in data:
        validated_datetime = _validate_create_datetime(data["datetime"])
        if validated_datetime is None:
            errors["datetime"] = (
                "Must be RFC3339 with an offset or Z and between 2000-01-01 and 5 minutes from now"
            )

    mutable_input = {field: data[field] for field in UPDATE_FIELDS if field in data}
    validated_mutable: dict[str, Any] = {}
    if mutable_input:
        try:
            validated_mutable = validate_update_input(mutable_input)
        except ValidationError as exc:
            errors.update(exc.fields)
    if errors:
        raise ValidationError(errors)
    validated = {"analysis_id": analysis_id, **validated_mutable}
    if "candidate_index" in data:
        validated["candidate_index"] = candidate_index
    if validated_datetime is not None:
        validated["datetime"] = validated_datetime
    return validated


def _validate_place_id(value: Any, *, nullable: bool) -> str | None:
    if nullable and value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > 1000:
        raise ValueError
    if any(ord(character) < 0x20 or ord(character) > 0x7E for character in value):
        raise ValueError
    return value


def validate_update_input(data: Mapping[str, Any]) -> dict[str, Any]:
    errors: dict[str, str] = {}
    for field in sorted(set(data) - UPDATE_FIELDS):
        errors[field] = "Field is not accepted"
    if not data:
        errors["body"] = "At least one mutable field is required"
    validated: dict[str, Any] = {}

    if "brand_text" in data:
        value = data["brand_text"]
        if not isinstance(value, str) or len(value) > 200:
            errors["brand_text"] = "Must be a string of at most 200 characters"
        else:
            validated["brand_text"] = value
    if "notes" in data:
        value = data["notes"]
        if not isinstance(value, str) or len(value) > 2000:
            errors["notes"] = "Must be a string of at most 2000 characters"
        else:
            validated["notes"] = value
    if "rating" in data:
        rating = _validate_rating(data["rating"])
        if rating is None:
            errors["rating"] = "Must be a number from 1 to 5"
        else:
            validated["rating"] = rating
    if "serving_style" in data:
        value = data["serving_style"]
        if value not in SERVING_STYLES:
            errors["serving_style"] = f"Must be one of {', '.join(sorted(SERVING_STYLES))}"
        else:
            validated["serving_style"] = value
    if "store" in data:
        store = data["store"]
        if not isinstance(store, dict) or not store or set(store) - {"name", "place_id"}:
            errors["store"] = "Must contain only name and optional place_id"
        else:
            clean_store: dict[str, Any] = {}
            if "name" in store:
                name = store["name"]
                if not isinstance(name, str) or len(name) > 200:
                    errors["store.name"] = "Must be a string of at most 200 characters"
                else:
                    clean_store["name"] = name
            if "place_id" in store:
                try:
                    clean_store["place_id"] = _validate_place_id(store["place_id"], nullable=True)
                except ValueError:
                    errors["store.place_id"] = "Must be printable ASCII of at most 1000 characters"
            validated["store"] = clean_store

    if errors:
        raise ValidationError(errors)
    return validated


def parse_timeline_query(
    query: Mapping[str, Any],
) -> tuple[int, dict[str, Any] | None, dict[str, str]]:
    try:
        limit = int(query.get("limit", DEFAULT_PAGE_LIMIT))
    except (TypeError, ValueError) as exc:
        raise ValidationError({"limit": f"Must be an integer from 1 to {MAX_PAGE_LIMIT}"}) from exc
    if not 1 <= limit <= MAX_PAGE_LIMIT:
        raise ValidationError({"limit": f"Must be from 1 to {MAX_PAGE_LIMIT}"})
    try:
        start_key = decode_next_token(query.get("next_token"))
    except ValueError as exc:
        raise ValidationError({"next_token": "Invalid continuation token"}) from exc
    filters: dict[str, str] = {}
    errors: dict[str, str] = {}
    for name in ("brand", "store", "place_id"):
        value = query.get(name)
        if value is None:
            continue
        if not isinstance(value, str) or len(value) > 100:
            errors[name] = "Must be a string of at most 100 characters"
        elif value:
            filters[name] = value
    if errors:
        raise ValidationError(errors)
    return limit, start_key, filters


@dataclass(frozen=True)
class _RouteContext:
    event: dict[str, Any]
    query: Mapping[str, Any]
    store: DrinkLogStore
    user_id: str
    record_id: Any


class _ExpectedRouteError(Exception):
    def __init__(self, cause: Exception):
        super().__init__(str(cause))
        self.cause = cause


_RouteKey = tuple[str, str]
_RouteResult = tuple[int, Any]
_RouteHandler = Callable[[_RouteContext], _RouteResult]
_ErrorMapper = Callable[[Exception, _RouteKey], _RouteResult]

_VALIDATION_ERRORS = (ValidationError,)
_UPLOAD_ERRORS = (RateLimitExceeded, TransientConflict)
_CREATE_ERRORS = _VALIDATION_ERRORS + _UPLOAD_ERRORS + (
    AnalysisConflict,
    CreateConflict,
    KeyError,
)


def _invoke_route_step(
    action: Callable[[], Any], expected_errors: tuple[type[Exception], ...]
) -> Any:
    try:
        return action()
    except expected_errors as exc:
        raise _ExpectedRouteError(exc) from exc


def _handle_upload_url(context: _RouteContext) -> _RouteResult:
    content_type = _invoke_route_step(
        lambda: validate_upload_input(parse_json_body(context.event)),
        _VALIDATION_ERRORS,
    )
    result = _invoke_route_step(
        lambda: context.store.create_upload_url(context.user_id, content_type),
        _UPLOAD_ERRORS,
    )
    return 200, result


def _handle_create(context: _RouteContext) -> _RouteResult:
    record, created = _invoke_route_step(
        lambda: context.store.create_drink_log(
            context.user_id,
            validate_create_input(parse_json_body(context.event)),
        ),
        _CREATE_ERRORS,
    )
    return 201 if created else 200, record


def _handle_detail(context: _RouteContext) -> _RouteResult:
    record = context.store.get_owned(context.user_id, context.record_id)
    if not record:
        return 404, {"error": "Drink log not found"}
    return 200, record


def _handle_timeline(context: _RouteContext) -> _RouteResult:
    limit, start_key, filters = _invoke_route_step(
        lambda: parse_timeline_query(context.query),
        _VALIDATION_ERRORS,
    )
    records, next_token = context.store.get_timeline(
        context.user_id,
        limit,
        start_key,
        filters,
    )
    return 200, {
        "results": records,
        "count": len(records),
        "next_token": next_token,
    }


def _handle_update(context: _RouteContext) -> _RouteResult:
    data = _invoke_route_step(
        lambda: validate_update_input(parse_json_body(context.event)),
        _VALIDATION_ERRORS,
    )
    record = context.store.update(
        context.user_id,
        context.record_id,
        data,
    )
    if not record:
        return 404, {"error": "Drink log not found"}
    return 200, record


def _handle_delete(context: _RouteContext) -> _RouteResult:
    deleted = context.store.delete(context.user_id, context.record_id)
    if not deleted:
        return 404, {"error": "Drink log not found"}
    return 204, ""


_ROUTE_DISPATCH: dict[_RouteKey, _RouteHandler] = {
    ("POST", "upload-url"): _handle_upload_url,
    ("POST", "collection"): _handle_create,
    ("GET", "record"): _handle_detail,
    ("GET", "collection"): _handle_timeline,
    ("PUT", "record"): _handle_update,
    ("DELETE", "record"): _handle_delete,
}


def _route_key(method: str, path: str, record_id: Any) -> _RouteKey:
    if method == "POST" and path.endswith("/upload-url"):
        return method, "upload-url"
    return method, "record" if record_id else "collection"


def _validation_error(exc: Exception, _route: _RouteKey) -> _RouteResult:
    return 400, {"error": "Validation failed", "fields": exc.fields}


def _rate_limit_error(_exc: Exception, route: _RouteKey) -> _RouteResult:
    message = (
        "Daily upload limit exceeded"
        if route == ("POST", "upload-url")
        else "Daily create or storage limit exceeded"
    )
    return 429, {"error": message}


def _transient_conflict_error(_exc: Exception, _route: _RouteKey) -> _RouteResult:
    return 503, {"error": "書き込みが混み合っています。少し時間をおいて再試行してください。"}


def _conflict_error(exc: Exception, _route: _RouteKey) -> _RouteResult:
    return 409, {"error": str(exc)}


def _not_found_error(_exc: Exception, _route: _RouteKey) -> _RouteResult:
    return 404, {"error": "Drink log not found"}


_EXCEPTION_MAPPERS: tuple[tuple[type[Exception], _ErrorMapper], ...] = (
    (ValidationError, _validation_error),
    (RateLimitExceeded, _rate_limit_error),
    (TransientConflict, _transient_conflict_error),
    (AnalysisConflict, _conflict_error),
    (CreateConflict, _conflict_error),
    (KeyError, _not_found_error),
)


def _map_exception(exc: Exception, route: _RouteKey) -> _RouteResult:
    for exception_type, mapper in _EXCEPTION_MAPPERS:
        if isinstance(exc, exception_type):
            return mapper(exc, route)
    raise exc


def _dispatch(route: _RouteKey, context: _RouteContext) -> _RouteResult:
    handler = _ROUTE_DISPATCH.get(route)
    if not handler:
        return 405, {"error": "Method not allowed"}
    try:
        return handler(context)
    except _ExpectedRouteError as exc:
        return _map_exception(exc.cause, route)


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    start_time = time.monotonic()
    request_id = shared_request_id(event, context)
    logger = get_logger("drink-logs", correlation_id=extract_correlation_id(event) or request_id)
    method = event.get("httpMethod", "UNKNOWN")
    path = (event.get("path") or "").rstrip("/")
    query = event.get("queryStringParameters") or {}
    logger.log_api_request(method=method, path=path, query_params=query)

    user_id = extract_user_id_from_event(event)
    if not user_id:
        return create_response(401, {"error": "Authentication required"}, event=event, private=True)

    try:
        dynamodb = get_dynamodb_resource()
        s3 = get_s3_client()
        store = DrinkLogStore.from_environment(dynamodb, s3)
        record_id = (event.get("pathParameters") or {}).get("id")
        route = _route_key(method, path, record_id)
        status_code, body = _dispatch(
            route,
            _RouteContext(
                event=event,
                query=query,
                store=store,
                user_id=user_id,
                record_id=record_id,
            ),
        )
        return create_response(
            status_code,
            body,
            event=event,
            private=True,
        )
    except Exception as exc:
        logger.error("Unhandled drink-log error", error=str(exc), request_id=request_id)
        return create_response(
            500,
            {"error": "Internal server error", "request_id": request_id},
            event=event,
            private=True,
            start_time=start_time,
            logger=logger,
        )
