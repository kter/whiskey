#!/bin/bash

# ECR権限修正のための緊急デプロイスクリプト
set -e

echo "🔧 Fixing ECR permissions for GitHub Actions..."
echo ""

# AWS認証情報の確認
if ! aws sts get-caller-identity >/dev/null 2>&1; then
    echo "❌ AWS credentials not configured"
    echo "Please run: aws configure"
    echo "Or set AWS_PROFILE environment variable"
    exit 1
fi

# CDK環境の確認
cd infra

# 依存関係のインストール
echo "📦 Installing CDK dependencies..."
npm install

# CDKのbootstrap確認（必要に応じて）
echo "🔍 Checking CDK bootstrap..."
if ! aws cloudformation describe-stacks --stack-name CDKToolkit --region ap-northeast-1 >/dev/null 2>&1; then
    echo "⚠️ CDK is not bootstrapped. Running bootstrap..."
    npx cdk bootstrap
fi

# 開発環境にデプロイ
echo "🚀 Deploying ECR permission fixes to dev environment..."
npx cdk deploy WhiskeyApp-Dev --require-approval never

echo ""
echo "✅ ECR permission fixes deployed successfully!"
echo ""
echo "🔄 Please retry your GitHub Actions workflow now."
echo "The ECR authentication error should be resolved." 