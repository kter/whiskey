import json
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
    monkeypatch.setenv("PUBLIC_SCAN_PAGE_SIZE", "250")


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
    assert table.scan.call_args.kwargs["Limit"] == 250
    built = ConditionExpressionBuilder().build_expression(
        table.scan.call_args.kwargs["FilterExpression"]
    )
    attribute_names = set(built.attribute_name_placeholders.values())
    assert attribute_names == {"name", "normalized_name"}


def search_service(table):
    dynamodb = Mock()
    dynamodb.Table.return_value = table
    return service_module.WhiskeySearchService(dynamodb)


def test_search_fills_result_from_a_later_scan_page():
    table = Mock()
    table.scan.side_effect = [
        {"Items": [], "LastEvaluatedKey": {"id": "before-match"}},
        {"Items": [{"id": "w1", "name": "Hibiki"}]},
    ]

    items, token = search_service(table).search_whiskeys("Hibiki", limit=20, max_pages=2)

    assert items == [{"id": "w1", "name": "Hibiki"}]
    assert token is None
    assert table.scan.call_args_list[1].kwargs["ExclusiveStartKey"] == {"id": "before-match"}


def test_search_truncation_token_resumes_without_duplicates_or_gaps():
    table = Mock()
    table.scan.side_effect = [
        {
            "Items": [
                {"id": "w1", "name": "Malt 1"},
                {"id": "w2", "name": "Malt 2"},
                {"id": "w3", "name": "Malt 3"},
            ],
            "LastEvaluatedKey": {"id": "scanned-past-w3"},
        },
        {
            "Items": [
                {"id": "w3", "name": "Malt 3"},
                {"id": "w4", "name": "Malt 4"},
            ],
        },
    ]
    service = search_service(table)

    first, token = service.search_whiskeys("Malt", limit=2, max_pages=1)
    second, final_token = service.search_whiskeys(
        "Malt",
        limit=2,
        next_token=token,
        max_pages=1,
    )

    assert [item["id"] for item in first + second] == ["w1", "w2", "w3", "w4"]
    assert scan_utils.decode_next_token(token) == {"id": "w2"}
    assert final_token is None
    assert table.scan.call_args_list[1].kwargs["ExclusiveStartKey"] == {"id": "w2"}


def test_search_returns_token_when_max_pages_reached_with_no_matches():
    table = Mock()
    table.scan.side_effect = [
        {"Items": [], "LastEvaluatedKey": {"id": "scanned-1"}},
        {"Items": [], "LastEvaluatedKey": {"id": "scanned-2"}},
    ]
    before_page = Mock()

    items, token = search_service(table).search_whiskeys(
        "missing",
        limit=20,
        max_pages=2,
        before_page=before_page,
    )

    assert items == []
    assert scan_utils.decode_next_token(token) == {"id": "scanned-2"}
    assert before_page.call_count == 2


def test_search_returns_no_token_at_end_of_scan():
    table = Mock()
    table.scan.return_value = {"Items": [{"id": "w1", "name": "Hibiki"}]}

    items, token = search_service(table).search_whiskeys("Hibiki", limit=20, max_pages=5)

    assert items == [{"id": "w1", "name": "Hibiki"}]
    assert token is None


def test_search_consumes_scan_budget_for_each_internal_page(monkeypatch):
    table = Mock()
    table.scan.side_effect = [
        {"Items": [], "LastEvaluatedKey": {"id": "scanned-1"}},
        {"Items": []},
    ]
    dynamodb = Mock()
    dynamodb.Table.return_value = table
    consume_scan_budget = Mock()
    monkeypatch.setenv("PUBLIC_SCAN_MAX_PAGES", "2")
    monkeypatch.setattr(search, "get_dynamodb_resource", lambda: dynamodb)
    monkeypatch.setattr(search, "consume_scan_budget", consume_scan_budget)

    response = search.lambda_handler(
        event(query={"q": "missing", "limit": "20"}),
        SimpleNamespace(aws_request_id="aws-budget"),
    )

    assert response["statusCode"] == 200
    assert consume_scan_budget.call_count == 2


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
