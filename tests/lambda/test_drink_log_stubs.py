import json
from types import SimpleNamespace

from tests.lambda_module_loader import load_lambda_module


analyze = load_lambda_module("drink_log_analyze_stub_tests", "lambda/drink-log-analyze/index.py")
places = load_lambda_module("drink_log_places_stub_tests", "lambda/drink-log-analyze/places.py")


def test_http_handlers_are_common_response_501_stubs(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://example.test")
    event = {"headers": {"Origin": "https://example.test"}}
    context = SimpleNamespace(aws_request_id="request-1")

    for module in (analyze, places):
        response = module.lambda_handler(event, context)
        assert response["statusCode"] == 501
        assert response["headers"]["Cache-Control"] == "private, no-store"
        assert json.loads(response["body"]) == {"error": "Not Implemented"}
