import json
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tests.lambda_module_loader import load_lambda_module


search = load_lambda_module("whiskeys_search_lambda_tests", "lambda/whiskeys-search/index.py")
list_lambda = load_lambda_module("whiskeys_list_lambda_tests", "lambda/whiskeys-list/index.py")
service_module = load_lambda_module(
    "whiskey_search_service_tests",
    "lambda/whiskeys-search/python/whiskey_search_service.py",
)


@pytest.fixture(autouse=True)
def environment(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://app.example")
    monkeypatch.setenv("WHISKEY_SEARCH_TABLE", "WhiskeySearch-test")
    monkeypatch.setenv("WHISKEYS_TABLE", "WhiskeySearch-test")
    monkeypatch.setenv("REVIEWS_TABLE", "Reviews-test")
    monkeypatch.setenv("ENVIRONMENT", "test")


def event(path="/api/whiskeys/search", query=None):
    return {
        "httpMethod": "GET",
        "path": path,
        "headers": {"origin": "https://app.example"},
        "queryStringParameters": query,
        "requestContext": {"requestId": "request-1"},
    }


def test_ranking_logic_is_preserved_while_common_helpers_are_used():
    whiskeys = Mock()
    whiskeys.scan.return_value = {
        "Items": [
            {"id": "w1", "name": "One"},
            {"id": "w2", "name": "Two"},
        ]
    }
    review_table = Mock()
    review_table.scan.return_value = {
        "Items": [
            {"whiskey_id": "w1", "rating": Decimal("4")},
            {"whiskey_id": "w2", "rating": Decimal("5")},
        ]
    }
    dynamodb = Mock()
    dynamodb.Table.side_effect = [whiskeys, review_table]
    result = search.get_whiskey_ranking(dynamodb, "WhiskeySearch-test", "Reviews-test")
    assert [item["id"] for item in result["rankings"]] == ["w2", "w1"]
    assert result["rankings"][0]["avg_rating"] == 5


def test_legacy_search_path_uses_configured_client_factory(monkeypatch):
    table = Mock()
    table.scan.side_effect = [
        {"Items": [{"name": "schema sample"}]},
        {"Items": [{"id": "w1", "name": "Hibiki", "distillery": "Suntory"}]},
    ]
    dynamodb = Mock()
    dynamodb.Table.return_value = table
    monkeypatch.setattr(search, "USE_NEW_SERVICE", False)
    monkeypatch.setattr(search, "get_dynamodb_resource", lambda: dynamodb)
    response = search.lambda_handler(event(query={"q": "Hibiki"}), SimpleNamespace(aws_request_id="aws-1"))
    body = json.loads(response["body"])
    assert response["statusCode"] == 200
    assert body["count"] == 1
    assert body["whiskeys"][0]["name"] == "Hibiki"
    assert response["headers"]["Vary"] == "Origin"


def test_search_500_does_not_expose_exception(monkeypatch):
    monkeypatch.setattr(search, "USE_NEW_SERVICE", False)

    def fail():
        raise RuntimeError("secret-search-error")

    monkeypatch.setattr(search, "get_dynamodb_resource", fail)
    response = search.lambda_handler(event(query={"q": "test"}), SimpleNamespace(aws_request_id="aws-search"))
    body = json.loads(response["body"])
    assert response["statusCode"] == 500
    assert body == {"error": "Internal server error", "request_id": "aws-search"}
    assert "secret-search-error" not in response["body"]


def test_list_500_does_not_expose_exception(monkeypatch):
    def fail():
        raise RuntimeError("secret-list-error")

    monkeypatch.setattr(list_lambda, "get_dynamodb_resource", fail)
    response = list_lambda.lambda_handler(event("/api/whiskeys"), SimpleNamespace(aws_request_id="aws-list"))
    body = json.loads(response["body"])
    assert response["statusCode"] == 500
    assert body == {"error": "Internal server error", "request_id": "aws-list"}
    assert "secret-list-error" not in response["body"]


def test_service_uses_shared_japanese_normalization():
    instance = object.__new__(service_module.WhiskeySearchService)
    assert instance._normalize_text(" ボウモア ") == "ぼうもあ"
