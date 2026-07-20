#!/usr/bin/env python3
"""Load the curated whiskey fixture into an explicit local or dev target."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError, ProfileNotFound


ROOT = Path(__file__).resolve().parents[2]
COMMON_PYTHON = ROOT / "lambda" / "common" / "python"
if str(COMMON_PYTHON) not in sys.path:
    sys.path.insert(0, str(COMMON_PYTHON))

from whiskey_common.normalize import normalize_text  # noqa: E402


DEV_ACCOUNT_ID = "031921999648"
REGION = "ap-northeast-1"
LOCAL_DYNAMODB_ENDPOINT = "http://127.0.0.1:8001"
FIXTURE_PATH = Path(__file__).resolve().parent / "seed_data" / "whiskeys.json"
CLIENT_CONFIG = Config(
    connect_timeout=3,
    read_timeout=10,
    retries={"mode": "standard", "total_max_attempts": 2},
)


def create_dynamodb_resource(target: str, profile: str | None):
    if os.environ.get("AWS_ENDPOINT_URL"):
        raise ValueError("AWS_ENDPOINT_URL is forbidden; use service-specific endpoints")

    endpoint = os.environ.get("AWS_ENDPOINT_URL_DYNAMODB")
    if target == "local":
        if not endpoint:
            raise ValueError("local target requires AWS_ENDPOINT_URL_DYNAMODB")
        if endpoint != LOCAL_DYNAMODB_ENDPOINT:
            raise ValueError(f"local DynamoDB endpoint must be {LOCAL_DYNAMODB_ENDPOINT}")
        if profile:
            raise ValueError("local target does not accept --profile")
        access_key = os.environ.get("AWS_ACCESS_KEY_ID")
        secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY")
        if not access_key or not secret_key:
            raise ValueError("local target requires explicit AWS credentials")
        session = boto3.Session(
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=REGION,
        )
        return session.resource(
            "dynamodb",
            endpoint_url=endpoint,
            config=CLIENT_CONFIG,
        )

    if endpoint or os.environ.get("AWS_ENDPOINT_URL_S3"):
        raise ValueError("dev target forbids local AWS endpoint variables")
    if not profile:
        raise ValueError("dev target requires an explicit --profile")
    session = boto3.Session(profile_name=profile, region_name=REGION)
    identity = session.client("sts", config=CLIENT_CONFIG).get_caller_identity()
    account = identity.get("Account")
    if account != DEV_ACCOUNT_ID:
        raise ValueError(f"dev target requires AWS account {DEV_ACCOUNT_ID}; got {account}")
    print(f"verified dev account: {account} ({identity['Arn']})")
    return session.resource("dynamodb", config=CLIENT_CONFIG)


def load_fixture(path: Path = FIXTURE_PATH) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as fixture_file:
        items = json.load(fixture_file)
    if not isinstance(items, list) or len(items) != 50:
        raise ValueError("seed fixture must contain exactly 50 whiskeys")
    required = {"id", "name_en", "name_ja", "distillery_en", "distillery_ja", "region", "type"}
    seen_ids: set[str] = set()
    for position, item in enumerate(items):
        if not isinstance(item, dict) or any(not item.get(key) for key in required):
            raise ValueError(f"fixture item {position} is missing a required non-empty field")
        if item["id"] in seen_ids:
            raise ValueError(f"duplicate whiskey id: {item['id']}")
        seen_ids.add(item["id"])
    return items


def to_dynamodb_item(source: dict[str, str], now: str) -> dict[str, Any]:
    name_ja = source["name_ja"].strip()
    name_en = source["name_en"].strip()
    distillery_ja = source["distillery_ja"].strip()
    return {
        **source,
        "name": name_ja,
        "distillery": distillery_ja,
        "normalized_name": normalize_text(f"{name_ja}|{name_en}"),
        "confidence": Decimal("1"),
        "source": "local_seed",
        "created_at": now,
        "updated_at": now,
    }


def increment_whiskey_revision(app_state_table: Any) -> None:
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    app_state_table.update_item(
        Key={"pk": "whiskey-change-counter"},
        UpdateExpression="SET updated_at = :updated_at ADD #count :one",
        ExpressionAttributeNames={"#count": "count"},
        ExpressionAttributeValues={":one": 1, ":updated_at": now},
    )
    app_state_table.update_item(
        Key={"pk": "ranking-cache/meta"},
        UpdateExpression="SET dirty_since = if_not_exists(dirty_since, :updated_at)",
        ExpressionAttributeValues={":updated_at": now},
    )


def seed(target: str, profile: str | None, fixture_path: Path = FIXTURE_PATH) -> int:
    dynamodb = create_dynamodb_resource(target, profile)
    suffix = "local" if target == "local" else "dev"
    whiskey_table = dynamodb.Table(f"WhiskeySearch-{suffix}")
    app_state_table = dynamodb.Table(f"AppState-{suffix}")
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    items = [to_dynamodb_item(item, now) for item in load_fixture(fixture_path)]
    with whiskey_table.batch_writer(overwrite_by_pkeys=["id"]) as writer:
        for item in items:
            writer.put_item(Item=item)
    increment_whiskey_revision(app_state_table)
    return len(items)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed curated whiskeys")
    parser.add_argument("--target", choices=("local", "dev"), required=True)
    parser.add_argument("--profile", help="required explicit AWS profile for --target dev")
    parser.add_argument("--fixture", type=Path, default=FIXTURE_PATH)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        count = seed(args.target, args.profile, args.fixture)
        print(f"seeded {count} whiskeys into {args.target}")
        return 0
    except (BotoCoreError, ClientError, ProfileNotFound, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
