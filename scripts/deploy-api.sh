#!/bin/bash

# Whiskey API Manual Deployment Script
# このスクリプトはAPIのDockerイメージをビルドし、ECRにプッシュして、ECSサービスを更新します

set -e

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored output
print_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if environment is provided
if [ -z "$1" ]; then
    print_error "Usage: $0 <environment>"
    print_info "Available environments: dev, prod"
    exit 1
fi

ENVIRONMENT=$1
REGION="ap-northeast-1"

# Validate environment
if [[ "$ENVIRONMENT" != "dev" && "$ENVIRONMENT" != "prod" ]]; then
    print_error "Invalid environment: $ENVIRONMENT"
    print_info "Available environments: dev, prod"
    exit 1
fi

# Determine stack name
if [[ "$ENVIRONMENT" == "dev" ]]; then
    STACK_NAME="WhiskeyApp-Dev"
elif [[ "$ENVIRONMENT" == "prod" ]]; then
    STACK_NAME="WhiskeyApp-Prd"
fi

print_info "Starting API deployment for $ENVIRONMENT environment..."

# Check if AWS CLI is installed
if ! command -v aws &> /dev/null; then
    print_error "AWS CLI not found. Please install AWS CLI first."
    exit 1
fi

# Check if Docker is installed and running
if ! command -v docker &> /dev/null; then
    print_error "Docker not found. Please install Docker first."
    exit 1
fi

if ! docker info &> /dev/null; then
    print_error "Docker daemon is not running. Please start Docker."
    exit 1
fi

# Check if jq is installed
if ! command -v jq &> /dev/null; then
    print_error "jq not found. Please install jq first."
    exit 1
fi

# Get infrastructure outputs
print_info "Getting infrastructure outputs from CloudFormation..."

# Check if stack exists
if ! aws cloudformation describe-stacks --stack-name "$STACK_NAME" --region "$REGION" >/dev/null 2>&1; then
    print_error "Stack $STACK_NAME not found in region $REGION"
    print_info "Available stacks:"
    aws cloudformation list-stacks --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE --region "$REGION" --query 'StackSummaries[].StackName' --output text
    exit 1
fi

# Get API infrastructure outputs
API_REPOSITORY_URI=$(aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --region "$REGION" \
    --query "Stacks[0].Outputs[?OutputKey=='ApiRepositoryUri'].OutputValue" \
    --output text)

ECS_CLUSTER_NAME=$(aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --region "$REGION" \
    --query "Stacks[0].Outputs[?OutputKey=='EcsClusterName'].OutputValue" \
    --output text)

ECS_SERVICE_NAME=$(aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --region "$REGION" \
    --query "Stacks[0].Outputs[?OutputKey=='EcsServiceName'].OutputValue" \
    --output text)

# Validate outputs
if [[ -z "$API_REPOSITORY_URI" || "$API_REPOSITORY_URI" == "None" ]]; then
    print_error "Could not retrieve API Repository URI from stack"
    exit 1
fi

if [[ -z "$ECS_CLUSTER_NAME" || "$ECS_CLUSTER_NAME" == "None" ]]; then
    print_error "Could not retrieve ECS Cluster Name from stack"
    exit 1
fi

if [[ -z "$ECS_SERVICE_NAME" || "$ECS_SERVICE_NAME" == "None" ]]; then
    print_error "Could not retrieve ECS Service Name from stack"
    exit 1
fi

print_info "Infrastructure outputs:"
print_info "  API Repository URI: $API_REPOSITORY_URI"
print_info "  ECS Cluster: $ECS_CLUSTER_NAME"
print_info "  ECS Service: $ECS_SERVICE_NAME"

# Generate image tag
IMAGE_TAG="manual-$(date +%Y%m%d-%H%M%S)"
print_info "Using image tag: $IMAGE_TAG"

# Login to ECR
print_info "Logging in to Amazon ECR..."
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$API_REPOSITORY_URI"

# Build Docker image
print_info "Building Docker image..."
cd backend

if ! docker build -t "$API_REPOSITORY_URI:$IMAGE_TAG" .; then
    print_error "Docker build failed"
    exit 1
fi

# Tag as latest
docker tag "$API_REPOSITORY_URI:$IMAGE_TAG" "$API_REPOSITORY_URI:latest"

# Push Docker image
print_info "Pushing Docker image to ECR..."
if ! docker push "$API_REPOSITORY_URI:$IMAGE_TAG"; then
    print_error "Docker push failed for tag $IMAGE_TAG"
    exit 1
fi

if ! docker push "$API_REPOSITORY_URI:latest"; then
    print_error "Docker push failed for latest tag"
    exit 1
fi

print_info "Docker image pushed successfully"

# Update ECS service
print_info "Updating ECS service..."
cd ..

if ! aws ecs update-service \
    --cluster "$ECS_CLUSTER_NAME" \
    --service "$ECS_SERVICE_NAME" \
    --force-new-deployment \
    --region "$REGION" >/dev/null; then
    print_error "Failed to update ECS service"
    exit 1
fi

print_info "ECS service update initiated"

# Wait for deployment to complete
print_info "Waiting for deployment to stabilize... (this may take several minutes)"
if ! aws ecs wait services-stable \
    --cluster "$ECS_CLUSTER_NAME" \
    --services "$ECS_SERVICE_NAME" \
    --region "$REGION"; then
    print_warning "Deployment may have failed or timed out"
    print_info "Check ECS console for more details: https://console.aws.amazon.com/ecs/home?region=$REGION#/clusters/$ECS_CLUSTER_NAME/services/$ECS_SERVICE_NAME/details"
    exit 1
fi

print_info "ECS deployment completed successfully!"

# Check service status
RUNNING_COUNT=$(aws ecs describe-services \
    --cluster "$ECS_CLUSTER_NAME" \
    --services "$ECS_SERVICE_NAME" \
    --region "$REGION" \
    --query 'services[0].runningCount' \
    --output text)

DESIRED_COUNT=$(aws ecs describe-services \
    --cluster "$ECS_CLUSTER_NAME" \
    --services "$ECS_SERVICE_NAME" \
    --region "$REGION" \
    --query 'services[0].desiredCount' \
    --output text)

print_info "Service status: $RUNNING_COUNT/$DESIRED_COUNT tasks running"

# Get API URL
if [[ "$ENVIRONMENT" == "dev" ]]; then
    API_URL="https://api.dev.whiskeybar.site"
elif [[ "$ENVIRONMENT" == "prod" ]]; then
    API_URL="https://api.whiskeybar.site"
fi

print_info "API URL: $API_URL"
print_info "Health check: $API_URL/health/"

print_info "🎉 API deployment to $ENVIRONMENT environment completed successfully!"
print_info "Image: $API_REPOSITORY_URI:$IMAGE_TAG" 