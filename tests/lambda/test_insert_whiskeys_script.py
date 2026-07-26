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


def test_bulk_writer_is_owned_by_script():
    writer = Mock()
    manager = Mock()
    manager.__enter__ = Mock(return_value=writer)
    manager.__exit__ = Mock(return_value=False)
    table = Mock()
    table.batch_writer.return_value = manager
    items = [{"id": "w1"}, {"id": "w2"}]
    assert script.bulk_write_whiskeys(table, items) == 2
    table.batch_writer.assert_called_once_with(overwrite_by_pkeys=["id"])
    assert writer.put_item.call_count == 2


def test_conversion_uses_deterministic_catalog_key_as_id():
    inserter = script.WhiskeyDatabaseInserter("local", dynamodb=Mock())
    whiskey = {
        "name": "The Macallan 12 Year Old Double Cask",
        "brand_key": "macallan",
        "expression_code": "double_cask",
        "age": 12,
        "cask": "Double Cask",
        "confidence": 1,
    }

    first = inserter.convert_to_db_format(whiskey)
    second = inserter.convert_to_db_format(whiskey)

    assert first["id"] == second["id"] == first["catalog_key"]
    assert first["catalog_schema_version"] == 2
    assert first["normalized_name"] == inserter.normalize_text(whiskey["name"])


def test_report_duplicates_checks_catalog_key_and_normalized_name():
    table = Mock()
    table.scan.return_value = {
        "Items": [
            {"id": "a", "catalog_key": "same-key", "normalized_name": "first", "name": "A"},
            {"id": "b", "catalog_key": "same-key", "normalized_name": "second", "name": "B"},
            {"id": "c", "catalog_key": "other-key", "normalized_name": "second", "name": "C"},
        ]
    }
    dynamodb = Mock()
    dynamodb.Table.return_value = table
    inserter = script.WhiskeyDatabaseInserter("local", dynamodb=dynamodb)

    report = inserter.report_existing_duplicates()

    assert [[record["id"] for record in group] for group in report["catalog_key"]] == [["a", "b"]]
    assert [[record["id"] for record in group] for group in report["normalized_name"]] == [
        ["b", "c"]
    ]
