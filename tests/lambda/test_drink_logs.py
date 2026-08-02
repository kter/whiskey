import io
import json
import struct
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws
from PIL import Image

from tests.lambda_module_loader import load_lambda_module


drink_logs = load_lambda_module("drink_logs_lambda_tests", "lambda/drink-logs/index.py")
reconciler = load_lambda_module("drink_logs_reconciler_tests", "lambda/drink-logs/reconciler.py")
images = load_lambda_module(
    "drink_logs_images_tests",
    "lambda/common/python/whiskey_common/images.py",
)
ROOT = Path(__file__).resolve().parents[2]


class TransactionCanceled(Exception):
    def __init__(self, reasons=None):
        self.response = {"CancellationReasons": reasons or []}
        super().__init__("transaction canceled")


class ConditionalFailed(Exception):
    pass


class RecordingClient:
    exceptions = SimpleNamespace(
        TransactionCanceledException=TransactionCanceled,
        ConditionalCheckFailedException=ConditionalFailed,
    )

    def __init__(self, transaction_hook=None):
        self.transactions = []
        self.transaction_hook = transaction_hook

    def transact_write_items(self, **kwargs):
        transaction = kwargs["TransactItems"]
        self.transactions.append(transaction)
        if self.transaction_hook:
            self.transaction_hook(transaction)


class StaticTable:
    def __init__(self, item=None, get_items=None, client=None, query_responses=None):
        self.item = item
        self.get_items = list(get_items or [])
        self.client = client or RecordingClient()
        self.meta = SimpleNamespace(client=self.client)
        self.query_responses = list(query_responses or [])
        self.get_calls = []
        self.query_calls = []

    def get_item(self, **kwargs):
        self.get_calls.append(kwargs)
        item = self.get_items.pop(0) if self.get_items else self.item
        return {"Item": dict(item)} if item is not None else {}

    def query(self, **kwargs):
        self.query_calls.append(kwargs)
        return self.query_responses.pop(0)


class FakeDynamoDB:
    def __init__(self, tables, client=None):
        self.tables = tables
        self.client = client or RecordingClient()
        self.meta = SimpleNamespace(client=self.client)

    def Table(self, name):
        return self.tables[name]


class PresignS3:
    def __init__(self):
        self.post_call = None
        self.url_calls = []

    def generate_presigned_post(self, **kwargs):
        self.post_call = kwargs
        return {"url": "https://upload.example", "fields": {"key": kwargs["Key"], **kwargs["Fields"]}}

    def generate_presigned_url(self, operation, **kwargs):
        self.url_calls.append((operation, kwargs))
        return f"https://image.example/{kwargs['Params']['Key']}"


def _client_error(code, operation="HeadObject"):
    return ClientError({"Error": {"Code": code, "Message": code}}, operation)


class MemoryS3(PresignS3):
    def __init__(self, objects=None):
        super().__init__()
        self.objects = dict(objects or {})

    def head_object(self, *, Bucket, Key):
        del Bucket
        if Key not in self.objects:
            raise _client_error("404")
        obj = self.objects[Key]
        return {
            "ETag": obj["etag"],
            "ContentType": obj["content_type"],
            "ContentLength": len(obj["body"]),
        }

    def get_object(self, *, Bucket, Key, IfMatch):
        del Bucket
        if Key not in self.objects:
            raise _client_error("NoSuchKey", "GetObject")
        obj = self.objects[Key]
        if obj["etag"] != IfMatch:
            raise _client_error("PreconditionFailed", "GetObject")
        return {"Body": io.BytesIO(obj["body"])}

    def put_object(self, *, Bucket, Key, Body, ContentType, CacheControl):
        del Bucket
        assert ContentType == "image/jpeg"
        assert CacheControl == "private, no-store"
        self.objects[Key] = {
            "body": Body,
            "content_type": ContentType,
            "etag": '"final"',
        }

    def delete_object(self, *, Bucket, Key):
        del Bucket
        self.objects.pop(Key, None)


class StateTable:
    def __init__(self, state, client):
        self.state = state
        self.meta = SimpleNamespace(client=client)

    def get_item(self, *, Key, **kwargs):
        del kwargs
        item = self.state.get(Key.get("id") or Key.get("pk"))
        return {"Item": dict(item)} if item else {}

    def update_item(self, **kwargs):
        item = self.state.get(kwargs["Key"]["id"])
        if not item:
            raise ConditionalFailed
        expression = kwargs["UpdateExpression"]
        values = kwargs.get("ExpressionAttributeValues", {})
        if expression.startswith("SET #status = :complete"):
            if item["status"] != "pending":
                raise ConditionalFailed
            completion = item["_completion"]
            item.update(completion)
            item.update(
                status="complete",
                s3_image_key=values[":final_key"],
                updated_at=values[":updated_at"],
            )
            for key in ("_completion", "content_type", "tmp_etag"):
                item.pop(key, None)
        elif expression == "REMOVE tmp_s3_key":
            item.pop("tmp_s3_key", None)
        elif ":deleting" in expression:
            if item["user_id"] != values[":caller"] or item["status"] not in {"complete", "deleting"}:
                raise ConditionalFailed
            item["status"] = "deleting"
            item.setdefault("delete_started_at", values[":started_at"])
        else:
            raise AssertionError(expression)
        return {"Attributes": dict(item)}


@pytest.fixture(autouse=True)
def environment(monkeypatch):
    values = {
        "DRINKLOGS_TABLE": "DrinkLogs-test",
        "APP_STATE_TABLE": "AppState-test",
        "IMAGES_BUCKET": "images-test",
        "COGNITO_USER_POOL_ID": "ap-northeast-1_pool",
        "COGNITO_CLIENT_ID": "client-123",
        "AWS_REGION": "ap-northeast-1",
        "ALLOWED_ORIGINS": "https://app.example",
        "IMAGE_MAX_BYTES": "1572864",
        "UPLOAD_MAX_BYTES": "3670016",
        "UPLOAD_USER_DAILY_LIMIT": "30",
        "UPLOAD_GLOBAL_DAILY_LIMIT": "100",
        "CREATE_USER_DAILY_LIMIT": "30",
        "CREATE_GLOBAL_DAILY_LIMIT": "100",
        "STORAGE_USER_LIMIT": "2000",
        "STORAGE_GLOBAL_LIMIT": "20000",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)


def _image_bytes(fmt, *, size=(80, 40), mode="RGB", color="red", exif=None):
    image = Image.new(mode, size, color)
    output = io.BytesIO()
    kwargs = {"format": fmt}
    if exif is not None:
        kwargs["exif"] = exif
    image.save(output, **kwargs)
    return output.getvalue()


def _bmp_header(width, height):
    row_bytes = ((width * 3 + 3) // 4) * 4
    pixel_bytes = row_bytes * height
    return (
        b"BM"
        + struct.pack("<IHHI", 54 + pixel_bytes, 0, 0, 54)
        + struct.pack("<IIIHHIIIIII", 40, width, height, 1, 24, 0, pixel_bytes, 2835, 2835, 0, 0)
    )


def test_sniff_format_supports_only_jpeg_png_and_webp():
    assert images.sniff_format(b"\xff\xd8\xffrest") == "jpeg"
    assert images.sniff_format(b"\x89PNG\r\n\x1a\nrest") == "png"
    assert images.sniff_format(b"RIFF\x04\x00\x00\x00WEBPrest") == "webp"
    assert images.sniff_format(b"\x00\x00\x00\x18ftypheic") is None


def test_normalize_applies_orientation_and_strips_metadata():
    exif = Image.Exif()
    exif[274] = 6
    exif[270] = "private metadata"
    raw = _image_bytes("JPEG", size=(80, 40), exif=exif)
    normalized = images.normalize_image(raw, max_bytes=1_572_864)
    with Image.open(io.BytesIO(normalized)) as result:
        assert result.size == (40, 80)
        assert result.mode == "RGB"
        assert not result.getexif()
        assert "icc_profile" not in result.info


def test_normalize_flattens_transparent_png_and_accepts_webp():
    png = _image_bytes("PNG", size=(10, 10), mode="RGBA", color=(255, 0, 0, 0))
    normalized = images.normalize_image(png, max_bytes=1_572_864)
    with Image.open(io.BytesIO(normalized)) as result:
        assert result.mode == "RGB"
        assert result.getpixel((0, 0)) == (255, 255, 255)
    webp = _image_bytes("WEBP", size=(20, 10))
    assert images.sniff_format(webp[:16]) == "webp"
    assert images.normalize_image(webp, max_bytes=1_572_864).startswith(b"\xff\xd8\xff")


@pytest.mark.parametrize("size", [(5000, 4001), (8001, 1)])
def test_normalize_rejects_oversized_headers_before_decode(size):
    with pytest.raises(images.ImageTooLargeError):
        images.normalize_image(_bmp_header(*size), max_bytes=1_572_864)


def test_normalize_reports_unreachable_byte_budget():
    with pytest.raises(images.ImageEncodeError):
        images.normalize_image(_image_bytes("PNG"), max_bytes=1)


def test_upload_url_consumes_atomic_limits_and_pins_form(monkeypatch):
    monkeypatch.setattr(drink_logs.uuid, "uuid4", lambda: uuid.UUID("11111111-1111-4111-8111-111111111111"))
    client = RecordingClient()
    dynamodb = FakeDynamoDB({}, client)
    s3 = PresignS3()
    result = drink_logs.create_upload_url(
        dynamodb, s3, "AppState-test", "images-test", "user-1", "image/png"
    )
    assert result["s3_key"] == "tmp/user-1/11111111-1111-4111-8111-111111111111.png"
    assert client.transactions[0][0]["Update"]["Key"]["pk"].startswith(
        "drinklog-counter#upload#user#user-1#"
    )
    assert client.transactions[0][1]["Update"]["Key"]["pk"].startswith(
        "drinklog-counter#upload#global#"
    )
    assert s3.post_call["Fields"] == {"Content-Type": "image/png"}
    assert ["content-length-range", 0, 3_670_016] in s3.post_call["Conditions"]
    assert s3.post_call["ExpiresIn"] == 120


def test_upload_validation_explicitly_rejects_heic():
    with pytest.raises(drink_logs.ValidationError) as exc:
        drink_logs.validate_upload_input({"content_type": "image/heic"})
    assert "HEIC" in exc.value.fields["content_type"]


def test_deterministic_id_is_owner_bound_and_stable_across_processes():
    upload_uuid = "12345678-1234-4234-8234-123456789abc"
    expected = drink_logs.derive_drink_log_id("user-1", upload_uuid)
    assert expected != drink_logs.derive_drink_log_id("user-2", upload_uuid)
    script = f"""
import sys
sys.path.insert(0, {str(ROOT / 'lambda' / 'common' / 'python')!r})
sys.path.insert(0, {str(ROOT / 'lambda' / 'drink-logs')!r})
import index
print(index.derive_drink_log_id('user-1', '{upload_uuid}'))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == expected


def _analysis_item(user_id, upload_uuid, body, content_type):
    return {
        "pk": f"ai-result:{user_id}:{upload_uuid}",
        "user": user_id,
        "s3_key": f"tmp/{user_id}/{upload_uuid}.{'png' if content_type == 'image/png' else 'webp'}",
        "ETag": '"etag-1"',
        "candidates": [
            {"brand_text": "Ardbeg", "whiskey_id": "whiskey-1", "confidence": Decimal("0.9")},
            {"brand_text": "Lagavulin", "confidence": Decimal("0.4")},
        ],
        "serving_style": "NEAT",
        "model_id": "model-1",
        "confidence": Decimal("0.8"),
        # analyze mirrors candidates[0] to the top level. Omitting it here made
        # the fixture unable to catch the 2nd-candidate cross-contamination bug.
        "whiskey_id": "whiskey-1",
        "expires_at": int(datetime.now(timezone.utc).timestamp()) + 600,
        "body": body,
    }


def _moto_create_dependencies(*, candidates=None):
    dynamodb = boto3.resource("dynamodb", region_name="ap-northeast-1")
    drinklogs = dynamodb.create_table(
        TableName="DrinkLogs-test",
        KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    app_state = dynamodb.create_table(
        TableName="AppState-test",
        KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    s3 = boto3.client("s3", region_name="ap-northeast-1")
    s3.create_bucket(
        Bucket="images-test",
        CreateBucketConfiguration={"LocationConstraint": "ap-northeast-1"},
    )
    upload_uuid = "12345678-1234-4234-8234-123456789abc"
    body = _image_bytes("PNG")
    analysis = _analysis_item("user-1", upload_uuid, body, "image/png")
    analysis.pop("body")
    if candidates is not None:
        analysis["candidates"] = candidates
        if not candidates:
            analysis.pop("confidence", None)
            analysis.pop("whiskey_id", None)
    response = s3.put_object(
        Bucket="images-test",
        Key=analysis["s3_key"],
        Body=body,
        ContentType="image/png",
    )
    analysis["ETag"] = response["ETag"]
    app_state.put_item(Item=analysis)
    return dynamodb, s3, drinklogs, app_state, analysis, upload_uuid


def test_create_validation_accepts_optional_candidate_and_reuses_update_rules():
    upload_uuid = "12345678-1234-4234-8234-123456789abc"
    validated = drink_logs.validate_create_input(
        {
            "analysis_id": upload_uuid,
            "brand_text": "自家製ハイボール",
            "store": {"name": "Bar 621", "place_id": "place-1"},
            "notes": "smoky",
            "rating": 4.5,
            "serving_style": "SODA",
        }
    )
    assert "candidate_index" not in validated
    assert validated["rating"] == Decimal("4.5")

    with pytest.raises(drink_logs.ValidationError) as exc:
        drink_logs.validate_create_input(
            {
                "analysis_id": upload_uuid,
                "candidate_index": True,
                "brand_text": "x" * 201,
                "store": {"name": "x" * 201},
                "notes": "x" * 2001,
                "rating": 0,
                "serving_style": "INVALID",
                "datetime": "2020-01-01T00:00:00",
            }
        )
    assert set(exc.value.fields) == {
        "brand_text",
        "candidate_index",
        "datetime",
        "notes",
        "rating",
        "serving_style",
        "store.name",
    }


def test_create_datetime_is_normalized_without_replacing_audit_timestamps(monkeypatch):
    fixed_now = datetime.now(timezone.utc).replace(microsecond=123456)
    captured_utc = fixed_now.replace(microsecond=0) - timedelta(hours=1)
    captured_with_offset = captured_utc.astimezone(
        timezone(timedelta(hours=9))
    ).isoformat()
    monkeypatch.setattr(drink_logs, "_utc_now", lambda: fixed_now)

    with mock_aws():
        dynamodb, s3, drinklogs, _app_state, analysis, _upload_uuid = (
            _moto_create_dependencies()
        )
        record, created = drink_logs.create_drink_log(
            dynamodb,
            s3,
            "DrinkLogs-test",
            "AppState-test",
            "images-test",
            "user-1",
            drink_logs.validate_create_input(
                {
                    "analysis_id": analysis["pk"],
                    "candidate_index": 0,
                    "datetime": captured_with_offset,
                }
            ),
        )

        expected_now = drink_logs._rfc3339(fixed_now)
        expected_captured = drink_logs._rfc3339(captured_utc)
        stored = drinklogs.get_item(Key={"id": record["id"]})["Item"]
        assert created is True
        assert record["datetime"] == expected_captured
        assert stored["datetime"] == expected_captured
        assert record["created_at"] == expected_now
        assert record["updated_at"] == expected_now


def test_create_datetime_normalizes_to_the_literal_sort_key_format(monkeypatch):
    """The GSI sort key is compared lexicographically, so the shape is the contract.

    Asserting against _rfc3339 would move with the implementation and let a
    format change through unnoticed.
    """
    monkeypatch.setattr(
        drink_logs,
        "_utc_now",
        lambda: datetime(2026, 8, 1, 12, 30, tzinfo=timezone.utc),
    )

    validated = drink_logs.validate_create_input(
        {
            "analysis_id": "12345678-1234-4234-8234-123456789abc",
            "datetime": "2026-08-01T12:00:00+09:00",
        }
    )

    assert validated["datetime"] == "2026-08-01T03:00:00.000Z"


def test_create_datetime_defaults_to_server_time(monkeypatch):
    fixed_now = datetime.now(timezone.utc).replace(microsecond=654321)
    monkeypatch.setattr(drink_logs, "_utc_now", lambda: fixed_now)

    with mock_aws():
        dynamodb, s3, _drinklogs, _app_state, analysis, _upload_uuid = (
            _moto_create_dependencies()
        )
        record, _created = drink_logs.create_drink_log(
            dynamodb,
            s3,
            "DrinkLogs-test",
            "AppState-test",
            "images-test",
            "user-1",
            drink_logs.validate_create_input(
                {"analysis_id": analysis["pk"], "candidate_index": 0}
            ),
        )

        assert record["datetime"] == drink_logs._rfc3339(fixed_now)


@pytest.mark.parametrize(
    "datetime_value",
    [
        "2026-08-01T21:30:00",
        "1999-12-31T23:59:59Z",
        "future",
    ],
)
def test_create_datetime_rejects_naive_and_out_of_range_values(
    monkeypatch, datetime_value
):
    fixed_now = datetime(2026, 8, 1, 12, 30, tzinfo=timezone.utc)
    monkeypatch.setattr(drink_logs, "_utc_now", lambda: fixed_now)
    if datetime_value == "future":
        datetime_value = drink_logs._rfc3339(fixed_now + timedelta(hours=1))

    with pytest.raises(drink_logs.ValidationError) as exc:
        drink_logs.validate_create_input(
            {
                "analysis_id": "12345678-1234-4234-8234-123456789abc",
                "datetime": datetime_value,
            }
        )

    assert "datetime" in exc.value.fields


def test_empty_candidates_can_create_complete_manual_brand():
    with mock_aws():
        dynamodb, s3, drinklogs, app_state, analysis, upload_uuid = (
            _moto_create_dependencies(candidates=[])
        )
        data = drink_logs.validate_create_input(
            {"analysis_id": analysis["pk"], "brand_text": "自家製ハイボール"}
        )
        record, created = drink_logs.create_drink_log(
            dynamodb,
            s3,
            "DrinkLogs-test",
            "AppState-test",
            "images-test",
            "user-1",
            data,
        )

        assert created is True
        assert record["status"] == "complete"
        assert record["brand_text"] == "自家製ハイボール"
        assert record["brand_source"] == "manual"
        assert "whiskey_id" not in record
        assert "datetime" in record
        assert app_state.get_item(Key={"pk": analysis["pk"]}).get("Item") is None
        assert drinklogs.get_item(Key={"id": record["id"]})["Item"]["status"] == "complete"


def test_candidate_brand_override_is_manual_and_analysis_is_consumed_once():
    with mock_aws():
        dynamodb, s3, _drinklogs, app_state, analysis, _upload_uuid = (
            _moto_create_dependencies()
        )
        data = drink_logs.validate_create_input(
            {
                "analysis_id": analysis["pk"],
                "candidate_index": 0,
                "brand_text": "Edited Bottle",
            }
        )
        record, created = drink_logs.create_drink_log(
            dynamodb,
            s3,
            "DrinkLogs-test",
            "AppState-test",
            "images-test",
            "user-1",
            data,
        )
        retried, retry_created = drink_logs.create_drink_log(
            dynamodb,
            s3,
            "DrinkLogs-test",
            "AppState-test",
            "images-test",
            "user-1",
            data,
        )

        assert created is True
        assert record["brand_text"] == "Edited Bottle"
        assert record["brand_source"] == "manual"
        assert "whiskey_id" not in record
        assert app_state.get_item(Key={"pk": analysis["pk"]}).get("Item") is None
        assert retried["id"] == record["id"]
        assert retry_created is False


@pytest.mark.parametrize(
    ("candidate_index", "brand_source", "whiskey_id"),
    [(0, "matched", "whiskey-1"), (1, "ai", None)],
)
def test_candidate_only_brand_derivation_regression(candidate_index, brand_source, whiskey_id):
    with mock_aws():
        dynamodb, s3, _drinklogs, _app_state, analysis, _upload_uuid = (
            _moto_create_dependencies()
        )
        record, created = drink_logs.create_drink_log(
            dynamodb,
            s3,
            "DrinkLogs-test",
            "AppState-test",
            "images-test",
            "user-1",
            drink_logs.validate_create_input(
                {"analysis_id": analysis["pk"], "candidate_index": candidate_index}
            ),
        )

        assert created is True
        assert record["brand_source"] == brand_source
        assert record.get("whiskey_id") == whiskey_id


def test_candidate_with_brand_metadata_can_be_consumed():
    candidate = {
        "brand_text": "厚岸 立春",
        "name_ja": "厚岸 立春",
        "name_en": "Akkeshi Risshun",
        "brand_ja": "厚岸",
        "brand_en": "Akkeshi",
        "brand_key": "akkeshi",
        "distillery_ja": "厚岸蒸溜所",
        "confidence": Decimal("0.91"),
        "match_source": "ai",
    }
    with mock_aws():
        dynamodb, s3, _drinklogs, _app_state, analysis, _upload_uuid = (
            _moto_create_dependencies(candidates=[candidate])
        )

        record, created = drink_logs.create_drink_log(
            dynamodb,
            s3,
            "DrinkLogs-test",
            "AppState-test",
            "images-test",
            "user-1",
            drink_logs.validate_create_input(
                {"analysis_id": analysis["pk"], "candidate_index": 0}
            ),
        )

        assert created is True
        assert record["brand_text"] == "厚岸 立春"
        assert record["brand_source"] == "ai"


def test_legacy_candidate_without_brand_metadata_can_still_be_consumed():
    legacy_candidate = {
        "brand_text": "Lagavulin",
        "confidence": Decimal("0.4"),
    }
    with mock_aws():
        dynamodb, s3, _drinklogs, _app_state, analysis, _upload_uuid = (
            _moto_create_dependencies(candidates=[legacy_candidate])
        )

        record, created = drink_logs.create_drink_log(
            dynamodb,
            s3,
            "DrinkLogs-test",
            "AppState-test",
            "images-test",
            "user-1",
            drink_logs.validate_create_input(
                {"analysis_id": analysis["pk"], "candidate_index": 0}
            ),
        )

        assert created is True
        assert record["brand_text"] == "Lagavulin"
        assert record["brand_source"] == "ai"


def test_create_confirmation_overrides_are_written_to_completed_record():
    with mock_aws():
        dynamodb, s3, _drinklogs, _app_state, analysis, _upload_uuid = (
            _moto_create_dependencies()
        )
        record, _created = drink_logs.create_drink_log(
            dynamodb,
            s3,
            "DrinkLogs-test",
            "AppState-test",
            "images-test",
            "user-1",
            drink_logs.validate_create_input(
                {
                    "analysis_id": analysis["pk"],
                    "candidate_index": 1,
                    "serving_style": "ROCKS",
                    "store": {"name": "Bar 621", "place_id": "place-621"},
                    "rating": 4.5,
                    "notes": "確認フォームで追記",
                }
            ),
        )

        assert record["serving_style"] == "ROCKS"
        assert record["store"] == {"name": "Bar 621", "place_id": "place-621"}
        assert record["rating"] == Decimal("4.5")
        assert record["notes"] == "確認フォームで追記"


def test_manual_consume_condition_keeps_image_binding_without_candidate_claim():
    upload_uuid = "12345678-1234-4234-8234-123456789abc"
    body = _image_bytes("PNG")
    result = _analysis_item("user-1", upload_uuid, body, "image/png")
    result["candidates"] = []
    result.pop("confidence")
    result.pop("whiskey_id", None)
    dynamodb = FakeDynamoDB({"AppState-test": StaticTable(item=result)})
    s3 = MemoryS3(
        {result["s3_key"]: {"body": body, "content_type": "image/png", "etag": '"etag-1"'}}
    )
    pending, consume = drink_logs._prepare_initial_record(
        dynamodb,
        s3,
        "AppState-test",
        "images-test",
        "user-1",
        result["pk"],
        upload_uuid,
        None,
        {"brand_text": "自家製ハイボール"},
    )

    delete = consume["Delete"]
    assert delete["ConditionExpression"] == (
        "#user = :user AND s3_key = :s3_key AND #etag = :etag AND expires_at > :now_epoch"
    )
    assert "#candidates" not in delete["ExpressionAttributeNames"]
    assert ":candidate" not in delete["ExpressionAttributeValues"]
    assert pending["_completion"]["brand_source"] == "manual"


@pytest.mark.parametrize("candidate_index", [None, 0])
def test_create_rejects_changed_image_for_manual_and_candidate_paths(candidate_index):
    with mock_aws():
        dynamodb, s3, _drinklogs, app_state, analysis, _upload_uuid = (
            _moto_create_dependencies()
        )
        s3.put_object(
            Bucket="images-test",
            Key=analysis["s3_key"],
            Body=_image_bytes("PNG", color="blue"),
            ContentType="image/png",
        )
        payload = {"analysis_id": analysis["pk"]}
        if candidate_index is None:
            payload["brand_text"] = "Manual"
        else:
            payload["candidate_index"] = candidate_index

        with pytest.raises(drink_logs.AnalysisConflict, match="changed after analysis"):
            drink_logs.create_drink_log(
                dynamodb,
                s3,
                "DrinkLogs-test",
                "AppState-test",
                "images-test",
                "user-1",
                drink_logs.validate_create_input(payload),
            )
        assert app_state.get_item(Key={"pk": analysis["pk"]}).get("Item") is not None


@pytest.mark.parametrize("candidate_index", [None, 0])
def test_create_rejects_expired_analysis_for_manual_and_candidate_paths(candidate_index):
    with mock_aws():
        dynamodb, s3, _drinklogs, app_state, analysis, _upload_uuid = (
            _moto_create_dependencies()
        )
        app_state.update_item(
            Key={"pk": analysis["pk"]},
            UpdateExpression="SET expires_at = :expired",
            ExpressionAttributeValues={
                ":expired": int(datetime.now(timezone.utc).timestamp()) - 1,
            },
        )
        payload = {"analysis_id": analysis["pk"]}
        if candidate_index is None:
            payload["brand_text"] = "Manual"
        else:
            payload["candidate_index"] = candidate_index

        with pytest.raises(drink_logs.AnalysisConflict, match="expired"):
            drink_logs.create_drink_log(
                dynamodb,
                s3,
                "DrinkLogs-test",
                "AppState-test",
                "images-test",
                "user-1",
                drink_logs.validate_create_input(payload),
            )


def test_candidate_consumption_rejects_candidate_tampering(monkeypatch):
    with mock_aws():
        dynamodb, s3, _drinklogs, app_state, analysis, _upload_uuid = (
            _moto_create_dependencies()
        )
        original_transaction = drink_logs._initial_create_transaction

        def tamper_then_transact(*args, **kwargs):
            app_state.update_item(
                Key={"pk": analysis["pk"]},
                UpdateExpression="SET candidates[0].brand_text = :brand",
                ExpressionAttributeValues={":brand": "Tampered"},
            )
            return original_transaction(*args, **kwargs)

        monkeypatch.setattr(drink_logs, "_initial_create_transaction", tamper_then_transact)
        with pytest.raises(drink_logs.AnalysisConflict, match="stale or already consumed"):
            drink_logs.create_drink_log(
                dynamodb,
                s3,
                "DrinkLogs-test",
                "AppState-test",
                "images-test",
                "user-1",
                drink_logs.validate_create_input(
                    {"analysis_id": analysis["pk"], "candidate_index": 0}
                ),
            )


def test_initial_transaction_binds_ai_etag_candidate_and_all_counters():
    upload_uuid = "12345678-1234-4234-8234-123456789abc"
    body = _image_bytes("PNG")
    result = _analysis_item("user-1", upload_uuid, body, "image/png")
    app_table = StaticTable(item=result)
    client = RecordingClient()
    dynamodb = FakeDynamoDB({"AppState-test": app_table}, client)
    s3 = MemoryS3(
        {result["s3_key"]: {"body": body, "content_type": "image/png", "etag": '"etag-1"'}}
    )
    pending, consume = drink_logs._prepare_initial_record(
        dynamodb,
        s3,
        "AppState-test",
        "images-test",
        "user-1",
        result["pk"],
        upload_uuid,
        1,
    )
    drink_logs._initial_create_transaction(
        dynamodb, "DrinkLogs-test", "AppState-test", pending, consume
    )
    transaction = client.transactions[0]
    assert len(transaction) == 6
    assert transaction[0]["Put"]["ConditionExpression"] == "attribute_not_exists(id)"
    assert [transaction[index]["Update"]["Key"]["pk"].split("#")[1] for index in range(1, 5)] == [
        "create",
        "create",
        "user",
        "global",
    ]
    delete = transaction[5]["Delete"]
    assert "#candidates[1] = :candidate" in delete["ConditionExpression"]
    assert "#etag = :etag" in delete["ConditionExpression"]
    assert delete["ExpressionAttributeValues"][":candidate"] == result["candidates"][1]
    assert pending["quota_allocated"] is True
    assert "ttl" not in pending


def test_response_loss_retry_returns_complete_without_consuming_quota_again():
    upload_uuid = "12345678-1234-4234-8234-123456789abc"
    record = {
        "id": drink_logs.derive_drink_log_id("user-1", upload_uuid),
        "user_id": "user-1",
        "status": "complete",
        "s3_image_key": f"logs/user-1/{upload_uuid}-attempt.jpg",
    }
    client = RecordingClient()
    dynamodb = FakeDynamoDB({"DrinkLogs-test": StaticTable(item=record)}, client)
    returned, created = drink_logs.create_drink_log(
        dynamodb,
        PresignS3(),
        "DrinkLogs-test",
        "AppState-test",
        "images-test",
        "user-1",
        {"analysis_id": upload_uuid, "candidate_index": 0},
    )
    assert returned == record
    assert created is False
    assert client.transactions == []


def test_transaction_loser_joins_winner_without_second_counter_charge(monkeypatch):
    upload_uuid = "12345678-1234-4234-8234-123456789abc"
    body = _image_bytes("PNG")
    analysis = _analysis_item("user-1", upload_uuid, body, "image/png")
    winner = {
        "id": drink_logs.derive_drink_log_id("user-1", upload_uuid),
        "user_id": "user-1",
        "status": "complete",
        "s3_image_key": f"logs/user-1/{upload_uuid}-winner.jpg",
    }

    def cancel(_transaction):
        raise TransactionCanceled([{"Code": "ConditionalCheckFailed"}])

    client = RecordingClient(cancel)
    records = StaticTable(get_items=[None, winner], client=client)
    dynamodb = FakeDynamoDB(
        {"DrinkLogs-test": records, "AppState-test": StaticTable(item=analysis)},
        client,
    )
    s3 = MemoryS3(
        {analysis["s3_key"]: {"body": body, "content_type": "image/png", "etag": '"etag-1"'}}
    )
    returned, created = drink_logs.create_drink_log(
        dynamodb,
        s3,
        "DrinkLogs-test",
        "AppState-test",
        "images-test",
        "user-1",
        {"analysis_id": upload_uuid, "candidate_index": 0},
    )
    assert returned == winner
    assert created is False
    assert len(client.transactions) == 1


def _disable_transaction_retry_delays(monkeypatch):
    retry = drink_logs.transact_write_with_retry

    def without_delays(client, transact_items, **kwargs):
        return retry(
            client,
            transact_items,
            sleep=lambda _delay: None,
            jitter=lambda: 1.0,
            **kwargs,
        )

    monkeypatch.setattr(drink_logs, "transact_write_with_retry", without_delays)


def _stub_initial_create(monkeypatch, upload_uuid):
    pending = {
        "id": drink_logs.derive_drink_log_id("user-1", upload_uuid),
        "user_id": "user-1",
        "status": "pending",
    }
    consume = {"Delete": {"TableName": "AppState-test", "Key": {"pk": "analysis"}}}
    monkeypatch.setattr(
        drink_logs,
        "_prepare_initial_record",
        lambda *_args, **_kwargs: (pending, consume),
    )
    return pending


def _post_event(path, body):
    return {
        "httpMethod": "POST",
        "path": path,
        "body": json.dumps(body),
        "headers": {"origin": "https://app.example"},
        "requestContext": {
            "requestId": "request-1",
            "authorizer": {
                "claims": {
                    "sub": "user-1",
                    "aud": "client-123",
                    "token_use": "id",
                }
            },
        },
    }


def test_create_retries_transaction_conflict_and_completes(monkeypatch):
    upload_uuid = "12345678-1234-4234-8234-123456789abc"
    attempts = 0

    def conflict_once(_transaction):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise TransactionCanceled([{"Code": "TransactionConflict"}] * 6)

    client = RecordingClient(conflict_once)
    records = StaticTable(item=None, client=client)
    dynamodb = FakeDynamoDB({"DrinkLogs-test": records}, client)
    pending = _stub_initial_create(monkeypatch, upload_uuid)
    monkeypatch.setattr(
        drink_logs,
        "_finish_pending_create",
        lambda *_args, **_kwargs: pending,
    )
    _disable_transaction_retry_delays(monkeypatch)

    record, created = drink_logs.create_drink_log(
        dynamodb,
        PresignS3(),
        "DrinkLogs-test",
        "AppState-test",
        "images-test",
        "user-1",
        {"analysis_id": upload_uuid, "candidate_index": 0},
    )

    assert record == pending
    assert created is True
    assert len(client.transactions) == 2


def test_exhausted_create_conflict_raises_transient_conflict(monkeypatch):
    upload_uuid = "12345678-1234-4234-8234-123456789abc"

    def always_conflict(_transaction):
        raise TransactionCanceled([{"Code": "TransactionConflict"}] * 6)

    client = RecordingClient(always_conflict)
    records = StaticTable(item=None, client=client)
    dynamodb = FakeDynamoDB({"DrinkLogs-test": records}, client)
    _stub_initial_create(monkeypatch, upload_uuid)
    _disable_transaction_retry_delays(monkeypatch)

    with pytest.raises(drink_logs.TransientConflict):
        drink_logs.create_drink_log(
            dynamodb,
            PresignS3(),
            "DrinkLogs-test",
            "AppState-test",
            "images-test",
            "user-1",
            {"analysis_id": upload_uuid, "candidate_index": 0},
        )

    assert len(client.transactions) == 4


def test_exhausted_create_conflict_returns_503_from_handler(monkeypatch):
    upload_uuid = "12345678-1234-4234-8234-123456789abc"

    def always_conflict(_transaction):
        raise TransactionCanceled([{"Code": "TransactionConflict"}] * 6)

    client = RecordingClient(always_conflict)
    dynamodb = FakeDynamoDB(
        {"DrinkLogs-test": StaticTable(item=None, client=client)},
        client,
    )
    _stub_initial_create(monkeypatch, upload_uuid)
    _disable_transaction_retry_delays(monkeypatch)
    monkeypatch.setattr(drink_logs, "get_dynamodb_resource", lambda: dynamodb)
    monkeypatch.setattr(drink_logs, "get_s3_client", PresignS3)

    response = drink_logs.lambda_handler(
        _post_event(
            "/api/drink-logs",
            {"analysis_id": upload_uuid, "candidate_index": 0},
        ),
        SimpleNamespace(aws_request_id="aws-1"),
    )

    assert response["statusCode"] == 503
    assert json.loads(response["body"]) == {
        "error": "書き込みが混み合っています。少し時間をおいて再試行してください。"
    }
    assert len(client.transactions) == 4


def test_upload_limit_stays_429_without_retry(monkeypatch):
    def conditional_failure(_transaction):
        raise TransactionCanceled([{"Code": "ConditionalCheckFailed"}, {"Code": "None"}])

    client = RecordingClient(conditional_failure)
    dynamodb = FakeDynamoDB(
        {"DrinkLogs-test": StaticTable(client=client)},
        client,
    )
    monkeypatch.setattr(drink_logs, "get_dynamodb_resource", lambda: dynamodb)
    monkeypatch.setattr(drink_logs, "get_s3_client", PresignS3)

    response = drink_logs.lambda_handler(
        _post_event("/api/drink-logs/upload-url", {"content_type": "image/jpeg"}),
        SimpleNamespace(aws_request_id="aws-1"),
    )

    assert response["statusCode"] == 429
    assert len(client.transactions) == 1


def test_create_limit_stays_429_without_retry(monkeypatch):
    upload_uuid = "12345678-1234-4234-8234-123456789abc"

    def conditional_failure(_transaction):
        raise TransactionCanceled(
            [
                {"Code": "None"},
                {"Code": "ConditionalCheckFailed"},
                {"Code": "None"},
                {"Code": "None"},
                {"Code": "None"},
                {"Code": "None"},
            ]
        )

    client = RecordingClient(conditional_failure)
    dynamodb = FakeDynamoDB(
        {"DrinkLogs-test": StaticTable(item=None, client=client)},
        client,
    )
    _stub_initial_create(monkeypatch, upload_uuid)
    monkeypatch.setattr(drink_logs, "get_dynamodb_resource", lambda: dynamodb)
    monkeypatch.setattr(drink_logs, "get_s3_client", PresignS3)

    response = drink_logs.lambda_handler(
        _post_event(
            "/api/drink-logs",
            {"analysis_id": upload_uuid, "candidate_index": 0},
        ),
        SimpleNamespace(aws_request_id="aws-1"),
    )

    assert response["statusCode"] == 429
    assert len(client.transactions) == 1


def test_mixed_reasons_prefer_the_limit_over_the_conflict(monkeypatch):
    """A real limit must win over a co-occurring conflict: 429, never 503."""
    upload_uuid = "12345678-1234-4234-8234-123456789abc"

    def mixed_failure(_transaction):
        raise TransactionCanceled(
            [
                {"Code": "TransactionConflict"},
                {"Code": "None"},
                {"Code": "ConditionalCheckFailed"},
                {"Code": "None"},
                {"Code": "None"},
                {"Code": "None"},
            ]
        )

    client = RecordingClient(mixed_failure)
    dynamodb = FakeDynamoDB(
        {"DrinkLogs-test": StaticTable(item=None, client=client)},
        client,
    )
    _stub_initial_create(monkeypatch, upload_uuid)
    monkeypatch.setattr(drink_logs, "get_dynamodb_resource", lambda: dynamodb)
    monkeypatch.setattr(drink_logs, "get_s3_client", PresignS3)

    response = drink_logs.lambda_handler(
        _post_event(
            "/api/drink-logs",
            {"analysis_id": upload_uuid, "candidate_index": 0},
        ),
        SimpleNamespace(aws_request_id="aws-1"),
    )

    assert response["statusCode"] == 429
    assert len(client.transactions) == 1


def test_upload_conflict_returns_503_instead_of_false_429(monkeypatch):
    def always_conflict(_transaction):
        raise TransactionCanceled(
            [{"Code": "TransactionConflict"}, {"Code": "None"}]
        )

    client = RecordingClient(always_conflict)
    dynamodb = FakeDynamoDB(
        {"DrinkLogs-test": StaticTable(client=client)},
        client,
    )
    _disable_transaction_retry_delays(monkeypatch)
    monkeypatch.setattr(drink_logs, "get_dynamodb_resource", lambda: dynamodb)
    monkeypatch.setattr(drink_logs, "get_s3_client", PresignS3)

    response = drink_logs.lambda_handler(
        _post_event("/api/drink-logs/upload-url", {"content_type": "image/jpeg"}),
        SimpleNamespace(aws_request_id="aws-1"),
    )

    assert response["statusCode"] == 503
    assert len(client.transactions) == 4


@pytest.mark.parametrize(
    ("fmt", "content_type", "extension"),
    [("PNG", "image/png", "png"), ("WEBP", "image/webp", "webp")],
)
def test_png_and_webp_finish_get_delete_flow(fmt, content_type, extension):
    upload_uuid = "12345678-1234-4234-8234-123456789abc"
    tmp_key = f"tmp/user-1/{upload_uuid}.{extension}"
    record_id = drink_logs.derive_drink_log_id("user-1", upload_uuid)
    state = {
        record_id: {
            "id": record_id,
            "user_id": "user-1",
            "status": "pending",
            "datetime": "2026-07-21T00:00:00Z",
            "tmp_s3_key": tmp_key,
            "tmp_etag": '"etag-1"',
            "content_type": content_type,
            "quota_allocated": True,
            "_completion": {
                "brand_text": "Ardbeg",
                "brand_source": "ai",
                "serving_style": "NEAT",
                "store": {"name": ""},
                "ai": {"model_id": "model-1", "confidence": Decimal("0.8")},
            },
            "created_at": "2026-07-21T00:00:00Z",
            "updated_at": "2026-07-21T00:00:00Z",
        }
    }

    def transact(transaction):
        if transaction[0].get("Delete"):
            state.pop(record_id, None)

    client = RecordingClient(transact)
    table = StateTable(state, client)
    dynamodb = FakeDynamoDB({"DrinkLogs-test": table}, client)
    s3 = MemoryS3(
        {tmp_key: {"body": _image_bytes(fmt), "content_type": content_type, "etag": '"etag-1"'}}
    )
    completed = drink_logs._finish_pending_create(
        dynamodb,
        s3,
        "DrinkLogs-test",
        "AppState-test",
        "images-test",
        dict(state[record_id]),
    )
    assert completed["status"] == "complete"
    assert completed["s3_image_key"].startswith(f"logs/user-1/{upload_uuid}-")
    assert tmp_key not in s3.objects
    assert s3.objects[completed["s3_image_key"]]["body"].startswith(b"\xff\xd8\xff")

    detail = drink_logs.get_owned_drink_log(table, s3, "images-test", "user-1", record_id)
    assert detail["image_url"].startswith("https://image.example/logs/user-1/")
    # Internal bucket-key structure and reconciliation bookkeeping must not leak
    # into API responses; clients only ever see the presigned image_url.
    for internal in ("s3_image_key", "tmp_s3_key", "quota_allocated", "delete_started_at"):
        assert internal not in detail
    assert drink_logs.delete_drink_log(
        dynamodb,
        s3,
        "DrinkLogs-test",
        "AppState-test",
        "images-test",
        "user-1",
        record_id,
    )
    assert record_id not in state
    assert completed["s3_image_key"] not in s3.objects


def test_timeline_fills_across_filtered_empty_pages_and_never_signs_pending():
    complete = {
        "id": "complete",
        "user_id": "user-1",
        "status": "complete",
        "datetime": "2026-07-21T00:00:00Z",
        "s3_image_key": "logs/user-1/image.jpg",
    }
    pending = {
        "id": "pending",
        "user_id": "user-1",
        "status": "pending",
        "datetime": "2026-07-20T00:00:00Z",
        "s3_image_key": "tmp/user-1/image.png",
    }
    table = StaticTable(
        query_responses=[
            {"Items": [], "LastEvaluatedKey": {"id": "cursor-1"}},
            {"Items": [pending, complete]},
        ]
    )
    dynamodb = FakeDynamoDB({"DrinkLogs-test": table})
    s3 = PresignS3()
    results, token = drink_logs.get_timeline(
        dynamodb,
        s3,
        "DrinkLogs-test",
        "images-test",
        "user-1",
        2,
        None,
        {"store": "Bar", "place_id": "place-1"},
    )
    assert [item["id"] for item in results] == ["complete"]
    assert token is None
    assert len(table.query_calls) == 2
    assert table.query_calls[1]["ExclusiveStartKey"] == {"id": "cursor-1"}
    assert len(s3.url_calls) == 1


def test_update_is_whitelisted_and_owner_status_are_atomic():
    with pytest.raises(drink_logs.ValidationError) as exc:
        drink_logs.validate_update_input({"id": "replacement", "s3_image_key": "evil"})
    assert set(exc.value.fields) == {"id", "s3_image_key"}

    calls = []

    class UpdateTable:
        meta = SimpleNamespace(client=RecordingClient())

        def update_item(self, **kwargs):
            calls.append(kwargs)
            return {"Attributes": {"id": "log-1", "status": "complete"}}

    result = drink_logs.update_drink_log(
        UpdateTable(),
        "user-1",
        "log-1",
        drink_logs.validate_update_input({"store": {"name": "Edited"}}),
    )
    assert result["id"] == "log-1"
    assert calls[0]["ConditionExpression"] == "#owner = :caller AND #status = :complete"
    assert "#store.#name = :store_name" in calls[0]["UpdateExpression"]
    assert "#store.#place_id" not in calls[0]["UpdateExpression"]


def test_put_rejects_datetime_as_an_immutable_field(monkeypatch):
    event = _post_event(
        "/api/drink-logs/log-1",
        {"datetime": "2026-08-01T12:30:00Z"},
    )
    event.update(
        httpMethod="PUT",
        pathParameters={"id": "log-1"},
    )
    dynamodb = FakeDynamoDB({"DrinkLogs-test": StaticTable()})
    monkeypatch.setattr(drink_logs, "get_dynamodb_resource", lambda: dynamodb)
    monkeypatch.setattr(drink_logs, "get_s3_client", PresignS3)

    response = drink_logs.lambda_handler(
        event, SimpleNamespace(aws_request_id="aws-request-1")
    )

    assert response["statusCode"] == 400
    assert json.loads(response["body"])["fields"] == {
        "datetime": "Field is not accepted"
    }


def test_batch_get_retries_unprocessed_keys_and_fails_closed():
    class BatchDynamo:
        def __init__(self, always=False):
            self.calls = 0
            self.always = always

        def batch_get_item(self, **kwargs):
            self.calls += 1
            request = kwargs["RequestItems"]
            if self.always or self.calls == 1:
                return {"Responses": {"DrinkLogs-test": []}, "UnprocessedKeys": request}
            return {
                "Responses": {"DrinkLogs-test": [{"id": "log-1"}]},
                "UnprocessedKeys": {},
            }

    retried = BatchDynamo()
    assert reconciler._batch_get_records(retried, "DrinkLogs-test", ["log-1"]) == {
        "log-1": {"id": "log-1"}
    }
    assert retried.calls == 2
    with pytest.raises(RuntimeError, match="remained unprocessed"):
        reconciler._batch_get_records(BatchDynamo(always=True), "DrinkLogs-test", ["log-1"])


def test_reconciler_never_treats_unconfirmed_s3_read_as_deleted():
    class FailingS3:
        def __init__(self):
            self.deleted = []

        def delete_object(self, **kwargs):
            self.deleted.append(kwargs["Key"])

        def head_object(self, **kwargs):
            raise _client_error("InternalError")

    s3 = FailingS3()
    with pytest.raises(ClientError):
        reconciler._delete_and_confirm(s3, "images-test", "logs/user-1/image.jpg")
    assert s3.deleted == ["logs/user-1/image.jpg"]


def test_reconciler_age_checks_fail_closed_on_unknown_timestamps():
    cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
    assert not reconciler._record_is_old({"updated_at": "not-a-time"}, cutoff)
    assert not reconciler._object_is_old({"LastModified": datetime.now()}, cutoff)


def test_reconciler_all_phases_converge_and_second_run_is_idempotent():
    old = datetime.now(timezone.utc) - timedelta(hours=72)
    old_text = old.isoformat().replace("+00:00", "Z")
    winner_uuid = "11111111-1111-4111-8111-111111111111"
    orphan_uuid = "22222222-2222-4222-8222-222222222222"
    deleting_uuid = "33333333-3333-4333-8333-333333333333"
    pending_uuid = "44444444-4444-4444-8444-444444444444"
    residual_uuid = "55555555-5555-4555-8555-555555555555"
    winner_id = drink_logs.derive_drink_log_id("user-1", winner_uuid)
    deleting_id = drink_logs.derive_drink_log_id("user-1", deleting_uuid)
    pending_id = drink_logs.derive_drink_log_id("user-1", pending_uuid)
    residual_id = drink_logs.derive_drink_log_id("user-1", residual_uuid)
    winner_key = f"logs/user-1/{winner_uuid}-aaaaaaaa.jpg"
    loser_key = f"logs/user-1/{winner_uuid}-bbbbbbbb.jpg"
    orphan_key = f"logs/user-1/{orphan_uuid}-cccccccc.jpg"
    deleting_key = f"logs/user-1/{deleting_uuid}-dddddddd.jpg"
    pending_tmp = f"tmp/user-1/{pending_uuid}.png"
    residual_tmp = f"tmp/user-1/{residual_uuid}.png"
    unreferenced_tmp = "tmp/user-1/66666666-6666-4666-8666-666666666666.png"
    state = {
        winner_id: {
            "id": winner_id,
            "user_id": "user-1",
            "status": "complete",
            "s3_image_key": winner_key,
            "quota_allocated": True,
            "updated_at": old_text,
        },
        deleting_id: {
            "id": deleting_id,
            "user_id": "user-1",
            "status": "deleting",
            "s3_image_key": deleting_key,
            "quota_allocated": True,
            "delete_started_at": old_text,
            "updated_at": old_text,
        },
        pending_id: {
            "id": pending_id,
            "user_id": "user-1",
            "status": "pending",
            "tmp_s3_key": pending_tmp,
            "quota_allocated": True,
            "updated_at": old_text,
        },
        residual_id: {
            "id": residual_id,
            "user_id": "user-1",
            "status": "complete",
            "s3_image_key": f"logs/user-1/{residual_uuid}-winner.jpg",
            "tmp_s3_key": residual_tmp,
            "quota_allocated": True,
            "updated_at": old_text,
        },
    }
    decremented = []

    class ReconcileClient(RecordingClient):
        def transact_write_items(self, **kwargs):
            transaction = kwargs["TransactItems"]
            self.transactions.append(transaction)
            delete = transaction[0]["Delete"]
            record_id = delete["Key"]["id"]
            item = state.get(record_id)
            if not item or item.get("status") != "deleting":
                raise TransactionCanceled([{"Code": "ConditionalCheckFailed"}])
            state.pop(record_id)
            decremented.extend(
                part["Update"]["Key"]["pk"]
                for part in transaction[1:]
            )

    client = ReconcileClient()

    class ReconcileTable:
        meta = SimpleNamespace(client=client)

        def get_item(self, *, Key, **kwargs):
            del kwargs
            item = state.get(Key["id"])
            return {"Item": dict(item)} if item else {}

        def scan(self, **kwargs):
            values = kwargs.get("ExpressionAttributeValues", {})
            items = list(state.values())
            if ":deleting" in values:
                items = [item for item in items if item.get("status") == "deleting"]
            elif ":pending" in values:
                items = [item for item in items if item.get("status") == "pending"]
            elif ":complete" in values:
                items = [
                    item
                    for item in items
                    if item.get("status") == "complete" and item.get("tmp_s3_key")
                ]
            return {"Items": [dict(item) for item in items]}

        def update_item(self, **kwargs):
            item = state.get(kwargs["Key"]["id"])
            if not item:
                raise ConditionalFailed
            if kwargs["UpdateExpression"] == "SET #status = :deleting":
                if item.get("status") != "pending":
                    raise ConditionalFailed
                item["status"] = "deleting"
                return {"Attributes": dict(item)}
            if kwargs["UpdateExpression"] == "REMOVE tmp_s3_key":
                item.pop("tmp_s3_key", None)
                return {}
            raise AssertionError(kwargs["UpdateExpression"])

        def put_item(self, *, Item, ConditionExpression):
            assert ConditionExpression == "attribute_not_exists(id)"
            if Item["id"] in state:
                raise ConditionalFailed
            state[Item["id"]] = dict(Item)

    table = ReconcileTable()

    class ReconcileDynamo:
        meta = SimpleNamespace(client=client)

        def Table(self, name):
            assert name == "DrinkLogs-test"
            return table

        def batch_get_item(self, **kwargs):
            keys = kwargs["RequestItems"]["DrinkLogs-test"]["Keys"]
            return {
                "Responses": {
                    "DrinkLogs-test": [dict(state[key["id"]]) for key in keys if key["id"] in state]
                },
                "UnprocessedKeys": {},
            }

    class ObjectPaginator:
        def __init__(self, owner):
            self.owner = owner

        def paginate(self, *, Bucket, Prefix):
            del Bucket
            yield {
                "Contents": [
                    {"Key": key, "LastModified": value["last_modified"]}
                    for key, value in self.owner.objects.items()
                    if key.startswith(Prefix)
                ]
            }

    class ReconcileS3(MemoryS3):
        def get_paginator(self, operation):
            assert operation == "list_objects_v2"
            return ObjectPaginator(self)

    object_keys = [
        winner_key,
        loser_key,
        orphan_key,
        deleting_key,
        pending_tmp,
        residual_tmp,
        unreferenced_tmp,
    ]
    s3 = ReconcileS3(
        {
            key: {
                "body": b"image",
                "content_type": "image/jpeg",
                "etag": '"etag"',
                "last_modified": old,
            }
            for key in object_keys
        }
    )
    dynamodb = ReconcileDynamo()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=48)

    first = {
        "logs_deleted": reconciler.reconcile_log_objects(
            dynamodb, s3, "DrinkLogs-test", "images-test", cutoff
        ),
        "deleting_completed": reconciler.reconcile_deleting_records(
            dynamodb, s3, "DrinkLogs-test", "AppState-test", "images-test", cutoff
        ),
        "pending_completed": reconciler.reconcile_pending_records(
            dynamodb, s3, "DrinkLogs-test", "AppState-test", "images-test", cutoff
        ),
        "tmp_deleted": reconciler.reconcile_tmp_objects(
            dynamodb, s3, "DrinkLogs-test", "images-test", cutoff
        ),
        "complete_tmp_cleaned": reconciler.reconcile_complete_tmp_references(
            dynamodb, s3, "DrinkLogs-test", "images-test", cutoff
        ),
    }
    assert first == {
        "logs_deleted": 3,
        "deleting_completed": 2,
        "pending_completed": 1,
        "tmp_deleted": 2,
        "complete_tmp_cleaned": 1,
    }
    assert set(state) == {winner_id, residual_id}
    assert residual_tmp not in state[residual_id]
    assert set(s3.objects) == {winner_key}
    assert decremented.count("drinklog-quota#global") == 2

    second = sum(
        (
            reconciler.reconcile_log_objects(
                dynamodb, s3, "DrinkLogs-test", "images-test", cutoff
            ),
            reconciler.reconcile_deleting_records(
                dynamodb, s3, "DrinkLogs-test", "AppState-test", "images-test", cutoff
            ),
            reconciler.reconcile_pending_records(
                dynamodb, s3, "DrinkLogs-test", "AppState-test", "images-test", cutoff
            ),
            reconciler.reconcile_tmp_objects(
                dynamodb, s3, "DrinkLogs-test", "images-test", cutoff
            ),
            reconciler.reconcile_complete_tmp_references(
                dynamodb, s3, "DrinkLogs-test", "images-test", cutoff
            ),
        )
    )
    assert second == 0


def test_handler_revalidates_authorizer_audience_and_token_use(monkeypatch):
    event = {
        "httpMethod": "GET",
        "path": "/api/drink-logs",
        "headers": {"origin": "https://app.example"},
        "requestContext": {
            "requestId": "request-1",
            "authorizer": {
                "claims": {"sub": "user-1", "aud": "wrong-client", "token_use": "access"}
            },
        },
    }
    response = drink_logs.lambda_handler(event, SimpleNamespace(aws_request_id="aws-1"))
    assert response["statusCode"] == 401
    assert response["headers"]["Cache-Control"] == "private, no-store"
    assert json.loads(response["body"])["error"] == "Authentication required"


def test_manual_brand_edit_clears_the_matched_whiskey_id():
    """Editing brand_text by hand must drop the previously matched whiskey_id.

    The create path (_completion_from_analysis) already pops it. Leaving it on
    update means the record shows the corrected name while still pointing at a
    different product -- e.g. a log corrected to アラン 10年 that still links to
    カリラ 12年.
    """
    calls = []

    class UpdateTable:
        meta = SimpleNamespace(client=RecordingClient())

        def update_item(self, **kwargs):
            calls.append(kwargs)
            return {"Attributes": {"id": "log-1", "status": "complete"}}

    drink_logs.update_drink_log(
        UpdateTable(),
        "user-1",
        "log-1",
        drink_logs.validate_update_input({"brand_text": "アラン 10年"}),
    )

    expression = calls[0]["UpdateExpression"]
    assert "#brand_source = :manual" in expression
    assert "REMOVE" in expression
    assert "#whiskey_id" in expression.split("REMOVE", 1)[1]
    assert calls[0]["ExpressionAttributeNames"]["#whiskey_id"] == "whiskey_id"


def test_non_brand_edit_leaves_the_whiskey_id_alone():
    """Only a brand correction invalidates the match -- notes must not."""
    calls = []

    class UpdateTable:
        meta = SimpleNamespace(client=RecordingClient())

        def update_item(self, **kwargs):
            calls.append(kwargs)
            return {"Attributes": {"id": "log-1", "status": "complete"}}

    drink_logs.update_drink_log(
        UpdateTable(),
        "user-1",
        "log-1",
        drink_logs.validate_update_input({"notes": "うまい"}),
    )

    assert "#whiskey_id" not in calls[0]["UpdateExpression"]


def test_selecting_a_later_bottle_does_not_inherit_the_first_bottles_match():
    """Multi-bottle photos must not cross-contaminate whiskey_id.

    analyze mirrors candidates[0].whiskey_id to the top level of the analysis
    item. Falling back to it for a selected candidate that has no match of its
    own means picking the 2nd bottle records it against the 1st bottle's master
    row, labelled brand_source "matched" -- a confidently wrong record.
    """
    result = {
        "whiskey_id": "caol-ila-12",
        "confidence": Decimal("0.9"),
        "model_id": "model-1",
        "serving_style": "NEAT",
    }
    unmatched_second = {
        "brand_text": "厚岸 シングルモルト",
        "confidence": Decimal("0.8"),
        "match_source": "ai",
    }

    completion = drink_logs._completion_from_analysis(
        result, unmatched_second, {}, candidate_selected=True
    )

    assert completion["brand_text"] == "厚岸 シングルモルト"
    assert "whiskey_id" not in completion
    assert completion["brand_source"] == "ai"


def test_selecting_a_matched_bottle_still_attaches_its_own_id():
    """The fix must not stop a genuinely matched candidate from linking."""
    result = {
        "whiskey_id": "caol-ila-12",
        "confidence": Decimal("0.9"),
        "model_id": "model-1",
        "serving_style": "NEAT",
    }
    matched = {
        "brand_text": "カリラ 12年",
        "whiskey_id": "caol-ila-12",
        "confidence": Decimal("0.9"),
        "match_source": "catalog",
    }

    completion = drink_logs._completion_from_analysis(
        result, matched, {}, candidate_selected=True
    )

    assert completion["whiskey_id"] == "caol-ila-12"
    assert completion["brand_source"] == "matched"
