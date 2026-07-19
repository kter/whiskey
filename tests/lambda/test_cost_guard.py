from datetime import datetime, timezone

import boto3
import pytest
from moto import mock_aws

from tests.lambda_module_loader import load_lambda_module


load_lambda_module("cost_guard_path_setup", "lambda/whiskeys-list/index.py")
from whiskey_common.cost_guard import ScanBudgetExceeded, consume_scan_budget


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
        consume_scan_budget(dynamodb, "AppState-test", "search", 1, now=now)
        with pytest.raises(ScanBudgetExceeded):
            consume_scan_budget(dynamodb, "AppState-test", "search", 1, now=now)
        item = dynamodb.Table("AppState-test").get_item(
            Key={"pk": "scan-counter/search/2026-07-19"}
        )["Item"]
        assert item["count"] == 1
        assert item["ttl"] > int(now.timestamp())
