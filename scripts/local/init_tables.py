#!/usr/bin/env python3
"""Create the DynamoDB Local tables needed by the application."""

from __future__ import annotations

import os
import sys
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError


REGION = "ap-northeast-1"
LOCAL_DYNAMODB_ENDPOINT = "http://127.0.0.1:8001"
TABLE_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "TableName": "WhiskeySearch-local",
        "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
        "AttributeDefinitions": [
            {"AttributeName": "id", "AttributeType": "S"},
            {"AttributeName": "normalized_name", "AttributeType": "S"},
        ],
        "GlobalSecondaryIndexes": [
            {
                "IndexName": "NameIndex",
                "KeySchema": [{"AttributeName": "normalized_name", "KeyType": "HASH"}],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
        "BillingMode": "PAY_PER_REQUEST",
    },
    {
        "TableName": "DrinkLogs-local",
        "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
        "AttributeDefinitions": [
            {"AttributeName": "id", "AttributeType": "S"},
            {"AttributeName": "user_id", "AttributeType": "S"},
            {"AttributeName": "datetime", "AttributeType": "S"},
        ],
        "GlobalSecondaryIndexes": [
            {
                "IndexName": "UserDatetimeIndex",
                "KeySchema": [
                    {"AttributeName": "user_id", "KeyType": "HASH"},
                    {"AttributeName": "datetime", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
        "BillingMode": "PAY_PER_REQUEST",
    },
    {
        "TableName": "AppState-local",
        "KeySchema": [{"AttributeName": "pk", "KeyType": "HASH"}],
        "AttributeDefinitions": [{"AttributeName": "pk", "AttributeType": "S"}],
        "BillingMode": "PAY_PER_REQUEST",
    },
)


def create_local_resource():
    endpoint = os.environ.get("AWS_ENDPOINT_URL_DYNAMODB")
    access_key = os.environ.get("AWS_ACCESS_KEY_ID")
    secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY")
    if os.environ.get("AWS_ENDPOINT_URL"):
        raise ValueError("AWS_ENDPOINT_URL is forbidden; set AWS_ENDPOINT_URL_DYNAMODB")
    if not endpoint:
        raise ValueError("AWS_ENDPOINT_URL_DYNAMODB is required")
    if endpoint != LOCAL_DYNAMODB_ENDPOINT:
        raise ValueError(f"local DynamoDB endpoint must be {LOCAL_DYNAMODB_ENDPOINT}")
    if not access_key or not secret_key:
        raise ValueError("explicit local AWS credentials are required")
    session = boto3.Session(
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=REGION,
    )
    return session.resource(
        "dynamodb",
        endpoint_url=endpoint,
        config=Config(
            connect_timeout=2,
            read_timeout=5,
            retries={"mode": "standard", "total_max_attempts": 2},
        ),
    )


def initialize_tables(dynamodb: Any) -> None:
    client = dynamodb.meta.client
    existing = set(client.list_tables().get("TableNames", []))
    for definition in TABLE_DEFINITIONS:
        table_name = definition["TableName"]
        if table_name in existing:
            print(f"exists: {table_name}")
            continue
        try:
            client.create_table(**definition)
            client.get_waiter("table_exists").wait(
                TableName=table_name,
                WaiterConfig={"Delay": 1, "MaxAttempts": 30},
            )
            print(f"created: {table_name}")
        except client.exceptions.ResourceInUseException:
            print(f"exists: {table_name}")

    ttl = client.describe_time_to_live(TableName="AppState-local")["TimeToLiveDescription"]
    if ttl.get("TimeToLiveStatus") in {"DISABLED", "DISABLING"}:
        client.update_time_to_live(
            TableName="AppState-local",
            TimeToLiveSpecification={"Enabled": True, "AttributeName": "ttl"},
        )
        print("enabled TTL: AppState-local.ttl")
    else:
        print("exists: AppState-local.ttl")


def main() -> int:
    try:
        initialize_tables(create_local_resource())
        return 0
    except (BotoCoreError, ClientError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
