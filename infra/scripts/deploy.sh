#!/bin/bash

# CDK デプロイスクリプト for Whiskey App
# Usage: ./scripts/deploy.sh [dev|prod]

set -e

# 色の定義
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 使用方法の表示
show_usage() {
    echo "Usage: $0 [dev|prod] [options]"
    echo ""
    echo "Environments:"
    echo "  dev     Deploy to development environment"
    echo "  prod    Deploy to production environment"
    echo ""
    echo "Options:"
    echo "  --diff       Show diff before deployment"
    echo "  --no-confirm Skip confirmation prompt"
    echo "  --destroy    Destroy the stack instead of deploying"
    echo ""
    echo "Examples:"
    echo "  $0 dev"
    echo "  $0 prod --diff"
    echo "  $0 dev --destroy"
    exit 1
}

# 引数チェック
if [ $# -eq 0 ]; then
    show_usage
fi

ENVIRONMENT=$1
SHOW_DIFF=false
NO_CONFIRM=false
DESTROY=false

# オプション解析
shift
while [[ $# -gt 0 ]]; do
    case $1 in
        --diff)
            SHOW_DIFF=true
            shift
            ;;
        --no-confirm)
            NO_CONFIRM=true
            shift
            ;;
        --destroy)
            DESTROY=true
            shift
            ;;
        -h|--help)
            show_usage
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            show_usage
            ;;
    esac
done

# 環境チェック
if [ "$ENVIRONMENT" != "dev" ] && [ "$ENVIRONMENT" != "prod" ]; then
    echo -e "${RED}Error: Environment must be 'dev' or 'prod'${NC}"
    show_usage
fi

# 前提条件チェック
echo -e "${YELLOW}Checking prerequisites...${NC}"

# AWS CLI チェック
if ! command -v aws &> /dev/null; then
    echo -e "${RED}Error: AWS CLI is not installed${NC}"
    exit 1
fi

# AWS認証チェック
if ! aws sts get-caller-identity &> /dev/null; then
    echo -e "${RED}Error: AWS credentials not configured${NC}"
    echo "Please run: aws configure"
    exit 1
fi

# Node.js/npm チェック
if ! command -v npm &> /dev/null; then
    echo -e "${RED}Error: npm is not installed${NC}"
    exit 1
fi

# CDK CLI チェック
if ! npx cdk --version &> /dev/null; then
    echo -e "${YELLOW}Installing AWS CDK CLI...${NC}"
    npm install -g aws-cdk
fi

echo -e "${GREEN}Prerequisites check passed!${NC}"

# ディレクトリ移動
cd "$(dirname "$0")/.."

# パッケージインストール
echo -e "${YELLOW}Installing dependencies...${NC}"
npm install

# TypeScriptコンパイル
echo -e "${YELLOW}Building TypeScript...${NC}"
npm run build

# 環境情報表示
echo -e "${YELLOW}Deployment Information:${NC}"
echo "Environment: $ENVIRONMENT"
echo "Stack Name: WhiskeyApp-$(echo $ENVIRONMENT | sed 's/./\U&/')"
echo "Region: ap-northeast-1"
echo "Account: $(aws sts get-caller-identity --query Account --output text)"

# 本番環境の追加確認
if [ "$ENVIRONMENT" == "prod" ] && [ "$NO_CONFIRM" != "true" ] && [ "$DESTROY" != "true" ]; then
    echo ""
    echo -e "${RED}⚠️  WARNING: You are about to deploy to PRODUCTION environment!${NC}"
    read -p "Are you sure you want to continue? (yes/no): " -r
    if [[ ! $REPLY =~ ^[Yy][Ee][Ss]$ ]]; then
        echo "Deployment cancelled."
        exit 1
    fi
fi

# CDK Bootstrap（初回のみ）
echo -e "${YELLOW}Checking CDK bootstrap...${NC}"
if ! aws cloudformation describe-stacks --stack-name CDKToolkit &> /dev/null; then
    echo -e "${YELLOW}Bootstrapping CDK...${NC}"
    npx cdk bootstrap -c env=$ENVIRONMENT
fi

# Diff表示
if [ "$SHOW_DIFF" == "true" ]; then
    echo -e "${YELLOW}Showing deployment diff...${NC}"
    npx cdk diff -c env=$ENVIRONMENT
    echo ""
    if [ "$NO_CONFIRM" != "true" ]; then
        read -p "Continue with deployment? (yes/no): " -r
        if [[ ! $REPLY =~ ^[Yy][Ee][Ss]$ ]]; then
            echo "Deployment cancelled."
            exit 1
        fi
    fi
fi

# デプロイまたは削除実行
if [ "$DESTROY" == "true" ]; then
    echo -e "${RED}Destroying stack...${NC}"
    npx cdk destroy -c env=$ENVIRONMENT --force
    echo -e "${GREEN}Stack destruction completed!${NC}"
else
    echo -e "${YELLOW}Deploying stack...${NC}"
    npx cdk deploy -c env=$ENVIRONMENT --require-approval never
    
    echo -e "${GREEN}Deployment completed successfully!${NC}"
    echo ""
    echo -e "${YELLOW}Stack Outputs:${NC}"
    aws cloudformation describe-stacks \
        --stack-name "WhiskeyApp-$(echo $ENVIRONMENT | sed 's/./\U&/')" \
        --query 'Stacks[0].Outputs[*].[OutputKey,OutputValue]' \
        --output table
fi

echo ""
echo -e "${GREEN}✅ Operation completed for $ENVIRONMENT environment!${NC}" 