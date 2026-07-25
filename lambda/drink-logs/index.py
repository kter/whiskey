"""Authenticated drink-log image upload and CRUD API."""

from __future__ import annotations

import json
import os
import re
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping

from botocore.exceptions import ClientError

try:
    from whiskey_common.clients import get_dynamodb_resource, get_s3_client
    from whiskey_common.images import (
        ImageNormalizationError,
        normalize_image,
        sniff_format,
    )
    from whiskey_common.jwt_utils import extract_user_id_from_event
    from whiskey_common.logger import extract_correlation_id, get_logger
    from whiskey_common.responses import create_response
    from whiskey_common.scan_utils import decode_next_token, encode_next_token
except ModuleNotFoundError as exc:
    if exc.name != "whiskey_common":
        raise
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common" / "python"))
    from whiskey_common.clients import get_dynamodb_resource, get_s3_client
    from whiskey_common.images import (
        ImageNormalizationError,
        normalize_image,
        sniff_format,
    )
    from whiskey_common.jwt_utils import extract_user_id_from_event
    from whiskey_common.logger import extract_correlation_id, get_logger
    from whiskey_common.responses import create_response
    from whiskey_common.scan_utils import decode_next_token, encode_next_token


SERVING_STYLES = {"NEAT", "ROCKS", "WATER", "SODA", "COCKTAIL"}
CONTENT_TYPES = {
    "image/jpeg": ("jpeg", "jpg"),
    "image/png": ("png", "png"),
    "image/webp": ("webp", "webp"),
}
UPDATE_FIELDS = {"brand_text", "store", "notes", "rating", "serving_style"}
CREATE_FIELDS = {"analysis_id", "candidate_index"} | UPDATE_FIELDS
# Strip internal bookkeeping and raw bucket-key structure from API responses.
# Clients receive a presigned `image_url` instead of the raw S3 keys; the quota
# and delete-lifecycle fields are server-side reconciliation state only.
INTERNAL_FIELDS = {
    "_completion",
    "content_type",
    "tmp_etag",
    "s3_image_key",
    "tmp_s3_key",
    "quota_allocated",
    "delete_started_at",
}
DEFAULT_PAGE_LIMIT = 20
MAX_PAGE_LIMIT = 50
MAX_TIMELINE_PAGE_QUERIES = 10
PRESIGNED_POST_SECONDS = 120
PRESIGNED_GET_SECONDS = 900
NAMESPACE_DRINKLOG = uuid.UUID("7df1920f-5929-51ee-9860-164c1d4bc388")
UUID_TEXT = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}"
ANALYSIS_ID_RE = re.compile(rf"^(?:ai-result:([^:]+):)?({UUID_TEXT})$")


class ValidationError(ValueError):
    def __init__(self, fields: Mapping[str, str]):
        super().__init__("Validation failed")
        self.fields = dict(fields)


class RateLimitExceeded(Exception):
    pass


class AnalysisConflict(Exception):
    pass


class CreateConflict(Exception):
    pass


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _rfc3339(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _request_id(event: Mapping[str, Any], context: Any) -> str:
    return (
        getattr(context, "aws_request_id", None)
        or (event.get("requestContext") or {}).get("requestId")
        or "unknown"
    )


def _parse_json_body(event: Mapping[str, Any]) -> dict[str, Any]:
    raw_body = event.get("body")
    if not isinstance(raw_body, str):
        raise ValidationError({"body": "A JSON object is required"})
    try:
        body = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise ValidationError({"body": "Malformed JSON"}) from exc
    if not isinstance(body, dict):
        raise ValidationError({"body": "A JSON object is required"})
    return body


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


def derive_drink_log_id(user_id: str, upload_uuid: str) -> str:
    """Derive a stable ID bound to both the owner and upload UUID."""
    parsed = str(uuid.UUID(upload_uuid))
    return str(uuid.uuid5(NAMESPACE_DRINKLOG, f"{user_id}\0{parsed}"))


def _analysis_identity(user_id: str, analysis_id: str) -> tuple[str, str]:
    match = ANALYSIS_ID_RE.fullmatch(analysis_id)
    if not match:
        raise ValidationError({"analysis_id": "Must be a valid analysis result token"})
    token_user, upload_uuid = match.groups()
    if token_user is not None and token_user != user_id:
        raise AnalysisConflict("Analysis result does not belong to caller")
    upload_uuid = str(uuid.UUID(upload_uuid))
    return f"ai-result:{user_id}:{upload_uuid}", upload_uuid


def _extract_upload_uuid(s3_key: str, user_id: str) -> str:
    pattern = re.compile(
        rf"^tmp/{re.escape(user_id)}/({UUID_TEXT})\.(?:jpg|jpeg|png|webp)$"
    )
    match = pattern.fullmatch(s3_key)
    if not match:
        raise AnalysisConflict("Analysis result has an invalid upload key")
    return str(uuid.UUID(match.group(1)))


def _rate_counter_update(table_name: str, key: str, limit: int, ttl: int, now: str) -> dict[str, Any]:
    return {
        "Update": {
            "TableName": table_name,
            "Key": {"pk": key},
            "UpdateExpression": (
                "SET #ttl = if_not_exists(#ttl, :ttl), updated_at = :updated_at "
                "ADD #count :one"
            ),
            "ConditionExpression": "attribute_not_exists(#count) OR #count < :limit",
            "ExpressionAttributeNames": {"#count": "count", "#ttl": "ttl"},
            "ExpressionAttributeValues": {
                ":one": 1,
                ":limit": limit,
                ":ttl": ttl,
                ":updated_at": now,
            },
        }
    }


def _quota_counter_update(table_name: str, key: str, limit: int, now: str) -> dict[str, Any]:
    return {
        "Update": {
            "TableName": table_name,
            "Key": {"pk": key},
            "UpdateExpression": "SET updated_at = :updated_at ADD #count :one",
            "ConditionExpression": "attribute_not_exists(#count) OR #count < :limit",
            "ExpressionAttributeNames": {"#count": "count"},
            "ExpressionAttributeValues": {":one": 1, ":limit": limit, ":updated_at": now},
        }
    }


def _quota_counter_decrement(table_name: str, key: str, now: str) -> dict[str, Any]:
    return {
        "Update": {
            "TableName": table_name,
            "Key": {"pk": key},
            "UpdateExpression": "SET updated_at = :updated_at ADD #count :minus_one",
            "ConditionExpression": "#count >= :one",
            "ExpressionAttributeNames": {"#count": "count"},
            "ExpressionAttributeValues": {":minus_one": -1, ":one": 1, ":updated_at": now},
        }
    }


def create_upload_url(
    dynamodb: Any,
    s3: Any,
    app_state_table_name: str,
    bucket_name: str,
    user_id: str,
    content_type: str,
) -> dict[str, Any]:
    now_dt = _utc_now()
    now = _rfc3339(now_dt)
    utc_date = now_dt.strftime("%Y-%m-%d")
    ttl = int((now_dt + timedelta(days=2)).timestamp())
    client = dynamodb.meta.client
    try:
        client.transact_write_items(
            TransactItems=[
                _rate_counter_update(
                    app_state_table_name,
                    f"drinklog-counter#upload#user#{user_id}#{utc_date}",
                    int(os.environ.get("UPLOAD_USER_DAILY_LIMIT", "30")),
                    ttl,
                    now,
                ),
                _rate_counter_update(
                    app_state_table_name,
                    f"drinklog-counter#upload#global#{utc_date}",
                    int(os.environ.get("UPLOAD_GLOBAL_DAILY_LIMIT", "100")),
                    ttl,
                    now,
                ),
            ]
        )
    except client.exceptions.TransactionCanceledException as exc:
        raise RateLimitExceeded from exc

    _format, extension = CONTENT_TYPES[content_type]
    key = f"tmp/{user_id}/{uuid.uuid4()}.{extension}"
    max_bytes = int(os.environ.get("UPLOAD_MAX_BYTES", "3670016"))
    # A captured form is pinned to one exact key. Reuse can only overwrite that
    # object and cannot consume storage allocation or an expensive API. The
    # residual risk is low-cost PUT requests during the 120-second validity
    # window; request metrics and alarms monitor that unbounded request charge.
    post = s3.generate_presigned_post(
        Bucket=bucket_name,
        Key=key,
        Fields={"Content-Type": content_type},
        Conditions=[
            {"Content-Type": content_type},
            ["content-length-range", 0, max_bytes],
        ],
        ExpiresIn=PRESIGNED_POST_SECONDS,
    )
    return {"upload_url": post["url"], "fields": post["fields"], "s3_key": key}


def _get_record(table: Any, record_id: str) -> dict[str, Any] | None:
    return table.get_item(Key={"id": record_id}, ConsistentRead=True).get("Item")


def _candidate_brand(candidate: Any) -> str:
    if isinstance(candidate, str):
        brand = candidate
    elif isinstance(candidate, Mapping):
        brand = next(
            (
                candidate.get(key)
                for key in ("brand_text", "name", "label")
                if isinstance(candidate.get(key), str)
            ),
            "",
        )
    else:
        brand = ""
    if not brand or len(brand) > 200:
        raise AnalysisConflict("Selected analysis candidate is invalid")
    return brand


def _completion_from_analysis(
    result: Mapping[str, Any],
    candidate: Any,
    overrides: Mapping[str, Any],
    *,
    candidate_selected: bool,
) -> dict[str, Any]:
    brand_text = _candidate_brand(candidate) if candidate_selected else ""
    whiskey_id = None
    if isinstance(candidate, Mapping):
        whiskey_id = candidate.get("whiskey_id") or candidate.get("matched_whiskey_id")
    if candidate_selected:
        whiskey_id = whiskey_id or result.get("whiskey_id") or result.get("matched_whiskey_id")
    if whiskey_id is not None and (not isinstance(whiskey_id, str) or not whiskey_id):
        raise AnalysisConflict("Matched whiskey ID is invalid")
    serving_style = result.get("serving_style", "NEAT")
    if serving_style not in SERVING_STYLES:
        raise AnalysisConflict("Analysis serving style is invalid")

    completion: dict[str, Any] = {
        "brand_text": brand_text,
        "brand_source": "manual" if not candidate_selected else ("matched" if whiskey_id else "ai"),
        "serving_style": serving_style,
        "store": {"name": ""},
    }
    if whiskey_id:
        completion["whiskey_id"] = whiskey_id
    model_id = result.get("model_id")
    confidence = result.get("confidence")
    if isinstance(candidate, Mapping) and candidate.get("confidence") is not None:
        confidence = candidate.get("confidence")
    if confidence is not None or (candidate_selected and model_id is not None):
        if not isinstance(model_id, str) or not model_id:
            raise AnalysisConflict("Analysis model ID is invalid")
        try:
            confidence_decimal = Decimal(str(confidence))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise AnalysisConflict("Analysis confidence is invalid") from exc
        if not confidence_decimal.is_finite() or not Decimal("0") <= confidence_decimal <= Decimal("1"):
            raise AnalysisConflict("Analysis confidence is invalid")
        completion["ai"] = {"model_id": model_id, "confidence": confidence_decimal}

    if "brand_text" in overrides:
        completion["brand_text"] = overrides["brand_text"]
        completion["brand_source"] = "manual"
        completion.pop("whiskey_id", None)
    if "serving_style" in overrides:
        completion["serving_style"] = overrides["serving_style"]
    if "store" in overrides:
        store = {"name": ""}
        if "name" in overrides["store"]:
            store["name"] = overrides["store"]["name"]
        place_id = overrides["store"].get("place_id")
        if place_id is not None:
            store["place_id"] = place_id
        completion["store"] = store
    for field in ("rating", "notes"):
        if field in overrides:
            completion[field] = overrides[field]
    return completion


def _prepare_initial_record(
    dynamodb: Any,
    s3: Any,
    app_state_table_name: str,
    bucket_name: str,
    user_id: str,
    analysis_pk: str,
    upload_uuid: str,
    candidate_index: int | None,
    overrides: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    result = dynamodb.Table(app_state_table_name).get_item(
        Key={"pk": analysis_pk},
        ConsistentRead=True,
    ).get("Item")
    now_epoch = int(_utc_now().timestamp())
    if not result or result.get("user") != user_id:
        raise AnalysisConflict("Analysis result is missing or already consumed")
    try:
        expires_at = int(result["expires_at"])
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise AnalysisConflict("Analysis result expiry is invalid") from exc
    if expires_at <= now_epoch:
        raise AnalysisConflict("Analysis result has expired; analyze the image again")
    s3_key = result.get("s3_key")
    if not isinstance(s3_key, str) or _extract_upload_uuid(s3_key, user_id) != upload_uuid:
        raise AnalysisConflict("Analysis result upload binding is invalid")
    etag_name = "ETag" if "ETag" in result else "etag"
    etag = result.get(etag_name)
    if not isinstance(etag, str) or not etag:
        raise AnalysisConflict("Analysis result ETag is invalid")
    candidate = None
    if candidate_index is not None:
        candidates = result.get("candidates")
        if not isinstance(candidates, list) or candidate_index >= len(candidates):
            raise AnalysisConflict("Selected analysis candidate is unavailable")
        candidate = candidates[candidate_index]
    completion = _completion_from_analysis(
        result,
        candidate,
        overrides or {},
        candidate_selected=candidate_index is not None,
    )

    try:
        head = s3.head_object(Bucket=bucket_name, Key=s3_key)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
            raise AnalysisConflict("Uploaded image is missing; upload and analyze it again") from exc
        raise
    if head.get("ETag") != etag:
        raise AnalysisConflict("Uploaded image changed after analysis")
    content_type = head.get("ContentType")
    if content_type not in CONTENT_TYPES:
        raise AnalysisConflict("Uploaded image content type is unsupported")
    if int(head.get("ContentLength", 0)) > int(os.environ.get("UPLOAD_MAX_BYTES", "3670016")):
        raise AnalysisConflict("Uploaded image exceeds the upload limit")

    now = _rfc3339(_utc_now())
    pending = {
        "id": derive_drink_log_id(user_id, upload_uuid),
        "user_id": user_id,
        "status": "pending",
        "datetime": now,
        "tmp_s3_key": s3_key,
        "tmp_etag": etag,
        "content_type": content_type,
        "quota_allocated": True,
        "_completion": completion,
        "created_at": now,
        "updated_at": now,
    }
    condition = "#user = :user AND s3_key = :s3_key AND #etag = :etag"
    names = {"#user": "user", "#etag": etag_name}
    values = {
        ":user": user_id,
        ":s3_key": s3_key,
        ":etag": etag,
        ":now_epoch": now_epoch,
    }
    if candidate_index is not None:
        condition += f" AND #candidates[{candidate_index}] = :candidate"
        names["#candidates"] = "candidates"
        values[":candidate"] = candidate
    condition += " AND expires_at > :now_epoch"
    consume = {
        "Delete": {
            "TableName": app_state_table_name,
            "Key": {"pk": analysis_pk},
            "ConditionExpression": condition,
            "ExpressionAttributeNames": names,
            "ExpressionAttributeValues": values,
        }
    }
    return pending, consume


def _initial_create_transaction(
    dynamodb: Any,
    drinklogs_table_name: str,
    app_state_table_name: str,
    pending: Mapping[str, Any],
    consume_analysis: Mapping[str, Any],
) -> None:
    now_dt = _utc_now()
    now = _rfc3339(now_dt)
    utc_date = now_dt.strftime("%Y-%m-%d")
    ttl = int((now_dt + timedelta(days=2)).timestamp())
    user_id = pending["user_id"]
    transaction = [
        {
            "Put": {
                "TableName": drinklogs_table_name,
                "Item": dict(pending),
                "ConditionExpression": "attribute_not_exists(id)",
            }
        },
        _rate_counter_update(
            app_state_table_name,
            f"drinklog-counter#create#user#{user_id}#{utc_date}",
            int(os.environ.get("CREATE_USER_DAILY_LIMIT", "30")),
            ttl,
            now,
        ),
        _rate_counter_update(
            app_state_table_name,
            f"drinklog-counter#create#global#{utc_date}",
            int(os.environ.get("CREATE_GLOBAL_DAILY_LIMIT", "100")),
            ttl,
            now,
        ),
        _quota_counter_update(
            app_state_table_name,
            f"drinklog-quota#user#{user_id}",
            int(os.environ.get("STORAGE_USER_LIMIT", "2000")),
            now,
        ),
        _quota_counter_update(
            app_state_table_name,
            "drinklog-quota#global",
            int(os.environ.get("STORAGE_GLOBAL_LIMIT", "20000")),
            now,
        ),
        dict(consume_analysis),
    ]
    dynamodb.meta.client.transact_write_items(TransactItems=transaction)


def _compensate_pending(
    dynamodb: Any,
    drinklogs_table_name: str,
    app_state_table_name: str,
    record: Mapping[str, Any],
) -> bool:
    now = _rfc3339(_utc_now())
    client = dynamodb.meta.client
    try:
        client.transact_write_items(
            TransactItems=[
                {
                    "Delete": {
                        "TableName": drinklogs_table_name,
                        "Key": {"id": record["id"]},
                        "ConditionExpression": (
                            "#owner = :caller AND #status = :pending AND quota_allocated = :true"
                        ),
                        "ExpressionAttributeNames": {"#owner": "user_id", "#status": "status"},
                        "ExpressionAttributeValues": {
                            ":caller": record["user_id"],
                            ":pending": "pending",
                            ":true": True,
                        },
                    }
                },
                _quota_counter_decrement(
                    app_state_table_name,
                    f"drinklog-quota#user#{record['user_id']}",
                    now,
                ),
                _quota_counter_decrement(
                    app_state_table_name,
                    "drinklog-quota#global",
                    now,
                ),
            ]
        )
        return True
    except client.exceptions.TransactionCanceledException:
        return False


def _read_s3_body(s3: Any, *, bucket_name: str, key: str, etag: str) -> bytes:
    response = s3.get_object(Bucket=bucket_name, Key=key, IfMatch=etag)
    body = response["Body"]
    try:
        return body.read()
    finally:
        body.close()


def _is_missing_s3_error(exc: ClientError) -> bool:
    return exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}


def _object_absent(s3: Any, bucket_name: str, key: str) -> bool:
    try:
        s3.head_object(Bucket=bucket_name, Key=key)
    except ClientError as exc:
        if _is_missing_s3_error(exc):
            return True
        raise
    return False


def _remove_tmp_reference(
    table: Any,
    record_id: str,
    user_id: str,
    tmp_key: str,
) -> dict[str, Any] | None:
    try:
        response = table.update_item(
            Key={"id": record_id},
            UpdateExpression="REMOVE tmp_s3_key",
            ConditionExpression="#owner = :caller AND #status = :complete AND tmp_s3_key = :tmp",
            ExpressionAttributeNames={"#owner": "user_id", "#status": "status"},
            ExpressionAttributeValues={
                ":caller": user_id,
                ":complete": "complete",
                ":tmp": tmp_key,
            },
            ReturnValues="ALL_NEW",
        )
        return response.get("Attributes")
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        return None


def _complete_pending_record(
    table: Any,
    record: Mapping[str, Any],
    final_key: str,
) -> dict[str, Any] | None:
    completion = record.get("_completion")
    if not isinstance(completion, Mapping):
        raise CreateConflict("Pending record is missing completion metadata")
    names = {
        "#owner": "user_id",
        "#status": "status",
        "#brand_text": "brand_text",
        "#brand_source": "brand_source",
        "#serving_style": "serving_style",
        "#store": "store",
        "#updated_at": "updated_at",
        "#completion": "_completion",
        "#content_type": "content_type",
        "#tmp_etag": "tmp_etag",
    }
    values: dict[str, Any] = {
        ":caller": record["user_id"],
        ":pending": "pending",
        ":complete": "complete",
        ":final_key": final_key,
        ":brand_text": completion["brand_text"],
        ":brand_source": completion["brand_source"],
        ":serving_style": completion["serving_style"],
        ":store": completion["store"],
        ":updated_at": _rfc3339(_utc_now()),
    }
    sets = [
        "#status = :complete",
        "s3_image_key = :final_key",
        "#brand_text = :brand_text",
        "#brand_source = :brand_source",
        "#serving_style = :serving_style",
        "#store = :store",
        "#updated_at = :updated_at",
    ]
    for field in ("whiskey_id", "ai", "rating", "notes"):
        if field in completion:
            names[f"#{field}"] = field
            values[f":{field}"] = completion[field]
            sets.append(f"#{field} = :{field}")
    try:
        response = table.update_item(
            Key={"id": record["id"]},
            UpdateExpression=(
                f"SET {', '.join(sets)} "
                "REMOVE #completion, #content_type, #tmp_etag"
            ),
            ConditionExpression="#owner = :caller AND #status = :pending",
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
            ReturnValues="ALL_NEW",
        )
        return response.get("Attributes")
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        return None


def _finish_pending_create(
    dynamodb: Any,
    s3: Any,
    drinklogs_table_name: str,
    app_state_table_name: str,
    bucket_name: str,
    record: Mapping[str, Any],
) -> dict[str, Any]:
    table = dynamodb.Table(drinklogs_table_name)
    tmp_key = record.get("tmp_s3_key")
    etag = record.get("tmp_etag")
    content_type = record.get("content_type")
    if not isinstance(tmp_key, str) or not isinstance(etag, str) or content_type not in CONTENT_TYPES:
        raise CreateConflict("Pending record is incomplete")

    try:
        raw = _read_s3_body(s3, bucket_name=bucket_name, key=tmp_key, etag=etag)
        actual_format = sniff_format(raw[:16])
        expected_format = CONTENT_TYPES[content_type][0]
        if actual_format != expected_format:
            raise ImageNormalizationError("Image bytes do not match the declared content type")
        normalized = normalize_image(
            raw,
            max_bytes=int(os.environ.get("IMAGE_MAX_BYTES", "1572864")),
        )
    except ImageNormalizationError as exc:
        compensated = _compensate_pending(
            dynamodb,
            drinklogs_table_name,
            app_state_table_name,
            record,
        )
        winner = _get_record(table, record["id"])
        if not compensated and winner and winner.get("status") == "complete":
            return winner
        if not compensated and winner:
            raise RuntimeError("Terminal image failure was not compensated") from exc
        if compensated:
            try:
                s3.delete_object(Bucket=bucket_name, Key=tmp_key)
            except ClientError:
                # The record no longer references this object. The explicit
                # tmp/ reconciliation pass will retry this recoverable cleanup.
                pass
        raise ValidationError({"image": str(exc)}) from exc
    except ClientError as exc:
        if _is_missing_s3_error(exc) or exc.response.get("Error", {}).get("Code") in {
            "PreconditionFailed",
            "412",
        }:
            compensated = _compensate_pending(
                dynamodb,
                drinklogs_table_name,
                app_state_table_name,
                record,
            )
            winner = _get_record(table, record["id"])
            if not compensated and winner and winner.get("status") == "complete":
                return winner
            if not compensated and winner:
                raise RuntimeError("Changed image failure was not compensated") from exc
            if compensated:
                try:
                    s3.delete_object(Bucket=bucket_name, Key=tmp_key)
                except ClientError:
                    # The tmp/ reconciler owns retry after record compensation.
                    pass
            raise ValidationError({"image": "Uploaded image is missing or changed"}) from exc
        raise

    upload_uuid = _extract_upload_uuid(tmp_key, record["user_id"])
    attempt = uuid.uuid4().hex
    final_key = f"logs/{record['user_id']}/{upload_uuid}-{attempt}.jpg"
    s3.put_object(
        Bucket=bucket_name,
        Key=final_key,
        Body=normalized,
        ContentType="image/jpeg",
        CacheControl="private, no-store",
    )
    completed = _complete_pending_record(table, record, final_key)
    if completed is None:
        winner = _get_record(table, record["id"])
        if not winner or winner.get("user_id") != record["user_id"]:
            raise CreateConflict("Drink log disappeared during creation")
        if winner.get("status") != "complete":
            raise CreateConflict("Drink log is no longer creatable")
        completed = winner

    s3.delete_object(Bucket=bucket_name, Key=tmp_key)
    if not _object_absent(s3, bucket_name, tmp_key):
        raise RuntimeError("Temporary image deletion was not confirmed")
    cleaned = _remove_tmp_reference(table, record["id"], record["user_id"], tmp_key)
    return cleaned or _get_record(table, record["id"]) or completed


def create_drink_log(
    dynamodb: Any,
    s3: Any,
    drinklogs_table_name: str,
    app_state_table_name: str,
    bucket_name: str,
    user_id: str,
    data: Mapping[str, Any],
) -> tuple[dict[str, Any], bool]:
    analysis_pk, upload_uuid = _analysis_identity(user_id, data["analysis_id"])
    record_id = derive_drink_log_id(user_id, upload_uuid)
    table = dynamodb.Table(drinklogs_table_name)

    existing = _get_record(table, record_id)
    if existing:
        if existing.get("user_id") != user_id:
            raise KeyError(record_id)
        if existing.get("status") == "complete":
            return existing, False
        if existing.get("status") == "pending":
            return _finish_pending_create(
                dynamodb,
                s3,
                drinklogs_table_name,
                app_state_table_name,
                bucket_name,
                existing,
            ), False
        raise CreateConflict("Drink log is being deleted")

    pending, consume = _prepare_initial_record(
        dynamodb,
        s3,
        app_state_table_name,
        bucket_name,
        user_id,
        analysis_pk,
        upload_uuid,
        data.get("candidate_index"),
        data,
    )
    client = dynamodb.meta.client
    try:
        _initial_create_transaction(
            dynamodb,
            drinklogs_table_name,
            app_state_table_name,
            pending,
            consume,
        )
        created = True
        current = pending
    except client.exceptions.TransactionCanceledException as exc:
        current = _get_record(table, record_id)
        if current:
            if current.get("user_id") != user_id:
                raise KeyError(record_id) from exc
            if current.get("status") == "complete":
                return current, False
            if current.get("status") == "pending":
                return _finish_pending_create(
                    dynamodb,
                    s3,
                    drinklogs_table_name,
                    app_state_table_name,
                    bucket_name,
                    current,
                ), False
        reasons = exc.response.get("CancellationReasons", [])
        if not reasons or any(
            index < len(reasons) and reasons[index].get("Code") == "ConditionalCheckFailed"
            for index in (1, 2, 3, 4)
        ):
            raise RateLimitExceeded from exc
        if len(reasons) > 5 and reasons[5].get("Code") == "ConditionalCheckFailed":
            raise AnalysisConflict("Analysis result is stale or already consumed") from exc
        if reasons[0].get("Code") == "ConditionalCheckFailed":
            raise CreateConflict("Concurrent creation did not expose a winner") from exc
        raise

    return _finish_pending_create(
        dynamodb,
        s3,
        drinklogs_table_name,
        app_state_table_name,
        bucket_name,
        current,
    ), created


def _safe_image_key(item: Mapping[str, Any], user_id: str) -> str | None:
    key = item.get("s3_image_key")
    if item.get("status") != "complete" or not isinstance(key, str):
        return None
    return key if key.startswith(f"logs/{user_id}/") else None


def _public_record(item: Mapping[str, Any], s3: Any, bucket_name: str, user_id: str) -> dict[str, Any]:
    result = {key: value for key, value in item.items() if key not in INTERNAL_FIELDS}
    image_key = _safe_image_key(item, user_id)
    if image_key:
        result["image_url"] = s3.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": bucket_name,
                "Key": image_key,
                "ResponseCacheControl": "private, no-store",
            },
            ExpiresIn=PRESIGNED_GET_SECONDS,
        )
    return result


def get_timeline(
    dynamodb: Any,
    s3: Any,
    drinklogs_table_name: str,
    bucket_name: str,
    user_id: str,
    limit: int,
    start_key: dict[str, Any] | None,
    filters: Mapping[str, str],
) -> tuple[list[dict[str, Any]], str | None]:
    table = dynamodb.Table(drinklogs_table_name)
    items: list[dict[str, Any]] = []
    cursor = start_key
    next_token: str | None = None
    max_pages = max(1, int(os.environ.get("TIMELINE_MAX_PAGES", str(MAX_TIMELINE_PAGE_QUERIES))))
    for _ in range(max_pages):
        names = {"#status": "status"}
        values: dict[str, Any] = {":user_id": user_id, ":complete": "complete"}
        clauses = ["#status = :complete"]
        if "brand" in filters:
            names["#brand"] = "brand_text"
            values[":brand"] = filters["brand"]
            clauses.append("contains(#brand, :brand)")
        if "store" in filters:
            names.update({"#store": "store", "#name": "name"})
            values[":store"] = filters["store"]
            clauses.append("contains(#store.#name, :store)")
        if "place_id" in filters:
            names.update({"#store": "store", "#place_id": "place_id"})
            values[":place_id"] = filters["place_id"]
            clauses.append("#store.#place_id = :place_id")
        kwargs: dict[str, Any] = {
            "IndexName": "UserDatetimeIndex",
            "KeyConditionExpression": "user_id = :user_id",
            "FilterExpression": " AND ".join(clauses),
            "ExpressionAttributeNames": names,
            "ExpressionAttributeValues": values,
            "ScanIndexForward": False,
            "Limit": max(1, limit - len(items)),
        }
        if cursor:
            kwargs["ExclusiveStartKey"] = cursor
        response = table.query(**kwargs)
        for item in response.get("Items", []):
            if item.get("status") == "complete" and item.get("user_id") == user_id:
                items.append(_public_record(item, s3, bucket_name, user_id))
                if len(items) == limit:
                    break
        cursor = response.get("LastEvaluatedKey")
        if not cursor:
            next_token = None
            break
        next_token = encode_next_token(cursor)
        if len(items) == limit:
            break
    return items, next_token


def get_owned_drink_log(
    table: Any,
    s3: Any,
    bucket_name: str,
    user_id: str,
    record_id: str,
) -> dict[str, Any] | None:
    item = _get_record(table, record_id)
    if not item or item.get("user_id") != user_id or item.get("status") != "complete":
        return None
    return _public_record(item, s3, bucket_name, user_id)


def update_drink_log(
    table: Any,
    user_id: str,
    record_id: str,
    data: Mapping[str, Any],
) -> dict[str, Any] | None:
    names = {"#owner": "user_id", "#status": "status", "#updated_at": "updated_at"}
    values: dict[str, Any] = {
        ":caller": user_id,
        ":complete": "complete",
        ":updated_at": _rfc3339(_utc_now()),
    }
    sets = ["#updated_at = :updated_at"]
    removes: list[str] = []
    for field in ("brand_text", "notes", "rating", "serving_style"):
        if field in data:
            names[f"#{field}"] = field
            values[f":{field}"] = data[field]
            sets.append(f"#{field} = :{field}")
    if "brand_text" in data:
        names["#brand_source"] = "brand_source"
        values[":manual"] = "manual"
        sets.append("#brand_source = :manual")
    if "store" in data:
        names.update({"#store": "store", "#name": "name", "#place_id": "place_id"})
        store = data["store"]
        if "name" in store:
            values[":store_name"] = store["name"]
            sets.append("#store.#name = :store_name")
        if "place_id" in store:
            if store["place_id"] is None:
                removes.append("#store.#place_id")
            else:
                values[":place_id"] = store["place_id"]
                sets.append("#store.#place_id = :place_id")
    expression = f"SET {', '.join(sets)}"
    if removes:
        expression += f" REMOVE {', '.join(removes)}"
    try:
        response = table.update_item(
            Key={"id": record_id},
            UpdateExpression=expression,
            ConditionExpression="#owner = :caller AND #status = :complete",
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
            ReturnValues="ALL_NEW",
        )
        return response.get("Attributes")
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        return None


def _finalize_delete(
    dynamodb: Any,
    drinklogs_table_name: str,
    app_state_table_name: str,
    item: Mapping[str, Any],
) -> bool:
    client = dynamodb.meta.client
    delete = {
        "Delete": {
            "TableName": drinklogs_table_name,
            "Key": {"id": item["id"]},
            "ConditionExpression": (
                "#owner = :caller AND #status = :deleting AND quota_allocated = :allocated"
            ),
            "ExpressionAttributeNames": {"#owner": "user_id", "#status": "status"},
            "ExpressionAttributeValues": {
                ":caller": item["user_id"],
                ":deleting": "deleting",
                ":allocated": bool(item.get("quota_allocated")),
            },
        }
    }
    transaction: list[dict[str, Any]] = [delete]
    if item.get("quota_allocated") is True:
        now = _rfc3339(_utc_now())
        transaction.extend(
            [
                _quota_counter_decrement(
                    app_state_table_name,
                    f"drinklog-quota#user#{item['user_id']}",
                    now,
                ),
                _quota_counter_decrement(app_state_table_name, "drinklog-quota#global", now),
            ]
        )
    try:
        client.transact_write_items(TransactItems=transaction)
        return True
    except client.exceptions.TransactionCanceledException:
        if _get_record(dynamodb.Table(drinklogs_table_name), item["id"]) is None:
            return True
        raise RuntimeError("Drink log deletion transaction did not converge")


def delete_drink_log(
    dynamodb: Any,
    s3: Any,
    drinklogs_table_name: str,
    app_state_table_name: str,
    bucket_name: str,
    user_id: str,
    record_id: str,
) -> bool:
    table = dynamodb.Table(drinklogs_table_name)
    try:
        response = table.update_item(
            Key={"id": record_id},
            UpdateExpression=(
                "SET #status = :deleting, "
                "delete_started_at = if_not_exists(delete_started_at, :started_at)"
            ),
            ConditionExpression=(
                "#owner = :caller AND (#status = :complete OR #status = :deleting)"
            ),
            ExpressionAttributeNames={"#owner": "user_id", "#status": "status"},
            ExpressionAttributeValues={
                ":caller": user_id,
                ":complete": "complete",
                ":deleting": "deleting",
                ":started_at": _rfc3339(_utc_now()),
            },
            ReturnValues="ALL_NEW",
        )
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        return False
    item = response.get("Attributes")
    if not item:
        raise RuntimeError("Deleting record was not returned")
    key = item.get("s3_image_key")
    if isinstance(key, str) and key.startswith(f"logs/{user_id}/"):
        s3.delete_object(Bucket=bucket_name, Key=key)
        if not _object_absent(s3, bucket_name, key):
            raise RuntimeError("Drink log image deletion was not confirmed")
    elif key:
        raise RuntimeError("Refusing to delete an image outside the owner prefix")
    return _finalize_delete(dynamodb, drinklogs_table_name, app_state_table_name, item)


def _validation_response(exc: ValidationError, event: Mapping[str, Any]) -> dict[str, Any]:
    return create_response(
        400,
        {"error": "Validation failed", "fields": exc.fields},
        event=event,
        private=True,
    )


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    start_time = time.monotonic()
    request_id = _request_id(event, context)
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
        drinklogs_table_name = os.environ["DRINKLOGS_TABLE"]
        app_state_table_name = os.environ["APP_STATE_TABLE"]
        bucket_name = os.environ["IMAGES_BUCKET"]
        table = dynamodb.Table(drinklogs_table_name)
        record_id = (event.get("pathParameters") or {}).get("id")

        if method == "POST" and path.endswith("/upload-url"):
            try:
                content_type = validate_upload_input(_parse_json_body(event))
            except ValidationError as exc:
                return _validation_response(exc, event)
            try:
                result = create_upload_url(
                    dynamodb,
                    s3,
                    app_state_table_name,
                    bucket_name,
                    user_id,
                    content_type,
                )
            except RateLimitExceeded:
                return create_response(
                    429,
                    {"error": "Daily upload limit exceeded"},
                    event=event,
                    private=True,
                )
            return create_response(200, result, event=event, private=True)

        if method == "POST" and not record_id:
            try:
                data = validate_create_input(_parse_json_body(event))
                record, created = create_drink_log(
                    dynamodb,
                    s3,
                    drinklogs_table_name,
                    app_state_table_name,
                    bucket_name,
                    user_id,
                    data,
                )
            except ValidationError as exc:
                return _validation_response(exc, event)
            except RateLimitExceeded:
                return create_response(
                    429,
                    {"error": "Daily create or storage limit exceeded"},
                    event=event,
                    private=True,
                )
            except AnalysisConflict as exc:
                return create_response(409, {"error": str(exc)}, event=event, private=True)
            except CreateConflict as exc:
                return create_response(409, {"error": str(exc)}, event=event, private=True)
            except KeyError:
                return create_response(404, {"error": "Drink log not found"}, event=event, private=True)
            return create_response(
                201 if created else 200,
                _public_record(record, s3, bucket_name, user_id),
                event=event,
                private=True,
            )

        if method == "GET" and record_id:
            record = get_owned_drink_log(table, s3, bucket_name, user_id, record_id)
            if not record:
                return create_response(404, {"error": "Drink log not found"}, event=event, private=True)
            return create_response(200, record, event=event, private=True)

        if method == "GET" and not record_id:
            try:
                limit, start_key, filters = parse_timeline_query(query)
            except ValidationError as exc:
                return _validation_response(exc, event)
            records, next_token = get_timeline(
                dynamodb,
                s3,
                drinklogs_table_name,
                bucket_name,
                user_id,
                limit,
                start_key,
                filters,
            )
            return create_response(
                200,
                {
                    "results": records,
                    "drink_logs": records,
                    "count": len(records),
                    "next_token": next_token,
                },
                event=event,
                private=True,
            )

        if method == "PUT" and record_id:
            try:
                data = validate_update_input(_parse_json_body(event))
            except ValidationError as exc:
                return _validation_response(exc, event)
            record = update_drink_log(table, user_id, record_id, data)
            if not record:
                return create_response(404, {"error": "Drink log not found"}, event=event, private=True)
            return create_response(
                200,
                _public_record(record, s3, bucket_name, user_id),
                event=event,
                private=True,
            )

        if method == "DELETE" and record_id:
            deleted = delete_drink_log(
                dynamodb,
                s3,
                drinklogs_table_name,
                app_state_table_name,
                bucket_name,
                user_id,
                record_id,
            )
            if not deleted:
                return create_response(404, {"error": "Drink log not found"}, event=event, private=True)
            return create_response(204, "", event=event, private=True)

        return create_response(405, {"error": "Method not allowed"}, event=event, private=True)
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
