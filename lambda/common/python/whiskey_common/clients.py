"""Consistently configured boto3 client and resource factories."""

import os
from typing import Any

import boto3
from botocore.config import Config


BASE_CONFIG = Config(
    connect_timeout=3,
    read_timeout=10,
    retries={"mode": "standard", "total_max_attempts": 2},
)


def _endpoint_url(service_name: str) -> str | None:
    if service_name == "s3":
        return os.environ.get("AWS_ENDPOINT_URL_S3")
    if service_name == "dynamodb":
        return os.environ.get("AWS_ENDPOINT_URL_DYNAMODB")
    return None


def _config(service_name: str) -> Config:
    if service_name == "s3":
        return BASE_CONFIG.merge(Config(s3={"addressing_style": "path"}))
    return BASE_CONFIG


def _kwargs(service_name: str) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"config": _config(service_name)}
    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
    endpoint_url = _endpoint_url(service_name)
    if region:
        kwargs["region_name"] = region
    if endpoint_url:
        kwargs["endpoint_url"] = endpoint_url
    return kwargs


def get_boto3_client(service_name: str):
    """Return a boto3 client with bounded timeouts and retries."""
    return boto3.client(service_name, **_kwargs(service_name))


def get_boto3_resource(service_name: str):
    """Return a boto3 resource with bounded timeouts and retries."""
    return boto3.resource(service_name, **_kwargs(service_name))


def get_dynamodb_resource():
    return get_boto3_resource("dynamodb")


def get_s3_client():
    return get_boto3_client("s3")
