import json
from io import StringIO
from unittest.mock import patch

from tests.lambda_module_loader import load_lambda_module


logger_module = load_lambda_module(
    "whiskey_common_logger_tests",
    "lambda/common/python/whiskey_common/logger.py",
)


def test_structured_logger_includes_context():
    logger = logger_module.LambdaLogger("reviews", correlation_id="request-1")
    entry = logger._create_log_entry(logger_module.LogLevel.INFO, "handled", count=2)
    assert entry["function"] == "reviews"
    assert entry["correlation_id"] == "request-1"
    assert entry["details"]["count"] == 2
    assert entry["timestamp"].endswith("Z")


def test_api_request_records_parameter_names_not_values():
    stream = StringIO()
    logger = logger_module.LambdaLogger("redaction-test")
    handler = logger.logger.handlers[0]
    original_stream = handler.stream
    handler.setStream(stream)
    try:
        logger.log_api_request(
            method="POST",
            path="/api/test",
            query_params={"lat": "35.0", "brand": "secret-brand", "limit": "10"},
            body={"store": "private-store", "notes": "private notes"},
        )
    finally:
        handler.setStream(original_stream)
    entry = json.loads(stream.getvalue())
    assert entry["details"]["query_params"] == ["brand", "lat", "limit"]
    assert entry["details"]["body"] == ["notes", "store"]
    serialized = json.dumps(entry)
    assert "secret-brand" not in serialized
    assert "private-store" not in serialized


def test_nested_sensitive_values_are_redacted():
    value = logger_module.redact({"safe": "yes", "email": "user@example.com", "nested": {"lng": 139}})
    assert value == {"safe": "yes", "email": "[REDACTED]", "nested": {"lng": "[REDACTED]"}}


def test_extract_correlation_id():
    assert logger_module.extract_correlation_id({"requestContext": {"requestId": "api-id"}}) == "api-id"
    assert logger_module.extract_correlation_id({"correlation_id": "direct-id"}) == "direct-id"
