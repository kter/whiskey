import json
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tests.lambda_module_loader import load_lambda_module


reviews = load_lambda_module("reviews_lambda_tests", "lambda/reviews/index.py")


class TransactionCanceled(Exception):
    def __init__(self, reasons=None):
        self.response = {"CancellationReasons": reasons or []}
        super().__init__("transaction canceled")


class RecordingClient:
    exceptions = SimpleNamespace(TransactionCanceledException=TransactionCanceled)

    def __init__(self):
        self.transactions = []
        self.error = None

    def transact_write_items(self, **kwargs):
        self.transactions.append(kwargs["TransactItems"])
        if self.error:
            raise self.error


class FakeTable:
    def __init__(self, *, item=None, query_response=None):
        self.item = item
        self.query_response = query_response or {"Items": []}
        self.get_calls = []
        self.query_calls = []

    def get_item(self, **kwargs):
        self.get_calls.append(kwargs)
        return {"Item": dict(self.item)} if self.item is not None else {}

    def query(self, **kwargs):
        self.query_calls.append(kwargs)
        return self.query_response


class FakeDynamoDB:
    def __init__(self, tables=None, batch_items=None):
        self.tables = tables or {}
        self.batch_items = batch_items or {}
        self.client = RecordingClient()
        self.meta = SimpleNamespace(client=self.client)
        self.batch_calls = []

    def Table(self, name):
        return self.tables[name]

    def batch_get_item(self, **kwargs):
        self.batch_calls.append(kwargs)
        table_name = next(iter(kwargs["RequestItems"]))
        return {"Responses": {table_name: [dict(item) for item in self.batch_items.get(table_name, [])]}}


@pytest.fixture(autouse=True)
def environment(monkeypatch):
    values = {
        "REVIEWS_TABLE": "Reviews-test",
        "WHISKEYS_TABLE": "WhiskeySearch-test",
        "APP_STATE_TABLE": "AppState-test",
        "COGNITO_USER_POOL_ID": "ap-northeast-1_pool",
        "COGNITO_CLIENT_ID": "client-123",
        "AWS_REGION": "ap-northeast-1",
        "ALLOWED_ORIGINS": "https://app.example",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)


def valid_create(**overrides):
    data = {
        "whiskey_id": "whiskey-1",
        "rating": 4,
        "notes": "smoky",
        "serving_style": "NEAT",
        "date": "2026-07-19",
        "is_public": False,
    }
    data.update(overrides)
    return data


def auth_event(method="GET", path="/api/reviews", **extra):
    event = {
        "httpMethod": method,
        "path": path,
        "headers": {"origin": "https://app.example"},
        "requestContext": {
            "requestId": "request-1",
            "authorizer": {
                "claims": {"sub": "user-1", "aud": "client-123", "token_use": "id"}
            },
        },
        "queryStringParameters": None,
    }
    event.update(extra)
    return event


@pytest.mark.parametrize("rating", [1, 2.5, 5])
def test_create_validation_accepts_frontend_rating_range(rating):
    validated = reviews.validate_review_input(valid_create(rating=rating), creating=True)
    assert validated["rating"] == Decimal(str(rating))


@pytest.mark.parametrize("rating", [0, 5.1, True, "5"])
def test_create_validation_rejects_invalid_rating(rating):
    with pytest.raises(reviews.ValidationError) as exc:
        reviews.validate_review_input(valid_create(rating=rating), creating=True)
    assert "rating" in exc.value.fields


def test_validation_rejects_noncanonical_fields_and_values():
    with pytest.raises(reviews.ValidationError) as exc:
        reviews.validate_review_input(
            valid_create(
                serving_style="neat",
                date="2026-02-30",
                notes="n" * 2001,
                is_public="true",
                image_url="https://private.example/photo.jpg",
            ),
            creating=True,
        )
    assert set(exc.value.fields) == {"serving_style", "date", "notes", "is_public", "image_url"}


def test_update_is_whitelisted_and_rejects_whiskey_id():
    assert reviews.validate_review_input({"rating": 5, "is_public": True}, creating=False) == {
        "rating": Decimal("5"),
        "is_public": True,
    }
    with pytest.raises(reviews.ValidationError) as exc:
        reviews.validate_review_input({"whiskey_id": "replacement"}, creating=False)
    assert exc.value.fields["whiskey_id"] == "Field is not accepted"


def test_create_transaction_contains_rate_limits_review_and_dirty_counter():
    dynamodb = FakeDynamoDB()
    created = reviews.create_review(
        dynamodb,
        "Reviews-test",
        "AppState-test",
        "user-1",
        reviews.validate_review_input(valid_create(is_public=True), creating=True),
    )
    transaction = dynamodb.client.transactions[0]
    assert len(transaction) == 4
    assert transaction[0]["Update"]["Key"]["pk"].startswith("review-rate#user#user-1#")
    assert transaction[1]["Update"]["Key"]["pk"].startswith("review-rate#global#")
    assert transaction[0]["Update"]["ExpressionAttributeValues"][":ttl"] > 0
    assert transaction[2]["Put"]["Item"]["public_pk"] == "PUBLIC"
    assert transaction[3]["Update"]["Key"] == {"pk": reviews.DIRTY_COUNTER_KEY}
    assert created["is_public"] is True


def test_create_rate_limit_condition_maps_to_429_error():
    dynamodb = FakeDynamoDB()
    dynamodb.client.error = TransactionCanceled([
        {"Code": "ConditionalCheckFailed"},
        {"Code": "None"},
    ])
    with pytest.raises(reviews.RateLimitExceeded):
        reviews.create_review(
            dynamodb,
            "Reviews-test",
            "AppState-test",
            "user-1",
            reviews.validate_review_input(valid_create(), creating=True),
        )


def test_post_handler_returns_429_for_daily_limit(monkeypatch):
    whiskey_table = FakeTable(item={"id": "whiskey-1"})
    dynamodb = FakeDynamoDB({"WhiskeySearch-test": whiskey_table})
    monkeypatch.setattr(reviews, "get_dynamodb_resource", lambda: dynamodb)

    def limited(*_args, **_kwargs):
        raise reviews.RateLimitExceeded

    monkeypatch.setattr(reviews, "create_review", limited)
    response = reviews.lambda_handler(
        auth_event("POST", body=json.dumps(valid_create())),
        SimpleNamespace(aws_request_id="aws-rate"),
    )
    assert response["statusCode"] == 429
    assert json.loads(response["body"])["error"] == "Daily review limit exceeded"


def test_update_uses_atomic_owner_condition_and_sparse_index_remove():
    review_table = FakeTable(item={"id": "review-1", "user_id": "user-1", "is_public": False})
    dynamodb = FakeDynamoDB({"Reviews-test": review_table})
    result = reviews.update_review(
        dynamodb,
        "Reviews-test",
        "AppState-test",
        "user-1",
        "review-1",
        {"rating": Decimal("5"), "is_public": False},
    )
    update = dynamodb.client.transactions[0][0]["Update"]
    assert update["ConditionExpression"] == "#owner = :caller"
    assert "REMOVE #public_pk" in update["UpdateExpression"]
    assert dynamodb.client.transactions[0][1]["Update"]["Key"]["pk"] == reviews.DIRTY_COUNTER_KEY
    assert review_table.get_calls[0]["ConsistentRead"] is True
    assert result["id"] == "review-1"


def test_update_and_delete_hide_missing_or_foreign_reviews():
    dynamodb = FakeDynamoDB({"Reviews-test": FakeTable()})
    dynamodb.client.error = TransactionCanceled([{"Code": "ConditionalCheckFailed"}])
    assert reviews.update_review(
        dynamodb, "Reviews-test", "AppState-test", "user-1", "foreign", {"rating": Decimal("4")}
    ) is None
    assert reviews.delete_review(
        dynamodb, "Reviews-test", "AppState-test", "user-1", "foreign"
    ) is False


def test_delete_owner_check_and_dirty_increment_are_one_transaction():
    dynamodb = FakeDynamoDB()
    assert reviews.delete_review(dynamodb, "Reviews-test", "AppState-test", "user-1", "review-1")
    transaction = dynamodb.client.transactions[0]
    assert transaction[0]["Delete"]["ConditionExpression"] == "#owner = :caller"
    assert transaction[1]["Update"]["Key"] == {"pk": reviews.DIRTY_COUNTER_KEY}


def test_public_listing_queries_sparse_gsi_and_rechecks_base_table_consistently():
    candidates = [
        {"id": "public", "date": "2026-07-19", "public_pk": "PUBLIC", "user_id": "u1"},
        {"id": "stale", "date": "2026-07-18", "public_pk": "PUBLIC", "user_id": "u2"},
    ]
    review_table = FakeTable(query_response={"Items": candidates})
    dynamodb = FakeDynamoDB(
        {"Reviews-test": review_table},
        {
            "Reviews-test": [
                {"id": "public", "whiskey_id": "w1", "date": "2026-07-19", "is_public": True, "user_id": "u1"},
                {"id": "stale", "whiskey_id": "w2", "date": "2026-07-18", "is_public": False, "user_id": "u2"},
            ],
            "WhiskeySearch-test": [{"id": "w1", "name": "Public Whiskey"}],
        },
    )
    result, token = reviews.get_public_reviews(
        dynamodb, "Reviews-test", "WhiskeySearch-test", 20, None
    )
    assert token is None
    assert [item["id"] for item in result] == ["public"]
    assert "user_id" not in result[0]
    assert result[0]["whiskey_name"] == "Public Whiskey"
    assert review_table.query_calls[0]["IndexName"] == "PublicDateIndex"
    review_batch = dynamodb.batch_calls[0]["RequestItems"]["Reviews-test"]
    assert review_batch["ConsistentRead"] is True


def test_public_to_private_transition_is_not_returned_even_with_stale_gsi_candidate():
    candidate = {"id": "review-1", "date": "2026-07-19", "public_pk": "PUBLIC"}
    review_table = FakeTable(query_response={"Items": [candidate]})
    dynamodb = FakeDynamoDB(
        {"Reviews-test": review_table},
        {"Reviews-test": [{"id": "review-1", "whiskey_id": "w1", "is_public": True}]},
    )
    before, _ = reviews.get_public_reviews(dynamodb, "Reviews-test", "WhiskeySearch-test", 20, None)
    assert [item["id"] for item in before] == ["review-1"]

    dynamodb.batch_items["Reviews-test"][0]["is_public"] = False
    after, _ = reviews.get_public_reviews(dynamodb, "Reviews-test", "WhiskeySearch-test", 20, None)
    assert after == []


def test_user_reviews_use_gsi_limit_and_next_token():
    table = FakeTable(query_response={
        "Items": [{"id": "review-1", "whiskey_id": "w1"}],
        "LastEvaluatedKey": {"id": "review-1", "user_id": "user-1", "date": "2026-07-19"},
    })
    dynamodb = FakeDynamoDB(
        {"Reviews-test": table},
        {"WhiskeySearch-test": [{"id": "w1", "name": "Whiskey"}]},
    )
    result, token = reviews.get_user_reviews(
        dynamodb, "Reviews-test", "WhiskeySearch-test", "user-1", 10, None
    )
    assert result[0]["whiskey_name"] == "Whiskey"
    assert reviews.decode_next_token(token)["id"] == "review-1"
    assert table.query_calls[0]["Limit"] == 10
    assert table.query_calls[0]["IndexName"] == "UserDateIndex"


def test_whiskey_existence_check_is_strongly_consistent():
    table = FakeTable(item={"id": "w1"})
    dynamodb = FakeDynamoDB({"WhiskeySearch-test": table})
    assert reviews._whiskey_exists(dynamodb, "WhiskeySearch-test", "w1")
    assert table.get_calls[0]["ConsistentRead"] is True


def test_owner_get_and_delete_routes(monkeypatch):
    dynamodb = FakeDynamoDB()
    monkeypatch.setattr(reviews, "get_dynamodb_resource", lambda: dynamodb)
    monkeypatch.setattr(reviews, "get_owned_review", lambda *args: {"id": "review-1", "user_id": "user-1"})
    get_response = reviews.lambda_handler(
        auth_event("GET", "/api/reviews/review-1", pathParameters={"id": "review-1"}),
        SimpleNamespace(aws_request_id="aws-1"),
    )
    assert get_response["statusCode"] == 200
    assert get_response["headers"]["Cache-Control"] == "private, no-store"

    monkeypatch.setattr(reviews, "delete_review", lambda *args: True)
    delete_response = reviews.lambda_handler(
        auth_event("DELETE", "/api/reviews/review-1", pathParameters={"id": "review-1"}),
        SimpleNamespace(aws_request_id="aws-2"),
    )
    assert delete_response["statusCode"] == 204


def test_missing_or_invalid_claims_return_401(monkeypatch):
    monkeypatch.setattr(reviews, "get_dynamodb_resource", lambda: FakeDynamoDB())
    event = auth_event("GET")
    event["requestContext"]["authorizer"]["claims"]["aud"] = "wrong-client"
    response = reviews.lambda_handler(event, SimpleNamespace(aws_request_id="aws-1"))
    assert response["statusCode"] == 401


def test_500_response_is_generic_and_contains_request_id(monkeypatch):
    def fail():
        raise RuntimeError("database-password-was-here")

    monkeypatch.setattr(reviews, "get_dynamodb_resource", fail)
    response = reviews.lambda_handler(auth_event(), SimpleNamespace(aws_request_id="aws-request-9"))
    body = json.loads(response["body"])
    assert response["statusCode"] == 500
    assert body == {"error": "Internal server error", "request_id": "aws-request-9"}
    assert "database-password-was-here" not in response["body"]
