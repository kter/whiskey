#!/bin/bash

echo "Creating DynamoDB session table..."

# Create Django session table
docker-compose exec -T localstack awslocal dynamodb create-table \
  --table-name django_session \
  --attribute-definitions AttributeName=session_key,AttributeType=S \
  --key-schema AttributeName=session_key,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST \
  --region ap-northeast-1

echo "Django session table created successfully!"

# Check if table exists
echo "Verifying table creation..."
docker-compose exec -T localstack awslocal dynamodb describe-table \
  --table-name django_session \
  --region ap-northeast-1 > /dev/null

if [ $? -eq 0 ]; then
    echo "✅ Session table is ready for use"
else
    echo "❌ Failed to create session table"
    exit 1
fi 