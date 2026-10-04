"""Read-only chat tools with real catalog and Drink Log storage."""

import boto3
import pytest
from moto import mock_aws

from tests.lambda_module_loader import load_lambda_module


tools = load_lambda_module("agent_chat_tools_tests", "lambda/agent-chat/tools.py")


@pytest.fixture
def directory(monkeypatch):
    for key in ("AWS_ENDPOINT_URL_DYNAMODB", "AWS_ENDPOINT_URL_S3", "AWS_ENDPOINT_URL"):
        monkeypatch.delenv(key, raising=False)
    for key, value in {"DRINKLOGS_TABLE": "DrinkLogs-test", "APP_STATE_TABLE": "AppState-test", "IMAGES_BUCKET": "images-test", "WHISKEY_SEARCH_TABLE": "WhiskeySearch-test"}.items():
        monkeypatch.setenv(key, value)
    with mock_aws():
        db = boto3.resource("dynamodb", region_name="ap-northeast-1")
        table = db.create_table(TableName="DrinkLogs-test", KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}, {"AttributeName": "user_id", "AttributeType": "S"}, {"AttributeName": "datetime", "AttributeType": "S"}],
            GlobalSecondaryIndexes=[{"IndexName": "UserDatetimeIndex", "KeySchema": [{"AttributeName": "user_id", "KeyType": "HASH"}, {"AttributeName": "datetime", "KeyType": "RANGE"}], "Projection": {"ProjectionType": "ALL"}}], BillingMode="PAY_PER_REQUEST")
        catalog = db.create_table(TableName="WhiskeySearch-test", KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}], AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}], BillingMode="PAY_PER_REQUEST")
        for user in ("alice", "bob"):
            for day in (1, 2):
                table.put_item(Item={"id": f"{user}-{day}", "user_id": user, "datetime": f"2026-10-0{day}T12:00:00Z", "brand_text": "アラン", "status": "complete", "store": {"name": "Bar"}, "notes": f"{user}の記録"})
        yield tools.ChatTools(db, boto3.client("s3", region_name="ap-northeast-1")), table, catalog


def test_recent_drink_logs_are_owned_and_model_cannot_override_principal(directory):
    service, _, _ = directory
    event = {"principal": {"user_id": "alice"}, "name": "get_drink_logs", "params": {"limit": 1}}
    result = service.handle(event)
    assert [r["id"] for r in result["results"]] == ["alice-2"]
    assert result["partial"] is True
    assert "user_id" not in result["results"][0]
    assert "error" in service.handle({**event, "params": {"user_id": "bob"}})


def test_catalog_search_reports_unsearched_data_instead_of_false_absence(directory, monkeypatch):
    service, _, catalog = directory
    monkeypatch.setenv("PUBLIC_SCAN_PAGE_SIZE", "1")
    for i in range(5):
        catalog.put_item(Item={"id": str(i), "name": "タリスカー" if i == 4 else "別の銘柄", "normalized_name": "talisker" if i == 4 else "other"})
    event = {"principal": {"user_id": "alice"}, "name": "search_whiskeys", "params": {"query": "タリスカー"}}
    assert service.handle(event) == {"results": [], "partial": True}
    monkeypatch.setenv("PUBLIC_SCAN_PAGE_SIZE", "2")
    result = service.handle(event)
    assert result["results"][0]["name"] == "タリスカー"
    assert result["partial"] is False


@pytest.mark.parametrize("params", [{"limit": True}, {"limit": 21}, {"limit": 0}, {"limit": "3"}])
def test_tool_validates_generated_limits_before_reading_logs(directory, params):
    service, _, _ = directory
    assert service.handle({"principal": {"user_id": "alice"}, "name": "get_drink_logs", "params": params}) == {"error": "Invalid tool input"}
