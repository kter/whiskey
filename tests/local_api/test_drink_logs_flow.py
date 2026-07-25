"""HTTP integration coverage for the local drink-log adapter."""

import asyncio
import io
import os
import sys
from contextlib import contextmanager

import boto3
import httpx
import pytest
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient
from moto import mock_aws
from PIL import Image


pytest.importorskip("fastapi")


LOCAL_USER_ID = "local-user"
DRINKLOGS_TABLE = "DrinkLogs-local"
APP_STATE_TABLE = "AppState-local"
WHISKEYS_TABLE = "WhiskeySearch-local"
IMAGES_BUCKET = "whiskey-images-local"


class _AsyncAsgiClient:
    """Keep the ASGI request on the test thread for Python 3.14."""

    def __init__(self, app):
        self.app = app

    def request(self, method, path, **kwargs):
        async def send():
            transport = httpx.ASGITransport(app=self.app)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://testserver",
            ) as client:
                return await client.request(method, path, **kwargs)

        return asyncio.run(send())

    def get(self, path, **kwargs):
        return self.request("GET", path, **kwargs)

    def post(self, path, **kwargs):
        return self.request("POST", path, **kwargs)

    def delete(self, path, **kwargs):
        return self.request("DELETE", path, **kwargs)


def _create_tables(dynamodb):
    dynamodb.create_table(
        TableName=DRINKLOGS_TABLE,
        KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
        AttributeDefinitions=[
            {"AttributeName": "id", "AttributeType": "S"},
            {"AttributeName": "user_id", "AttributeType": "S"},
            {"AttributeName": "datetime", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "UserDatetimeIndex",
                "KeySchema": [
                    {"AttributeName": "user_id", "KeyType": "HASH"},
                    {"AttributeName": "datetime", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    dynamodb.create_table(
        TableName=APP_STATE_TABLE,
        KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    dynamodb.create_table(
        TableName=WHISKEYS_TABLE,
        KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
        AttributeDefinitions=[
            {"AttributeName": "id", "AttributeType": "S"},
            {"AttributeName": "normalized_name", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "NameIndex",
                "KeySchema": [{"AttributeName": "normalized_name", "KeyType": "HASH"}],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
        BillingMode="PAY_PER_REQUEST",
    )


def _jpeg_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (40, 20), (191, 128, 64)).save(output, format="JPEG")
    return output.getvalue()


@contextmanager
def _local_http_services(monkeypatch):
    monkeypatch.setenv("MOCK_AUTH", "1")
    monkeypatch.setenv("MOCK_AI", "1")
    monkeypatch.setenv("MOCK_PLACES", "1")
    with mock_aws():
        from local_api import main

        # The adapter pins real local-process endpoints. Removing only those
        # endpoints lets boto3 stay behind moto while preserving all local env.
        monkeypatch.delenv("AWS_ENDPOINT_URL_DYNAMODB")
        monkeypatch.delenv("AWS_ENDPOINT_URL_S3")

        dynamodb = boto3.client("dynamodb", region_name=os.environ["AWS_REGION"])
        _create_tables(dynamodb)
        s3 = boto3.client("s3", region_name=os.environ["AWS_REGION"])
        s3.create_bucket(
            Bucket=IMAGES_BUCKET,
            CreateBucketConfiguration={"LocationConstraint": os.environ["AWS_REGION"]},
        )

        # Keep moto calls on the ASGI thread instead of adding a second worker
        # thread beneath TestClient.
        async def inline(handler, *args):
            return handler(*args)

        monkeypatch.setattr(main, "run_in_threadpool", inline)
        if sys.version_info >= (3, 14):
            # FastAPI 0.115's TestClient portal blocks on Python 3.14. Running
            # the same ASGI HTTP request inline also keeps moto's state on one
            # thread. Supported project runtimes continue to use TestClient.
            client = _AsyncAsgiClient(main.app)
        else:
            client = TestClient(main.app)
        yield client, boto3.resource("dynamodb", region_name=os.environ["AWS_REGION"]), s3


def test_drink_log_full_http_flow(monkeypatch):
    with _local_http_services(monkeypatch) as (client, dynamodb, s3):
        upload_response = client.post(
            "/api/drink-logs/upload-url",
            json={"content_type": "image/jpeg"},
        )
        assert upload_response.status_code == 200
        upload = upload_response.json()
        assert upload["upload_url"]
        assert upload["fields"]
        assert upload["s3_key"].startswith(f"tmp/{LOCAL_USER_ID}/")
        assert upload["fields"]["key"] == upload["s3_key"]

        put_response = s3.put_object(
            Bucket=IMAGES_BUCKET,
            Key=upload["fields"]["key"],
            Body=_jpeg_bytes(),
            ContentType="image/jpeg",
        )
        etag = put_response["ETag"]

        analyze_response = client.post(
            "/api/drink-logs/analyze",
            json={"s3_key": upload["s3_key"]},
        )
        assert analyze_response.status_code == 200
        analysis = analyze_response.json()
        assert analysis["analysis_id"].startswith(f"ai-result:{LOCAL_USER_ID}:")
        assert analysis["candidates"][0]["brand_text"] == "モックウイスキー"

        analysis_item = dynamodb.Table(APP_STATE_TABLE).get_item(
            Key={"pk": analysis["analysis_id"]},
            ConsistentRead=True,
        )["Item"]
        assert analysis_item["ETag"] == etag
        assert analysis_item["s3_key"] == upload["s3_key"]

        create_response = client.post(
            "/api/drink-logs",
            json={"analysis_id": analysis["analysis_id"], "candidate_index": 0},
        )
        assert create_response.status_code in {200, 201}
        created = create_response.json()
        assert created["status"] == "complete"
        assert created["datetime"].endswith("Z")
        assert created["store"] == {"name": ""}
        assert "logs/" in created["image_url"]

        with pytest.raises(ClientError) as missing_tmp:
            s3.head_object(Bucket=IMAGES_BUCKET, Key=upload["s3_key"])
        assert missing_tmp.value.response["Error"]["Code"] in {
            "404",
            "NoSuchKey",
            "NotFound",
        }

        timeline_response = client.get("/api/drink-logs")
        assert timeline_response.status_code == 200
        timeline = timeline_response.json()
        assert timeline["count"] == 1
        item = timeline["results"][0]
        assert item["id"] == created["id"]
        assert item["image_url"]
        for internal_field in ("s3_image_key", "tmp_s3_key", "quota_allocated"):
            assert internal_field not in item

        places_response = client.post(
            "/api/drink-logs/places",
            json={"lat": 35.68, "lng": 139.76},
        )
        assert places_response.status_code == 200
        assert places_response.json() == [
            {
                "place_id": "mock-place-1",
                "display_name": "モックバー",
                "formatted_address": "東京都モック区1-1",
                "attributions": [],
            }
        ]

        delete_response = client.delete(f"/api/drink-logs/{created['id']}")
        assert delete_response.status_code == 204

        empty_timeline = client.get("/api/drink-logs")
        assert empty_timeline.status_code == 200
        assert empty_timeline.json()["results"] == []


def test_drink_log_http_requires_authentication(monkeypatch):
    with _local_http_services(monkeypatch) as (client, _dynamodb, _s3):
        monkeypatch.setenv("MOCK_AUTH", "0")
        response = client.post(
            "/api/drink-logs/upload-url",
            json={"content_type": "image/jpeg"},
        )
        assert response.status_code == 401
