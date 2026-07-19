import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from boto3.dynamodb.conditions import ConditionExpressionBuilder

from tests.lambda_module_loader import load_lambda_module


search = load_lambda_module("whiskeys_search_lambda_tests", "lambda/whiskeys-search/index.py")
list_lambda = load_lambda_module("whiskeys_list_lambda_tests", "lambda/whiskeys-list/index.py")
service_module = load_lambda_module(
    "whiskey_search_service_tests",
    "lambda/whiskeys-search/python/whiskey_search_service.py",
)
from whiskey_common import scan_utils
@pytest.fixture(autouse=True)
def environment(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://app.example")
    monkeypatch.setenv("WHISKEY_SEARCH_TABLE", "WhiskeySearch-test")
    monkeypatch.setenv("WHISKEYS_TABLE", "WhiskeySearch-test")
    monkeypatch.setenv("APP_STATE_TABLE", "AppState-test")
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("PUBLIC_SCAN_MAX_PAGES", "1")


def event(path="/api/whiskeys/search", query=None):
    return {
        "httpMethod": "GET",
        "path": path,
        "headers": {"origin": "https://app.example"},
        "queryStringParameters": query,
        "requestContext": {"requestId": "request-1"},
    }


def test_scan_helper_returns_token_at_page_limit_and_resumes():
    table = Mock()
    table.scan.side_effect = [
        {"Items": [{"id": "w1"}], "LastEvaluatedKey": {"id": "w1"}},
        {"Items": [{"id": "w2"}]},
    ]
    first, token = scan_utils.scan_all_pages(table, max_pages=1)
    assert first == [{"id": "w1"}]
    assert scan_utils.decode_next_token(token) == {"id": "w1"}
    second, final_token = scan_utils.scan_all_pages(
        table,
        max_pages=1,
        ExclusiveStartKey=scan_utils.decode_next_token(token),
    )
    assert second == [{"id": "w2"}]
    assert final_token is None
    assert table.scan.call_args_list[1].kwargs["ExclusiveStartKey"] == {"id": "w1"}


def test_search_uses_bounded_scan_and_returns_next_token(monkeypatch):
    table = Mock()
    table.scan.return_value = {
        "Items": [{"id": "w1", "name": "Hibiki"}],
        "LastEvaluatedKey": {"id": "w1"},
    }
    dynamodb = Mock()
    dynamodb.Table.return_value = table
    monkeypatch.setattr(search, "get_dynamodb_resource", lambda: dynamodb)
    monkeypatch.setattr(search, "consume_scan_budget", lambda *args, **kwargs: None)
    response = search.lambda_handler(
        event(query={"q": "Hibiki", "limit": "25"}),
        SimpleNamespace(aws_request_id="aws-1"),
    )
    body = json.loads(response["body"])
    assert response["statusCode"] == 200
    assert body["whiskeys"][0]["name"] == "Hibiki"
    assert scan_utils.decode_next_token(body["next_token"]) == {"id": "w1"}
    assert table.scan.call_args.kwargs["Limit"] == 25
    built = ConditionExpressionBuilder().build_expression(
        table.scan.call_args.kwargs["FilterExpression"]
    )
    attribute_names = set(built.attribute_name_placeholders.values())
    assert attribute_names == {"name", "normalized_name"}


def test_list_uses_bounded_scan_and_returns_next_token(monkeypatch):
    table = Mock()
    table.scan.return_value = {
        "Items": [{"id": "w1", "name": "Hibiki"}],
        "LastEvaluatedKey": {"id": "w1"},
    }
    dynamodb = Mock()
    dynamodb.Table.return_value = table
    monkeypatch.setattr(list_lambda, "get_dynamodb_resource", lambda: dynamodb)
    monkeypatch.setattr(list_lambda, "consume_scan_budget", lambda *args, **kwargs: None)
    response = list_lambda.lambda_handler(
        event("/api/whiskeys", {"limit": "50"}),
        SimpleNamespace(aws_request_id="aws-list"),
    )
    body = json.loads(response["body"])
    assert response["statusCode"] == 200
    assert body["count"] == 1
    assert scan_utils.decode_next_token(body["next_token"]) == {"id": "w1"}


def test_public_scan_budget_returns_429(monkeypatch):
    def exhausted(*args, **kwargs):
        raise search.ScanBudgetExceeded

    monkeypatch.setattr(search, "consume_scan_budget", exhausted)
    monkeypatch.setattr(search, "get_dynamodb_resource", Mock())
    response = search.lambda_handler(event(query={"q": "test"}), SimpleNamespace(aws_request_id="aws-1"))
    assert response["statusCode"] == 429


class RankingTable:
    def __init__(self, items):
        self.items = items

    def get_item(self, *, Key, **kwargs):
        item = self.items.get(Key["pk"])
        return {"Item": item} if item else {}


def ranking_resource(items):
    table = RankingTable(items)
    resource = Mock()
    resource.Table.return_value = table
    return resource


def test_ranking_reads_only_current_generation_pages(monkeypatch):
    meta = {
        "pk": search.RANKING_META_KEY,
        "generation_id": "g1",
        "page_count": 1,
        "total_items": 2,
        "cache_page_size": 100,
        "review_counter": 1,
        "whiskey_counter": 1,
    }
    items = {
        search.RANKING_META_KEY: meta,
        search._ranking_page_key("g1", 0): {
            "rankings": [{"id": "w2"}, {"id": "w1"}],
        },
    }
    monkeypatch.setattr(search, "get_dynamodb_resource", lambda: ranking_resource(items))
    response = search.lambda_handler(
        event("/api/whiskeys/ranking", {"page": "1", "limit": "1"}),
        SimpleNamespace(aws_request_id="rank-1"),
    )
    body = json.loads(response["body"])
    assert body["rankings"] == [{"id": "w2"}]
    assert body["pagination"]["has_next"] is True


def test_ranking_without_parameters_returns_legacy_bare_array(monkeypatch):
    items = {
        search.RANKING_META_KEY: {
            "generation_id": "g1",
            "page_count": 1,
            "page_sizes": [2],
            "total_items": 2,
            "cache_page_size": 100,
        },
        search._ranking_page_key("g1", 0): {
            "rankings": [{"id": "w2"}, {"id": "w1"}],
        },
    }
    monkeypatch.setattr(search, "get_dynamodb_resource", lambda: ranking_resource(items))

    response = search.lambda_handler(
        event("/api/whiskeys/ranking"),
        SimpleNamespace(aws_request_id="rank-legacy"),
    )

    assert json.loads(response["body"]) == [{"id": "w2"}, {"id": "w1"}]


@pytest.mark.parametrize(
    "meta",
    [
        None,
        {"generation_id": "g1", "invalidated_at": "2026-01-01T00:00:00Z"},
        {
            "generation_id": "g1",
            "dirty_since": (
                datetime.now(timezone.utc) - timedelta(minutes=46)
            ).isoformat().replace("+00:00", "Z"),
        },
    ],
)
def test_ranking_fail_closed_when_missing_invalidated_or_too_stale(monkeypatch, meta):
    items = {search.RANKING_META_KEY: meta} if meta else {}
    monkeypatch.setattr(search, "get_dynamodb_resource", lambda: ranking_resource(items))
    response = search.lambda_handler(
        event("/api/whiskeys/ranking"),
        SimpleNamespace(aws_request_id="rank-2"),
    )
    assert response["statusCode"] == 200
    assert json.loads(response["body"]) == {"status": "aggregating"}


def test_ranking_missing_generation_page_fails_closed(monkeypatch):
    items = {
        search.RANKING_META_KEY: {
            "generation_id": "g1",
            "total_items": 1,
            "cache_page_size": 100,
        }
    }
    monkeypatch.setattr(search, "get_dynamodb_resource", lambda: ranking_resource(items))
    response = search.lambda_handler(
        event("/api/whiskeys/ranking"),
        SimpleNamespace(aws_request_id="rank-3"),
    )
    assert json.loads(response["body"]) == {"status": "aggregating"}


def test_search_500_does_not_expose_exception(monkeypatch):
    monkeypatch.setattr(search, "get_dynamodb_resource", Mock(side_effect=RuntimeError("secret-search-error")))
    response = search.lambda_handler(event(query={"q": "test"}), SimpleNamespace(aws_request_id="aws-search"))
    assert response["statusCode"] == 500
    assert json.loads(response["body"]) == {
        "error": "Internal server error",
        "request_id": "aws-search",
    }
    assert "secret-search-error" not in response["body"]


def test_list_500_does_not_expose_exception(monkeypatch):
    monkeypatch.setattr(list_lambda, "get_dynamodb_resource", Mock(side_effect=RuntimeError("secret-list-error")))
    response = list_lambda.lambda_handler(event("/api/whiskeys"), SimpleNamespace(aws_request_id="aws-list"))
    assert response["statusCode"] == 500
    assert json.loads(response["body"]) == {
        "error": "Internal server error",
        "request_id": "aws-list",
    }
    assert "secret-list-error" not in response["body"]


def test_service_uses_shared_japanese_normalization():
    assert service_module.normalize_text(" ボウモア ") == "ぼうもあ"
