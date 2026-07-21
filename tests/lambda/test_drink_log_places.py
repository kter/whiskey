import json
from types import SimpleNamespace

import pytest
import requests

from tests.lambda_module_loader import load_lambda_module


places = load_lambda_module("drink_log_places_tests", "lambda/drink-log-analyze/places.py")


class TransactionCanceled(Exception):
    def __init__(self, reasons=None):
        self.response = {"CancellationReasons": reasons or []}
        super().__init__("transaction cancelled")


class RecordingClient:
    exceptions = SimpleNamespace(TransactionCanceledException=TransactionCanceled)

    def __init__(self):
        self.transactions = []

    def transact_write_items(self, **kwargs):
        self.transactions.append(kwargs["TransactItems"])


class FakeDynamoDB:
    def __init__(self, records=None, unprocessed_once=False):
        self.meta = SimpleNamespace(client=RecordingClient())
        self.records = {item["id"]: item for item in (records or [])}
        self.unprocessed_once = unprocessed_once
        self.batch_calls = 0

    def batch_get_item(self, **kwargs):
        self.batch_calls += 1
        request = kwargs["RequestItems"]
        if self.unprocessed_once and self.batch_calls == 1:
            return {"Responses": {"DrinkLogs-test": []}, "UnprocessedKeys": request}
        keys = request["DrinkLogs-test"]["Keys"]
        return {
            "Responses": {
                "DrinkLogs-test": [self.records[key["id"]] for key in keys if key["id"] in self.records]
            },
            "UnprocessedKeys": {},
        }


class FakeResponse:
    def __init__(self, payload=None, status_code=200, json_error=False):
        self.payload = payload
        self.status_code = status_code
        self.json_error = json_error

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))

    def json(self):
        if self.json_error:
            raise ValueError("bad json")
        return self.payload


class Context:
    aws_request_id = "request-1"

    def get_remaining_time_in_millis(self):
        return 10_000


@pytest.fixture(autouse=True)
def environment(monkeypatch):
    values = {
        "ENVIRONMENT": "dev",
        "APP_STATE_TABLE": "AppState-test",
        "DRINKLOGS_TABLE": "DrinkLogs-test",
        "COGNITO_USER_POOL_ID": "ap-northeast-1_pool",
        "COGNITO_CLIENT_ID": "client-123",
        "AWS_REGION": "ap-northeast-1",
        "PLACES_USER_DAILY_LIMIT": "30",
        "PLACES_GLOBAL_DAILY_LIMIT": "15",
        "PLACES_GLOBAL_MONTHLY_LIMIT": "150",
        "PLACES_SECRET_NAME": "places-test",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("MOCK_AI", raising=False)
    monkeypatch.delenv("MOCK_PLACES", raising=False)
    monkeypatch.setattr(places, "_PLACES_API_KEY", None)
    monkeypatch.setattr(places, "_load_api_key", lambda: "secret-key")


def _event(path, body):
    return {
        "httpMethod": "POST",
        "path": path,
        "body": json.dumps(body),
        "requestContext": {
            "authorizer": {
                "claims": {"sub": "user-1", "aud": "client-123", "token_use": "id"}
            }
        },
    }


def test_nearby_request_matches_new_api_contract_and_propagates_attributions(monkeypatch):
    dynamodb = FakeDynamoDB()
    call = {}

    def post(url, **kwargs):
        call.update(url=url, **kwargs)
        return FakeResponse(
            {
                "places": [
                    {
                        "id": "place-1",
                        "displayName": {"text": "バー621", "languageCode": "ja"},
                        "formattedAddress": "東京都新宿区",
                        "attributions": [{"provider": "example"}],
                    }
                ]
            }
        )

    monkeypatch.setattr(places, "get_dynamodb_resource", lambda: dynamodb)
    monkeypatch.setattr(places.requests, "post", post)
    response = places.lambda_handler(
        _event("/api/drink-logs/places", {"lat": 35.0, "lng": 139.0}), Context()
    )
    assert response["statusCode"] == 200
    result = json.loads(response["body"])[0]
    assert result["attributions"] == [{"provider": "example"}]
    assert "secret-key" not in response["body"]
    assert call["url"] == "https://places.googleapis.com/v1/places:searchNearby"
    assert call["timeout"] == (2, 5)
    assert call["headers"]["X-Goog-Api-Key"] == "secret-key"
    assert call["headers"]["X-Goog-FieldMask"] == places.NEARBY_FIELD_MASK
    assert "places.location" not in call["headers"]["X-Goog-FieldMask"]
    assert call["json"] == {
        "includedTypes": ["bar", "restaurant"],
        "rankPreference": "DISTANCE",
        "maxResultCount": 8,
        "languageCode": "ja",
        "regionCode": "JP",
        "locationRestriction": {
            "circle": {
                "center": {"latitude": 35.0, "longitude": 139.0},
                "radius": 300,
            }
        },
    }
    assert len(dynamodb.meta.client.transactions[0]) == 3


@pytest.mark.parametrize(
    "body",
    [
        {"lat": float("nan"), "lng": 139},
        {"lat": float("inf"), "lng": 139},
        {"lat": 91, "lng": 139},
        {"lat": 35, "lng": -181},
        {"lat": "35", "lng": 139},
    ],
)
def test_nearby_rejects_nonfinite_nonnumeric_and_out_of_range(monkeypatch, body):
    dynamodb = FakeDynamoDB()
    monkeypatch.setattr(places, "get_dynamodb_resource", lambda: dynamodb)
    monkeypatch.setattr(places.requests, "post", lambda *args, **kwargs: pytest.fail("must not call"))
    response = places.lambda_handler(_event("/api/drink-logs/places", body), Context())
    assert response["statusCode"] == 400
    assert dynamodb.meta.client.transactions == []


@pytest.mark.parametrize("failure, expected", [(requests.Timeout(), 504), (None, 502)])
def test_nearby_timeout_and_invalid_response(monkeypatch, failure, expected):
    dynamodb = FakeDynamoDB()

    def post(*args, **kwargs):
        del args, kwargs
        if failure:
            raise failure
        return FakeResponse(json_error=True)

    monkeypatch.setattr(places, "get_dynamodb_resource", lambda: dynamodb)
    monkeypatch.setattr(places.requests, "post", post)
    response = places.lambda_handler(
        _event("/api/drink-logs/places", {"lat": 35, "lng": 139}), Context()
    )
    assert response["statusCode"] == expected


def test_resolve_batch_get_deduplicates_and_details_uses_get_contract(monkeypatch):
    records = [
        {"id": "log-1", "user_id": "user-1", "store": {"place_id": "place/with slash"}},
        {"id": "log-2", "user_id": "user-1", "store": {"place_id": "place/with slash"}},
    ]
    dynamodb = FakeDynamoDB(records, unprocessed_once=True)
    calls = []

    def get(url, *, params, headers, timeout):
        calls.append({"url": url, "params": params, "headers": headers, "timeout": timeout})
        return FakeResponse(
            {
                "displayName": {"text": "解決済みバー"},
                "attributions": [{"provider": "google"}],
            }
        )

    monkeypatch.setattr(places, "get_dynamodb_resource", lambda: dynamodb)
    monkeypatch.setattr(places.requests, "get", get)
    items = [
        {"log_id": "log-1", "place_id": "place/with slash"},
        {"log_id": "log-2", "place_id": "place/with slash"},
    ]
    response = places.lambda_handler(
        _event("/api/drink-logs/places/resolve", {"items": items}), Context()
    )
    assert response["statusCode"] == 200
    results = json.loads(response["body"])["results"]
    assert [result["display_name"] for result in results] == ["解決済みバー", "解決済みバー"]
    assert all(result["attributions"] == [{"provider": "google"}] for result in results)
    assert dynamodb.batch_calls == 2
    assert len(calls) == 1
    assert calls[0]["url"].endswith("/places/place%2Fwith%20slash")
    assert calls[0]["params"] == {"languageCode": "ja", "regionCode": "JP"}
    assert calls[0]["headers"] == {
        "X-Goog-Api-Key": "secret-key",
        "X-Goog-FieldMask": "displayName,attributions",
    }
    transaction = dynamodb.meta.client.transactions[0]
    assert all(write["Update"]["ExpressionAttributeValues"][":amount"] == 1 for write in transaction)


def test_resolve_not_found_and_partial_failure_are_placeholders(monkeypatch):
    records = [
        {"id": "log-1", "user_id": "user-1", "store": {"place_id": "gone"}},
        {"id": "log-2", "user_id": "user-1", "store": {"place_id": "broken"}},
    ]
    dynamodb = FakeDynamoDB(records)

    def get(url, **kwargs):
        del kwargs
        if url.endswith("/gone"):
            return FakeResponse({}, status_code=404)
        raise requests.Timeout()

    monkeypatch.setattr(places, "get_dynamodb_resource", lambda: dynamodb)
    monkeypatch.setattr(places.requests, "get", get)
    response = places.lambda_handler(
        _event(
            "/api/drink-logs/places/resolve",
            {
                "items": [
                    {"log_id": "log-1", "place_id": "gone"},
                    {"log_id": "log-2", "place_id": "broken"},
                ]
            },
        ),
        Context(),
    )
    assert response["statusCode"] == 200
    results = json.loads(response["body"])["results"]
    assert [result["display_name"] for result in results] == [places.PLACEHOLDER_NAME] * 2
    assert all(result["attributions"] == [] for result in results)


def test_resolve_rejects_foreign_or_mismatched_log_before_counter_and_http(monkeypatch):
    dynamodb = FakeDynamoDB(
        [{"id": "log-1", "user_id": "other", "store": {"place_id": "place-1"}}]
    )
    monkeypatch.setattr(places, "get_dynamodb_resource", lambda: dynamodb)
    monkeypatch.setattr(places.requests, "get", lambda *args, **kwargs: pytest.fail("must not call"))
    response = places.lambda_handler(
        _event(
            "/api/drink-logs/places/resolve",
            {"items": [{"log_id": "log-1", "place_id": "place-1"}]},
        ),
        Context(),
    )
    assert response["statusCode"] == 403
    assert dynamodb.meta.client.transactions == []


def test_secret_schema_is_strict_and_cached(monkeypatch):
    calls = []

    class Secrets:
        def get_secret_value(self, **kwargs):
            calls.append(kwargs)
            return {"SecretString": '{"apiKey":"abc"}'}

    monkeypatch.undo()
    monkeypatch.setenv("PLACES_SECRET_NAME", "places-test")
    monkeypatch.setattr(places, "_PLACES_API_KEY", None)
    monkeypatch.setattr(places, "get_boto3_client", lambda service: Secrets())
    assert places._load_api_key() == "abc"
    assert places._load_api_key() == "abc"
    assert calls == [{"SecretId": "places-test"}]


def test_mock_guard_and_local_deterministic_flow(monkeypatch):
    monkeypatch.setenv("MOCK_PLACES", "1")
    with pytest.raises(RuntimeError, match="local"):
        places.lambda_handler(
            _event("/api/drink-logs/places", {"lat": 35, "lng": 139}), Context()
        )
    monkeypatch.setenv("ENVIRONMENT", "local")
    dynamodb = FakeDynamoDB()
    monkeypatch.setattr(places, "get_dynamodb_resource", lambda: dynamodb)
    monkeypatch.setattr(places, "_PLACES_API_KEY", None)
    response = places.lambda_handler(
        _event("/api/drink-logs/places", {"lat": 35, "lng": 139}), Context()
    )
    assert response["statusCode"] == 200
    assert json.loads(response["body"])[0]["place_id"] == "mock-place-1"


def test_places_counter_write_failure_is_fail_closed(monkeypatch):
    dynamodb = FakeDynamoDB()

    def fail_write(**kwargs):
        del kwargs
        raise RuntimeError("DynamoDB unavailable")

    dynamodb.meta.client.transact_write_items = fail_write
    monkeypatch.setattr(places, "get_dynamodb_resource", lambda: dynamodb)
    monkeypatch.setattr(places.requests, "post", lambda *args, **kwargs: pytest.fail("must not call"))
    response = places.lambda_handler(
        _event("/api/drink-logs/places", {"lat": 35, "lng": 139}), Context()
    )
    assert response["statusCode"] == 500


def test_nearby_deadline_exhaustion_does_not_start_http(monkeypatch):
    class ExpiredContext(Context):
        def get_remaining_time_in_millis(self):
            return 0

    dynamodb = FakeDynamoDB()
    monkeypatch.setattr(places, "get_dynamodb_resource", lambda: dynamodb)
    monkeypatch.setattr(places.requests, "post", lambda *args, **kwargs: pytest.fail("must not call"))
    response = places.lambda_handler(
        _event("/api/drink-logs/places", {"lat": 35, "lng": 139}), ExpiredContext()
    )
    assert response["statusCode"] == 504


@pytest.mark.parametrize(
    "secret_string",
    [
        "not-json",
        "{}",
        '{"apiKey":""}',
        '{"apiKey":"abc","extra":"forbidden"}',
        '[]',
    ],
)
def test_secret_schema_rejects_missing_malformed_and_extra_fields(monkeypatch, secret_string):
    class Secrets:
        def get_secret_value(self, **kwargs):
            del kwargs
            return {"SecretString": secret_string}

    monkeypatch.undo()
    monkeypatch.setenv("PLACES_SECRET_NAME", "places-test")
    monkeypatch.setattr(places, "_PLACES_API_KEY", None)
    monkeypatch.setattr(places, "get_boto3_client", lambda service: Secrets())
    with pytest.raises(RuntimeError):
        places._load_api_key()
