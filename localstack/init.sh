#!/bin/bash

# Wait for LocalStack to be ready
echo "Waiting for LocalStack to be ready..."
while ! nc -z localstack 4566; do
  sleep 1
done
echo "LocalStack is ready!"

# Create S3 bucket
echo "Creating S3 bucket..."
awslocal s3 mb s3://whiskey-reviews --region ap-northeast-1

# Set bucket policy to allow public read access
echo "Setting bucket policy..."
awslocal s3api put-bucket-policy --bucket whiskey-reviews --policy '{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "PublicReadGetObject",
            "Effect": "Allow",
            "Principal": "*",
            "Action": "s3:GetObject",
            "Resource": "arn:aws:s3:::whiskey-reviews/*"
        }
    ]
}'

# DynamoDBテーブルの作成

echo "Creating DynamoDB tables..."

# Whiskeysテーブル
awslocal dynamodb create-table \
    --table-name Whiskeys \
    --attribute-definitions \
        AttributeName=id,AttributeType=S \
        AttributeName=name,AttributeType=S \
    --key-schema \
        AttributeName=id,KeyType=HASH \
    --global-secondary-indexes \
        "IndexName=NameIndex,KeySchema=[{AttributeName=name,KeyType=HASH}],Projection={ProjectionType=ALL}" \
    --billing-mode PAY_PER_REQUEST \
    --region ap-northeast-1

# Reviewsテーブル
awslocal dynamodb create-table \
    --table-name Reviews \
    --attribute-definitions \
        AttributeName=id,AttributeType=S \
        AttributeName=user_id,AttributeType=S \
        AttributeName=date,AttributeType=S \
    --key-schema \
        AttributeName=id,KeyType=HASH \
    --global-secondary-indexes \
        "IndexName=UserDateIndex,KeySchema=[{AttributeName=user_id,KeyType=HASH},{AttributeName=date,KeyType=RANGE}],Projection={ProjectionType=ALL}" \
    --billing-mode PAY_PER_REQUEST \
    --region ap-northeast-1

echo "Tables and bucket created successfully!"

echo "LocalStack initialization completed!" 