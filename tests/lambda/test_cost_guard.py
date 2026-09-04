from datetime import datetime, timezone
from types import SimpleNamespace

import boto3
import pytest
from moto import mock_aws

from tests.lambda_module_loader import load_lambda_module


cost_guard = load_lambda_module(
    "cost_guard_tests",
    "lambda/common/python/whiskey_common/cost_guard.py",
)


class RecordingClient:
    exceptions = SimpleNamespace(TransactionCanceledException=RuntimeError)

    def __init__(self):
        self.transactions = []

    def transact_write_items(self, **kwargs):
        self.transactions.append(kwargs["TransactItems"])


class FakeDynamoDB:
    def __init__(self):
        self.meta = SimpleNamespace(client=RecordingClient())


def test_global_daily_scan_counter_is_atomic_and_returns_budget_error():
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="ap-northeast-1")
        dynamodb.create_table(
            TableName="AppState-test",
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        now = datetime(2026, 7, 19, tzinfo=timezone.utc)
        usage_budget = cost_guard.UsageBudget(dynamodb, "AppState-test")
        usage_budget.reserve_public_scan("search", 1, now=now)
        with pytest.raises(cost_guard.ScanBudgetExceeded):
            usage_budget.reserve_public_scan("search", 1, now=now)
        item = dynamodb.Table("AppState-test").get_item(
            Key={"pk": "scan-counter/search/2026-07-19"}
        )["Item"]
        assert item["count"] == 1
        assert item["ttl"] > int(now.timestamp())


def test_analysis_monthly_fallback_is_capped_at_three_hundred(monkeypatch):
    monkeypatch.delenv("ANALYZE_GLOBAL_MONTHLY_LIMIT", raising=False)
    dynamodb = FakeDynamoDB()

    cost_guard.UsageBudget(dynamodb, "AppState-test").reserve_analysis(
        "user-1",
        user_request=False,
        now=datetime(2026, 9, 4, tzinfo=timezone.utc),
    )

    monthly = dynamodb.meta.client.transactions[0][1]["Update"]
    assert monthly["Key"]["pk"] == "drinklog-counter#analyze#global-month#2026-09"
    assert monthly["ExpressionAttributeValues"][":largest_existing"] == 299
