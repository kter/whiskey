from decimal import Decimal
from unittest.mock import Mock

import pytest

from tests.lambda_module_loader import load_lambda_module


clients = load_lambda_module(
    "whiskey_common_clients_tests",
    "lambda/common/python/whiskey_common/clients.py",
)
from whiskey_common import responses, scan_utils


def test_cors_echoes_only_allowed_origin_and_varies(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://app.example,https://preview.example")
    headers = responses.get_cors_headers({"headers": {"origin": "https://preview.example"}}, private=True)
    assert headers["Access-Control-Allow-Origin"] == "https://preview.example"
    assert headers["Vary"] == "Origin"
    assert headers["Cache-Control"] == "private, no-store"

    rejected = responses.get_cors_headers({"headers": {"origin": "https://attacker.example"}})
    assert rejected["Access-Control-Allow-Origin"] == "https://app.example"


def test_response_serializes_decimal_and_sets_private_cache(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://app.example")
    response = responses.create_response(
        200,
        {"rating": Decimal("4.5")},
        event={"headers": {"origin": "https://app.example"}},
        private=True,
    )
    assert response["body"] == '{"rating": 4.5}'
    assert response["headers"]["Cache-Control"] == "private, no-store"

    response_with_headers = responses.create_response(
        200,
        {"rating": Decimal("4.5")},
        headers={"X-Test": "value"},
        private=True,
    )
    assert response_with_headers["headers"] == {
        "X-Test": "value",
        "Cache-Control": "private, no-store",
    }


def test_clients_use_service_specific_endpoints_and_bounded_config(monkeypatch):
    monkeypatch.setenv("AWS_ENDPOINT_URL", "http://must-not-be-used")
    monkeypatch.setenv("AWS_ENDPOINT_URL_DYNAMODB", "http://ddb.local")
    monkeypatch.setenv("AWS_ENDPOINT_URL_S3", "http://s3.local")
    monkeypatch.setenv("AWS_REGION", "ap-northeast-1")
    resource = Mock(return_value="ddb")
    client = Mock(return_value="s3")
    monkeypatch.setattr(clients.boto3, "resource", resource)
    monkeypatch.setattr(clients.boto3, "client", client)

    assert clients.get_dynamodb_resource() == "ddb"
    assert clients.get_s3_client() == "s3"
    ddb_kwargs = resource.call_args.kwargs
    s3_kwargs = client.call_args.kwargs
    assert ddb_kwargs["endpoint_url"] == "http://ddb.local"
    assert s3_kwargs["endpoint_url"] == "http://s3.local"
    assert ddb_kwargs["config"].connect_timeout == 3
    assert ddb_kwargs["config"].read_timeout == 10
    assert ddb_kwargs["config"].retries == {"mode": "standard", "total_max_attempts": 2}
    assert s3_kwargs["config"].s3["addressing_style"] == "path"


def test_scan_all_pages_and_continuation_token():
    table = Mock()
    table.scan.side_effect = [
        {"Items": [{"id": "1"}], "LastEvaluatedKey": {"id": "1"}},
        {"Items": [{"id": "2"}], "LastEvaluatedKey": {"id": "2"}},
    ]
    items, token = scan_utils.scan_all_pages(table, max_pages=2)
    assert items == [{"id": "1"}, {"id": "2"}]
    assert scan_utils.decode_next_token(token) == {"id": "2"}


def test_invalid_next_token_is_rejected():
    with pytest.raises(ValueError, match="Invalid next_token"):
        scan_utils.decode_next_token("not-a-token")
