#!/bin/bash

# Wait for LocalStack to be ready
echo "Waiting for LocalStack to be ready..."
while ! nc -z localstack 4566; do
  sleep 1
done
echo "LocalStack is ready!"

# Create S3 bucket
echo "Creating S3 bucket..."
awslocal s3 mb s3://whiskey-reviews

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

echo "LocalStack initialization completed!" 