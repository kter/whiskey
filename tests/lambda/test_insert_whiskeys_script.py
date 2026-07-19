from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tests.lambda_module_loader import load_lambda_module


script = load_lambda_module(
    "insert_whiskeys_script_tests",
    "scripts/insert_whiskeys_to_dynamodb.py",
)


def test_target_is_required():
    with pytest.raises(SystemExit):
        script.parse_args(["input.json"])
    args = script.parse_args(["input.json", "--target", "local"])
    assert args.target == "local"


def test_dev_target_rejects_wrong_sts_account(monkeypatch):
    session = Mock()
    session.client.return_value.get_caller_identity.return_value = {
        "Account": "000000000000",
        "Arn": "arn:aws:iam::000000000000:user/wrong",
    }
    monkeypatch.setattr(script.boto3, "Session", lambda **kwargs: session)
    with pytest.raises(ValueError, match=script.DEV_ACCOUNT_ID):
        script.create_dynamodb_resource("dev")


def test_bulk_writer_is_owned_by_script_and_revision_is_incremented():
    writer = Mock()
    manager = Mock()
    manager.__enter__ = Mock(return_value=writer)
    manager.__exit__ = Mock(return_value=False)
    table = Mock()
    table.batch_writer.return_value = manager
    items = [{"id": "w1"}, {"id": "w2"}]
    assert script.bulk_write_whiskeys(table, items) == 2
    assert writer.put_item.call_count == 2

    app_state = Mock()
    script.increment_whiskey_revision(app_state)
    counter_call, meta_call = [call.kwargs for call in app_state.update_item.call_args_list]
    assert counter_call["Key"] == {"pk": "whiskey-change-counter"}
    assert "dirty_since" not in counter_call["UpdateExpression"]
    assert counter_call["ExpressionAttributeValues"][":one"] == 1
    assert meta_call["Key"] == {"pk": "ranking-cache/meta"}
    assert "dirty_since = if_not_exists" in meta_call["UpdateExpression"]
