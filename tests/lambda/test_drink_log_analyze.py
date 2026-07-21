import io
import json
import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from PIL import Image

from tests.lambda_module_loader import load_lambda_module


analyze = load_lambda_module("drink_log_analyze_tests", "lambda/drink-log-analyze/index.py")
drink_logs = load_lambda_module("drink_logs_analysis_contract_tests", "lambda/drink-logs/index.py")


class TransactionCanceled(Exception):
    def __init__(self, reasons=None):
        self.response = {"CancellationReasons": reasons or []}
        super().__init__("transaction cancelled")


class RecordingClient:
    exceptions = SimpleNamespace(TransactionCanceledException=TransactionCanceled)

    def __init__(self):
        self.transactions = []

    def transact_write_items(self, **kwargs):
        self.transactions.append(kwargs["TransactItems"])


class AppStateTable:
    def __init__(self):
        self.items = {}

    def put_item(self, *, Item):
        self.items[Item["pk"]] = dict(Item)

    def get_item(self, *, Key, **kwargs):
        del kwargs
        item = self.items.get(Key["pk"])
        return {"Item": dict(item)} if item else {}


class WhiskeyTable:
    def __init__(self, match=True):
        self.match = match
        self.query_calls = []
        self.scan_calls = []

    def query(self, **kwargs):
        self.query_calls.append(kwargs)
        return {"Items": [{"id": "whiskey-1"}]} if self.match else {"Items": []}

    def scan(self, **kwargs):
        self.scan_calls.append(kwargs)
        return {"Items": []}


class FakeDynamoDB:
    def __init__(self, app=None, whiskeys=None):
        self.meta = SimpleNamespace(client=RecordingClient())
        self.app = app or AppStateTable()
        self.whiskeys = whiskeys or WhiskeyTable()

    def Table(self, name):
        if name == "AppState-test":
            return self.app
        if name == "WhiskeySearch-test":
            return self.whiskeys
        raise AssertionError(name)


class MemoryS3:
    def __init__(self, key, body, etag='"etag-1"'):
        self.key = key
        self.body = body
        self.etag = etag
        self.get_calls = []

    def head_object(self, *, Bucket, Key):
        assert Bucket == "images-test"
        assert Key == self.key
        return {
            "ContentLength": len(self.body),
            "ContentType": "image/png",
            "ETag": self.etag,
        }

    def get_object(self, **kwargs):
        self.get_calls.append(kwargs)
        assert kwargs["Bucket"] == "images-test"
        assert kwargs["Key"] == self.key
        if "Range" in kwargs:
            assert kwargs["Range"] == "bytes=0-15"
            return {"Body": io.BytesIO(self.body[:16])}
        assert kwargs["IfMatch"] == self.etag
        return {"Body": io.BytesIO(self.body)}


class Context:
    aws_request_id = "request-1"

    def __init__(self, remaining=28_000):
        self.remaining = remaining

    def get_remaining_time_in_millis(self):
        return self.remaining


class Bedrock:
    def __init__(self, texts):
        self.texts = list(texts)
        self.calls = []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        text = self.texts.pop(0)
        return {"output": {"message": {"content": [{"text": text}]}}}


@pytest.fixture(autouse=True)
def environment(monkeypatch):
    values = {
        "ENVIRONMENT": "dev",
        "APP_STATE_TABLE": "AppState-test",
        "WHISKEY_SEARCH_TABLE": "WhiskeySearch-test",
        "IMAGES_BUCKET": "images-test",
        "COGNITO_USER_POOL_ID": "ap-northeast-1_pool",
        "COGNITO_CLIENT_ID": "client-123",
        "AWS_REGION": "ap-northeast-1",
        "BEDROCK_MODEL_ID": "jp.amazon.nova-2-lite-v1:0",
        "BEDROCK_MODEL_ALLOWLIST": (
            "jp.amazon.nova-2-lite-v1:0,"
            "jp.anthropic.claude-haiku-4-5-20251001-v1:0"
        ),
        "ANALYZE_USER_DAILY_LIMIT": "20",
        "ANALYZE_GLOBAL_DAILY_LIMIT": "50",
        "ANALYZE_GLOBAL_MONTHLY_LIMIT": "1000",
        "IMAGE_MAX_BYTES": "1572864",
        "UPLOAD_MAX_BYTES": "3670016",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("MOCK_AI", raising=False)
    monkeypatch.delenv("MOCK_PLACES", raising=False)


def _png_bytes():
    image = Image.new("RGBA", (40, 20), (255, 0, 0, 128))
    output = io.BytesIO()
    image.save(output, format="PNG", pnginfo=None)
    return output.getvalue()


def _event(key):
    return {
        "httpMethod": "POST",
        "path": "/api/drink-logs/analyze",
        "body": json.dumps({"s3_key": key}),
        "requestContext": {
            "authorizer": {
                "claims": {"sub": "user-1", "aud": "client-123", "token_use": "id"}
            }
        },
    }


@pytest.mark.parametrize(
    "text",
    [
        '{"brand_candidates":[],"serving_style":"NEAT","glass_type":"tumbler"}',
        '```json\n{"brand_candidates":[],"serving_style":"NEAT","glass_type":"tumbler"}\n```',
    ],
)
def test_fenced_and_plain_json_are_accepted(monkeypatch, text):
    bedrock = Bedrock([text])
    monkeypatch.setattr(analyze, "_bedrock_client", lambda timeout: bedrock)
    result = analyze._invoke_model(
        "jp.amazon.nova-2-lite-v1:0", b"jpeg", Context(), analyze.time.monotonic()
    )
    assert result == {
        "brand_candidates": [],
        "serving_style": "NEAT",
        "glass_type": "tumbler",
    }
    assert bedrock.calls[0]["inferenceConfig"]["maxTokens"] == 512


def test_handler_normalizes_image_saves_contract_and_round_trips_to_create(monkeypatch):
    upload_uuid = "12345678-1234-4234-8234-123456789abc"
    key = f"tmp/user-1/{upload_uuid}.png"
    raw = _png_bytes()
    s3 = MemoryS3(key, raw)
    dynamodb = FakeDynamoDB()
    bedrock = Bedrock(
        [
            "```json\n"
            '{"brand_candidates":[{"name_ja":"アードベッグ","name_en":"Ardbeg",'
            '"confidence":0.91}],"serving_style":"highball","glass_type":"tumbler"}'
            "\n```"
        ]
    )
    monkeypatch.setattr(analyze, "get_dynamodb_resource", lambda: dynamodb)
    monkeypatch.setattr(analyze, "get_s3_client", lambda: s3)
    monkeypatch.setattr(analyze, "_bedrock_client", lambda timeout: bedrock)

    response = analyze.lambda_handler(_event(key), Context())
    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    analysis_id = f"ai-result:user-1:{upload_uuid}"
    assert body["analysis_id"] == analysis_id
    assert body["serving_style"] == "SODA"
    assert body["candidates"][0]["whiskey_id"] == "whiskey-1"

    sent_image = bedrock.calls[0]["messages"][0]["content"][0]["image"]["source"]["bytes"]
    assert sent_image.startswith(b"\xff\xd8\xff")
    assert sent_image != raw
    with Image.open(io.BytesIO(sent_image)) as normalized:
        assert normalized.mode == "RGB"
        assert not normalized.getexif()

    saved = dynamodb.app.items[analysis_id]
    assert saved["ETag"] == '"etag-1"'
    assert saved["user"] == "user-1"
    assert saved["ttl"] == saved["expires_at"]
    assert saved["candidates"][0]["confidence"] == Decimal("0.91")
    assert isinstance(saved["confidence"], Decimal)
    assert [len(transaction) for transaction in dynamodb.meta.client.transactions] == [1, 2]

    pending, consume = drink_logs._prepare_initial_record(
        dynamodb,
        s3,
        "AppState-test",
        "images-test",
        "user-1",
        analysis_id,
        upload_uuid,
        0,
    )
    assert pending["_completion"]["brand_text"] == "アードベッグ"
    assert pending["_completion"]["whiskey_id"] == "whiskey-1"
    assert consume["Delete"]["ExpressionAttributeValues"][":candidate"] == saved["candidates"][0]


def test_malformed_output_retries_and_consumes_each_global_attempt(monkeypatch):
    upload_uuid = "12345678-1234-4234-8234-123456789abc"
    key = f"tmp/user-1/{upload_uuid}.png"
    s3 = MemoryS3(key, _png_bytes())
    dynamodb = FakeDynamoDB(whiskeys=WhiskeyTable(match=False))
    bedrock = Bedrock(
        [
            "```json\nnot-json\n```",
            '{"brand_candidates":[],"serving_style":"NEAT","glass_type":"rocks"}',
        ]
    )
    monkeypatch.setattr(analyze, "get_dynamodb_resource", lambda: dynamodb)
    monkeypatch.setattr(analyze, "get_s3_client", lambda: s3)
    monkeypatch.setattr(analyze, "_bedrock_client", lambda timeout: bedrock)
    response = analyze.lambda_handler(_event(key), Context())
    assert response["statusCode"] == 200
    assert len(bedrock.calls) == 2
    assert [len(transaction) for transaction in dynamodb.meta.client.transactions] == [1, 2, 2]
    for transaction in dynamodb.meta.client.transactions[1:]:
        keys = [write["Update"]["Key"]["pk"] for write in transaction]
        assert all("#global" in key for key in keys)


def test_ownership_is_rejected_before_aws_calls(monkeypatch):
    key = f"tmp/other/{uuid.uuid4()}.jpg"
    monkeypatch.setattr(analyze, "get_dynamodb_resource", lambda: pytest.fail("must not create client"))
    response = analyze.lambda_handler(_event(key), Context())
    assert response["statusCode"] == 403


def test_invalid_model_allowlist_and_nonlocal_mock_are_startup_errors(monkeypatch):
    monkeypatch.setenv("BEDROCK_MODEL_ID", "global.forbidden")
    with pytest.raises(RuntimeError):
        analyze.lambda_handler(_event(f"tmp/user-1/{uuid.uuid4()}.jpg"), Context())
    monkeypatch.setenv("BEDROCK_MODEL_ID", "jp.amazon.nova-2-lite-v1:0")
    monkeypatch.setenv("MOCK_AI", "1")
    with pytest.raises(RuntimeError, match="local"):
        analyze.lambda_handler(_event(f"tmp/user-1/{uuid.uuid4()}.jpg"), Context())


def test_invalid_magic_bytes_are_rejected_before_bedrock(monkeypatch):
    key = f"tmp/user-1/{uuid.uuid4()}.jpg"
    s3 = MemoryS3(key, b"not-an-image")
    dynamodb = FakeDynamoDB()
    monkeypatch.setattr(analyze, "get_dynamodb_resource", lambda: dynamodb)
    monkeypatch.setattr(analyze, "get_s3_client", lambda: s3)
    monkeypatch.setattr(analyze, "_bedrock_client", lambda timeout: pytest.fail("must not invoke"))
    response = analyze.lambda_handler(_event(key), Context())
    assert response["statusCode"] == 400
    assert dynamodb.meta.client.transactions == []


def test_counter_write_failure_is_fail_closed(monkeypatch):
    key = f"tmp/user-1/{uuid.uuid4()}.png"
    s3 = MemoryS3(key, _png_bytes())
    dynamodb = FakeDynamoDB()

    def fail_write(**kwargs):
        del kwargs
        raise RuntimeError("DynamoDB unavailable")

    dynamodb.meta.client.transact_write_items = fail_write
    monkeypatch.setattr(analyze, "get_dynamodb_resource", lambda: dynamodb)
    monkeypatch.setattr(analyze, "get_s3_client", lambda: s3)
    monkeypatch.setattr(analyze, "_bedrock_client", lambda timeout: pytest.fail("must not invoke"))
    response = analyze.lambda_handler(_event(key), Context())
    assert response["statusCode"] == 500


def test_low_remaining_time_consumes_user_request_but_degrades_without_invocation(monkeypatch):
    key = f"tmp/user-1/{uuid.uuid4()}.png"
    dynamodb = FakeDynamoDB(whiskeys=WhiskeyTable(match=False))
    monkeypatch.setattr(analyze, "get_dynamodb_resource", lambda: dynamodb)
    monkeypatch.setattr(analyze, "get_s3_client", lambda: MemoryS3(key, _png_bytes()))
    monkeypatch.setattr(analyze, "_bedrock_client", lambda timeout: pytest.fail("must not invoke"))
    response = analyze.lambda_handler(_event(key), Context(remaining=1_000))
    assert response["statusCode"] == 200
    assert json.loads(response["body"])["candidates"] == []
    assert [len(transaction) for transaction in dynamodb.meta.client.transactions] == [1]


def test_monthly_analysis_limit_is_a_503_circuit_breaker():
    class MonthlyLimitClient(RecordingClient):
        def transact_write_items(self, **kwargs):
            del kwargs
            raise TransactionCanceled(
                [{"Code": "None"}, {"Code": "ConditionalCheckFailed"}]
            )

    dynamodb = FakeDynamoDB()
    dynamodb.meta.client = MonthlyLimitClient()
    with pytest.raises(analyze.BudgetExceeded) as exc:
        analyze._reserve_analysis_budget(
            dynamodb,
            "AppState-test",
            "user-1",
            user_request=False,
        )
    assert exc.value.status_code == 503
