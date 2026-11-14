#!/usr/bin/env python3
"""Idempotently create the local image bucket and browser upload CORS rules."""
import os
import sys

from botocore.exceptions import BotoCoreError, ClientError

from init_tables import LOCAL_DYNAMODB_ENDPOINT, REGION, create_local_resource


def main() -> None:
    # Reuse the explicit local credential/endpoint guards; never discover AWS credentials.
    dynamodb = create_local_resource()
    if os.environ.get("AWS_ENDPOINT_URL_S3") != LOCAL_DYNAMODB_ENDPOINT:
        raise ValueError(f"local S3 endpoint must be {LOCAL_DYNAMODB_ENDPOINT}")
    import boto3

    s3 = boto3.client(
        "s3", endpoint_url=LOCAL_DYNAMODB_ENDPOINT, region_name=REGION,
        aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
        config=dynamodb.meta.client.meta.config,
    )
    bucket = "whiskey-images-local"
    try:
        s3.create_bucket(Bucket=bucket, CreateBucketConfiguration={"LocationConstraint": REGION})
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "BucketAlreadyOwnedByYou":
            raise
    s3.put_bucket_cors(Bucket=bucket, CORSConfiguration={"CORSRules": [{
        "AllowedOrigins": ["http://localhost:3000"],
        "AllowedMethods": ["GET", "HEAD", "POST"],
        "AllowedHeaders": ["*"],
        "ExposeHeaders": ["ETag"],
        "MaxAgeSeconds": 3600,
    }]})
    print(f"ready: {bucket} (CORS: http://localhost:3000)")


if __name__ == "__main__":
    try:
        main()
    except (BotoCoreError, ClientError, ValueError) as exc:
        sys.exit(f"ERROR: {exc}")
