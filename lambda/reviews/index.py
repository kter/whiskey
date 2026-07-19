"""Authenticated review CRUD and public review listing."""

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

try:
    from whiskey_common.clients import get_dynamodb_resource
    from whiskey_common.jwt_utils import extract_user_id_from_event
    from whiskey_common.logger import extract_correlation_id, get_logger
    from whiskey_common.responses import create_response, get_cors_headers
    from whiskey_common.scan_utils import decode_next_token, encode_next_token
except ModuleNotFoundError as exc:
    if exc.name != "whiskey_common":
        raise
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common" / "python"))
    from whiskey_common.clients import get_dynamodb_resource
    from whiskey_common.jwt_utils import extract_user_id_from_event
    from whiskey_common.logger import extract_correlation_id, get_logger
    from whiskey_common.responses import create_response, get_cors_headers
    from whiskey_common.scan_utils import decode_next_token, encode_next_token


SERVING_STYLES = {"NEAT", "ROCKS", "WATER", "SODA", "COCKTAIL"}
CREATE_FIELDS = {"whiskey_id", "rating", "notes", "serving_style", "date", "is_public"}
UPDATE_FIELDS = {"rating", "notes", "serving_style", "date", "is_public"}
PUBLIC_PRIVATE_FIELDS = {"user_id", "public_pk", "email", "username", "cognito_sub"}
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DEFAULT_PAGE_LIMIT = 20
MAX_PAGE_LIMIT = 100
MAX_PUBLIC_PAGE_QUERIES = 10
DIRTY_COUNTER_KEY = "review-change-counter"


class ValidationError(ValueError):
    def __init__(self, fields: Mapping[str, str]):
        super().__init__("Validation failed")
        self.fields = dict(fields)


class RateLimitExceeded(Exception):
    pass


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


def validate_review_input(data: Mapping[str, Any], *, creating: bool) -> dict[str, Any]:
    allowed_fields = CREATE_FIELDS if creating else UPDATE_FIELDS
    errors: dict[str, str] = {}
    unknown_fields = sorted(set(data) - allowed_fields)
    for field in unknown_fields:
        errors[field] = "Field is not accepted"

    if creating:
        for field in ("whiskey_id", "rating", "date"):
            if field not in data:
                errors[field] = "Field is required"
    elif not data:
        errors["body"] = "At least one mutable field is required"

    validated: dict[str, Any] = {}
    if "whiskey_id" in data:
        whiskey_id = data["whiskey_id"]
        if not isinstance(whiskey_id, str) or not whiskey_id.strip():
            errors["whiskey_id"] = "Must be a non-empty string"
        else:
            validated["whiskey_id"] = whiskey_id.strip()

    if "rating" in data:
        rating = _validate_rating(data["rating"])
        if rating is None:
            errors["rating"] = "Must be a number from 1 to 5"
        else:
            validated["rating"] = rating

    if "notes" in data:
        notes = data["notes"]
        if not isinstance(notes, str):
            errors["notes"] = "Must be a string"
        elif len(notes) > 2000:
            errors["notes"] = "Must be at most 2000 characters"
        else:
            validated["notes"] = notes

    if "serving_style" in data:
        serving_style = data["serving_style"]
        if serving_style not in SERVING_STYLES:
            errors["serving_style"] = f"Must be one of {', '.join(sorted(SERVING_STYLES))}"
        else:
            validated["serving_style"] = serving_style

    if "date" in data:
        review_date = data["date"]
        if not isinstance(review_date, str) or not DATE_PATTERN.fullmatch(review_date):
            errors["date"] = "Must be a full date in YYYY-MM-DD format"
        else:
            try:
                datetime.strptime(review_date, "%Y-%m-%d")
                validated["date"] = review_date
            except ValueError:
                errors["date"] = "Must be a valid calendar date"

    if "is_public" in data:
        if type(data["is_public"]) is not bool:
            errors["is_public"] = "Must be a boolean"
        else:
            validated["is_public"] = data["is_public"]

    if errors:
        raise ValidationError(errors)
    return validated


def parse_pagination(query_params: Mapping[str, Any]) -> tuple[int, dict[str, Any] | None]:
    try:
        limit = int(query_params.get("limit", DEFAULT_PAGE_LIMIT))
    except (TypeError, ValueError) as exc:
        raise ValidationError({"limit": f"Must be an integer from 1 to {MAX_PAGE_LIMIT}"}) from exc
    if not 1 <= limit <= MAX_PAGE_LIMIT:
        raise ValidationError({"limit": f"Must be from 1 to {MAX_PAGE_LIMIT}"})
    try:
        start_key = decode_next_token(query_params.get("next_token"))
    except ValueError as exc:
        raise ValidationError({"next_token": "Invalid continuation token"}) from exc
    return limit, start_key


def _whiskey_exists(dynamodb: Any, table_name: str, whiskey_id: str) -> bool:
    response = dynamodb.Table(table_name).get_item(
        Key={"id": whiskey_id},
        ConsistentRead=True,
        ProjectionExpression="id",
    )
    return "Item" in response


def _dirty_counter_update(app_state_table_name: str, now: str) -> dict[str, Any]:
    return {
        "Update": {
            "TableName": app_state_table_name,
            "Key": {"pk": DIRTY_COUNTER_KEY},
            "UpdateExpression": "SET updated_at = :updated_at ADD #count :one",
            "ExpressionAttributeNames": {"#count": "count"},
            "ExpressionAttributeValues": {":one": 1, ":updated_at": now},
        }
    }


def _rate_counter_update(
    table_name: str,
    key: str,
    limit: int,
    ttl: int,
    now: str,
) -> dict[str, Any]:
    return {
        "Update": {
            "TableName": table_name,
            "Key": {"pk": key},
            "UpdateExpression": "SET #ttl = if_not_exists(#ttl, :ttl), updated_at = :updated_at ADD #count :one",
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


def create_review(
    dynamodb: Any,
    reviews_table_name: str,
    app_state_table_name: str,
    user_id: str,
    data: Mapping[str, Any],
) -> dict[str, Any]:
    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat().replace("+00:00", "Z")
    review: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "whiskey_id": data["whiskey_id"],
        "user_id": user_id,
        "rating": data["rating"],
        "notes": data.get("notes", ""),
        "serving_style": data.get("serving_style", "NEAT"),
        "date": data["date"],
        "is_public": data.get("is_public", False),
        "created_at": now,
        "updated_at": now,
    }
    if review["is_public"]:
        review["public_pk"] = "PUBLIC"

    utc_date = now_dt.strftime("%Y-%m-%d")
    ttl = int((now_dt + timedelta(days=2)).timestamp())
    user_limit = int(os.environ.get("REVIEW_DAILY_USER_LIMIT", "100"))
    global_limit = int(os.environ.get("REVIEW_DAILY_GLOBAL_LIMIT", "10000"))
    client = dynamodb.meta.client
    transaction = [
        _rate_counter_update(
            app_state_table_name,
            f"review-rate#user#{user_id}#{utc_date}",
            user_limit,
            ttl,
            now,
        ),
        _rate_counter_update(
            app_state_table_name,
            f"review-rate#global#{utc_date}",
            global_limit,
            ttl,
            now,
        ),
        {
            "Put": {
                "TableName": reviews_table_name,
                "Item": review,
                "ConditionExpression": "attribute_not_exists(id)",
            }
        },
        _dirty_counter_update(app_state_table_name, now),
    ]
    try:
        client.transact_write_items(TransactItems=transaction)
    except client.exceptions.TransactionCanceledException as exc:
        reasons = exc.response.get("CancellationReasons", [])
        if not reasons or any(reason.get("Code") == "ConditionalCheckFailed" for reason in reasons[:2]):
            raise RateLimitExceeded from exc
        raise
    return review


def update_review(
    dynamodb: Any,
    reviews_table_name: str,
    app_state_table_name: str,
    user_id: str,
    review_id: str,
    data: Mapping[str, Any],
) -> dict[str, Any] | None:
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    names = {"#owner": "user_id", "#updated_at": "updated_at"}
    values: dict[str, Any] = {":caller": user_id, ":updated_at": now}
    set_parts = ["#updated_at = :updated_at"]
    remove_parts: list[str] = []
    for field in ("rating", "notes", "serving_style", "date"):
        if field in data:
            name_key = f"#{field}"
            value_key = f":{field}"
            names[name_key] = field
            values[value_key] = data[field]
            set_parts.append(f"{name_key} = {value_key}")
    if "is_public" in data:
        names["#is_public"] = "is_public"
        names["#public_pk"] = "public_pk"
        values[":is_public"] = data["is_public"]
        set_parts.append("#is_public = :is_public")
        if data["is_public"]:
            values[":public_pk"] = "PUBLIC"
            set_parts.append("#public_pk = :public_pk")
        else:
            remove_parts.append("#public_pk")

    update_expression = f"SET {', '.join(set_parts)}"
    if remove_parts:
        update_expression += f" REMOVE {', '.join(remove_parts)}"
    client = dynamodb.meta.client
    try:
        client.transact_write_items(
            TransactItems=[
                {
                    "Update": {
                        "TableName": reviews_table_name,
                        "Key": {"id": review_id},
                        "UpdateExpression": update_expression,
                        "ConditionExpression": "#owner = :caller",
                        "ExpressionAttributeNames": names,
                        "ExpressionAttributeValues": values,
                    }
                },
                _dirty_counter_update(app_state_table_name, now),
            ]
        )
    except client.exceptions.TransactionCanceledException as exc:
        reasons = exc.response.get("CancellationReasons", [])
        if reasons and reasons[0].get("Code") != "ConditionalCheckFailed":
            raise
        return None
    response = dynamodb.Table(reviews_table_name).get_item(
        Key={"id": review_id},
        ConsistentRead=True,
    )
    return response.get("Item")


def delete_review(
    dynamodb: Any,
    reviews_table_name: str,
    app_state_table_name: str,
    user_id: str,
    review_id: str,
) -> bool:
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    client = dynamodb.meta.client
    try:
        client.transact_write_items(
            TransactItems=[
                {
                    "Delete": {
                        "TableName": reviews_table_name,
                        "Key": {"id": review_id},
                        "ConditionExpression": "#owner = :caller",
                        "ExpressionAttributeNames": {"#owner": "user_id"},
                        "ExpressionAttributeValues": {":caller": user_id},
                    }
                },
                _dirty_counter_update(app_state_table_name, now),
            ]
        )
    except client.exceptions.TransactionCanceledException as exc:
        reasons = exc.response.get("CancellationReasons", [])
        if reasons and reasons[0].get("Code") != "ConditionalCheckFailed":
            raise
        return False
    return True


def _batch_get(dynamodb: Any, table_name: str, keys: list[dict[str, Any]], *, consistent: bool) -> list[dict]:
    if not keys:
        return []
    request_items = {table_name: {"Keys": keys, "ConsistentRead": consistent}}
    items: list[dict] = []
    for _ in range(3):
        response = dynamodb.batch_get_item(RequestItems=request_items)
        items.extend(response.get("Responses", {}).get(table_name, []))
        unprocessed = response.get("UnprocessedKeys", {})
        if not unprocessed:
            break
        request_items = unprocessed
    return items


def _attach_whiskey_details(dynamodb: Any, table_name: str, reviews: list[dict]) -> None:
    whiskey_ids = list(dict.fromkeys(review.get("whiskey_id") for review in reviews if review.get("whiskey_id")))
    whiskeys = _batch_get(
        dynamodb,
        table_name,
        [{"id": whiskey_id} for whiskey_id in whiskey_ids],
        consistent=False,
    )
    by_id = {item["id"]: item for item in whiskeys}
    for review in reviews:
        whiskey = by_id.get(review.get("whiskey_id"))
        if whiskey:
            review["whiskey_name"] = whiskey.get("name") or whiskey.get("name_en") or whiskey.get("name_ja", "")
            review["whiskey_distillery"] = (
                whiskey.get("distillery")
                or whiskey.get("distillery_en")
                or whiskey.get("distillery_ja", "")
            )


def get_user_reviews(
    dynamodb: Any,
    reviews_table_name: str,
    whiskeys_table_name: str,
    user_id: str,
    limit: int,
    start_key: dict[str, Any] | None,
) -> tuple[list[dict], str | None]:
    kwargs: dict[str, Any] = {
        "IndexName": "UserDateIndex",
        "KeyConditionExpression": "user_id = :user_id",
        "ExpressionAttributeValues": {":user_id": user_id},
        "ScanIndexForward": False,
        "Limit": limit,
    }
    if start_key:
        kwargs["ExclusiveStartKey"] = start_key
    response = dynamodb.Table(reviews_table_name).query(**kwargs)
    reviews = response.get("Items", [])
    _attach_whiskey_details(dynamodb, whiskeys_table_name, reviews)
    return reviews, encode_next_token(response.get("LastEvaluatedKey"))


def get_public_reviews(
    dynamodb: Any,
    reviews_table_name: str,
    whiskeys_table_name: str,
    limit: int,
    start_key: dict[str, Any] | None,
) -> tuple[list[dict], str | None]:
    reviews_table = dynamodb.Table(reviews_table_name)
    verified: list[dict] = []
    last_evaluated_key = start_key
    next_token: str | None = None
    page_queries = 0
    while len(verified) < limit and page_queries < MAX_PUBLIC_PAGE_QUERIES:
        page_queries += 1
        kwargs: dict[str, Any] = {
            "IndexName": "PublicDateIndex",
            "KeyConditionExpression": "public_pk = :public_pk",
            "ExpressionAttributeValues": {":public_pk": "PUBLIC"},
            "ScanIndexForward": False,
            "Limit": limit - len(verified),
        }
        if last_evaluated_key:
            kwargs["ExclusiveStartKey"] = last_evaluated_key
        response = reviews_table.query(**kwargs)
        candidates = response.get("Items", [])
        last_evaluated_key = response.get("LastEvaluatedKey")
        base_items = _batch_get(
            dynamodb,
            reviews_table_name,
            [{"id": item["id"]} for item in candidates],
            consistent=True,
        )
        by_id = {item["id"]: item for item in base_items if item.get("is_public") is True}
        for candidate in candidates:
            item = by_id.get(candidate["id"])
            if item:
                verified.append({key: value for key, value in item.items() if key not in PUBLIC_PRIVATE_FIELDS})
        if not last_evaluated_key:
            next_token = None
            break
        next_token = encode_next_token(last_evaluated_key)
    _attach_whiskey_details(dynamodb, whiskeys_table_name, verified)
    return verified, next_token


def get_owned_review(
    dynamodb: Any,
    reviews_table_name: str,
    whiskeys_table_name: str,
    user_id: str,
    review_id: str,
) -> dict[str, Any] | None:
    response = dynamodb.Table(reviews_table_name).get_item(
        Key={"id": review_id},
        ConsistentRead=True,
    )
    review = response.get("Item")
    if not review or review.get("user_id") != user_id:
        return None
    _attach_whiskey_details(dynamodb, whiskeys_table_name, [review])
    return review


def _private_headers(event: Mapping[str, Any]) -> dict[str, str]:
    return get_cors_headers(event, private=True)


def _authenticate(event: Mapping[str, Any]) -> str | None:
    return extract_user_id_from_event(event)


def _validation_response(exc: ValidationError, headers: Mapping[str, str]) -> dict[str, Any]:
    return create_response(400, {"error": "Validation failed", "fields": exc.fields}, headers)


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    start_time = time.monotonic()
    request_id = _request_id(event, context)
    logger = get_logger("reviews", correlation_id=extract_correlation_id(event) or request_id)
    method = event.get("httpMethod", "UNKNOWN")
    path = (event.get("path") or "").rstrip("/")
    query_params = event.get("queryStringParameters") or {}
    logger.log_api_request(method=method, path=path, query_params=query_params)

    public_headers = get_cors_headers(event)
    private_headers = _private_headers(event)
    try:
        dynamodb = get_dynamodb_resource()
        reviews_table_name = os.environ["REVIEWS_TABLE"]
        whiskeys_table_name = os.environ["WHISKEYS_TABLE"]
        app_state_table_name = os.environ["APP_STATE_TABLE"]
        review_id = (event.get("pathParameters") or {}).get("id")

        if method == "GET" and path.endswith("/public"):
            try:
                limit, start_key = parse_pagination(query_params)
            except ValidationError as exc:
                return _validation_response(exc, public_headers)
            reviews, next_token = get_public_reviews(
                dynamodb,
                reviews_table_name,
                whiskeys_table_name,
                limit,
                start_key,
            )
            return create_response(
                200,
                {"results": reviews, "reviews": reviews, "count": len(reviews), "next_token": next_token},
                public_headers,
                start_time=start_time,
                logger=logger,
            )

        user_id = _authenticate(event)
        if not user_id:
            return create_response(401, {"error": "Authentication required"}, private_headers)

        if method == "GET" and review_id:
            review = get_owned_review(
                dynamodb,
                reviews_table_name,
                whiskeys_table_name,
                user_id,
                review_id,
            )
            if not review:
                return create_response(404, {"error": "Review not found"}, private_headers)
            return create_response(200, review, private_headers)

        if method == "GET":
            try:
                limit, start_key = parse_pagination(query_params)
            except ValidationError as exc:
                return _validation_response(exc, private_headers)
            reviews, next_token = get_user_reviews(
                dynamodb,
                reviews_table_name,
                whiskeys_table_name,
                user_id,
                limit,
                start_key,
            )
            return create_response(
                200,
                {"results": reviews, "reviews": reviews, "count": len(reviews), "next_token": next_token},
                private_headers,
            )

        if method == "POST":
            try:
                data = validate_review_input(_parse_json_body(event), creating=True)
            except ValidationError as exc:
                return _validation_response(exc, private_headers)
            if not _whiskey_exists(dynamodb, whiskeys_table_name, data["whiskey_id"]):
                return _validation_response(
                    ValidationError({"whiskey_id": "Whiskey does not exist"}),
                    private_headers,
                )
            try:
                review = create_review(
                    dynamodb,
                    reviews_table_name,
                    app_state_table_name,
                    user_id,
                    data,
                )
            except RateLimitExceeded:
                return create_response(429, {"error": "Daily review limit exceeded"}, private_headers)
            return create_response(201, review, private_headers)

        if method == "PUT" and review_id:
            try:
                data = validate_review_input(_parse_json_body(event), creating=False)
            except ValidationError as exc:
                return _validation_response(exc, private_headers)
            review = update_review(
                dynamodb,
                reviews_table_name,
                app_state_table_name,
                user_id,
                review_id,
                data,
            )
            if not review:
                return create_response(404, {"error": "Review not found"}, private_headers)
            return create_response(200, review, private_headers)

        if method == "DELETE" and review_id:
            deleted = delete_review(
                dynamodb,
                reviews_table_name,
                app_state_table_name,
                user_id,
                review_id,
            )
            if not deleted:
                return create_response(404, {"error": "Review not found"}, private_headers)
            return create_response(204, "", private_headers)

        return create_response(405, {"error": "Method not allowed"}, private_headers)
    except Exception as exc:
        logger.error("Unhandled reviews error", error=str(exc), request_id=request_id)
        return create_response(
            500,
            {"error": "Internal server error", "request_id": request_id},
            public_headers,
            start_time=start_time,
            logger=logger,
        )
