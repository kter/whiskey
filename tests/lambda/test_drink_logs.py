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

import pytest
from botocore.exceptions import ClientError
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
        "expires_at": int(datetime.now(timezone.utc).timestamp()) + 600,
        "body": body,
    }


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
