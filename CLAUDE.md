# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Application Overview

This is a whiskey tasting review application built with:
- **Frontend**: Nuxt.js 3 SPA (TypeScript, Tailwind CSS)
- **Backend**: Django REST API with DynamoDB (running on Lambda)
- **Infrastructure**: AWS CDK (Lambda, API Gateway, S3, CloudFront, Cognito)
- **Authentication**: AWS Cognito with Google OAuth
- **Deployment**: GitHub Actions CI/CD

## AWS Account Configuration

### Development Environment
- **AWS Account ID**: 031921999648
- **AWS Profile**: `dev`
- **Region**: ap-northeast-1

### Deployment Commands
Always use the `dev` profile for development environment:
```bash
AWS_PROFILE=dev npm run deploy:dev
AWS_PROFILE=dev npx cdk deploy --all --require-approval never
```

## Development Commands

### Local Development
```bash
# Start all services with Docker Compose
make up               # or ./dev.sh up
make down             # Stop all services
make build            # Rebuild containers
make logs             # View logs
make shell            # Access backend shell

# Frontend development (in frontend/)
npm run dev           # Start Nuxt dev server
npm run build         # Build for production
npm run lint          # Run ESLint
npm run lint:fix      # Fix ESLint issues

# Backend development (in backend/)
python manage.py runserver        # Start Django server
python manage.py migrate          # Run migrations
python manage.py create_test_data # Create test data
pytest                            # Run tests

# Infrastructure (in infra/)
npm run build         # Compile TypeScript
npm run test          # Run CDK tests
npm run deploy:dev    # Deploy to dev environment
npm run deploy:prod   # Deploy to prod environment
npm run diff:dev      # Show infrastructure diff
npm run synth:dev     # Synthesize CloudFormation

# Lambda function deployment (CDK handles automatically)
AWS_PROFILE=dev npx cdk deploy WhiskeyApp-Dev --require-approval never
# CDK automatically packages backend/ directory and deploys to Lambda
```

### Testing
```bash
# Backend tests
make test             # Run Django tests via Docker
./dev.sh test         # Alternative method

# Infrastructure tests
cd infra && npm test  # Run CDK tests
```

## Architecture

### Three-Tier Application（費用最適化済み）
1. **Frontend (Nuxt.js SPA)**: Static files served via S3/CloudFront
2. **API (Django REST)**: Serverless functions on AWS Lambda behind API Gateway
3. **Data Layer**: DynamoDB for application data, Cognito for authentication

### Key Infrastructure Components（全て従量課金）
- **VPC**: Multi-AZ with public/private subnets (**natGateways: 0** - 費用ゼロ)
- **Lambda**: Serverless compute platform for API（実行時のみ課金）
- **API Gateway**: RESTful API endpoint with CORS support（リクエスト従量）
- **S3**: Static site hosting + image storage（ストレージ従量）
- **CloudFront**: CDN for global content delivery（転送量従量）
- **DynamoDB**: NoSQL database - Pay per request（アクセス従量）
- **Cognito**: User authentication + Google OAuth（MAU従量）
- **Route53**: DNS management with custom domains（クエリ従量）

### 費用削減済みリソース
- ❌ **NAT Gateway**: 削除済み（月額$30-45削減）
- ❌ **ALB**: 削除済み（月額$16-25削減）
- ❌ **ECS Fargate**: 削除済み（月額$15-50削減）
- ✅ **総削減額**: 月額$60-120の大幅削減達成

### Environment Configuration
- **Local**: Docker Compose with LocalStack
- **Dev**: `dev.whiskeybar.site` + `api.dev.whiskeybar.site`
- **Prod**: `whiskeybar.site` + `api.whiskeybar.site`

## Key File Locations

### Frontend Structure
- `frontend/nuxt.config.ts` - Nuxt configuration
- `frontend/composables/` - Vue composables for API calls
- `frontend/pages/` - Vue page components
- `frontend/layouts/default.vue` - Main layout with auth handling

### Backend Structure
- `backend/backend/settings.py` - Django settings with environment detection
- `backend/api/` - Django REST API application
- `backend/api/middleware.py` - Cognito JWT authentication middleware
- `backend/api/dynamodb_service.py` - DynamoDB operations
- `backend/lambda_handler.py` - AWS Lambda entry point using Mangum

### Infrastructure
- `infra/lib/whiskey-infra-stack.ts` - Main CDK stack definition
- `infra/config/environments.ts` - Environment-specific configurations
- `infra/scripts/deploy.sh` - Deployment script

### Deployment
- `.github/workflows/` - GitHub Actions for CI/CD
- `scripts/` - Deployment and utility scripts
- `docker-compose.yml` - Local development setup

## Development Principles

### NEVER（絶対禁止）:
- NEVER: パスワードやAPIキーをハードコーディングしない
- NEVER: ユーザーの確認なしにデータを削除しない
- NEVER: テストなしで本番環境にデプロイしない
- **NEVER: 高額なAWSリソースを使用しない**
  - **NAT Gateway** (月額$30-45+) - 絶対に作成禁止
  - **Application Load Balancer (ALB)** (月額$16-25+) - 絶対に作成禁止
  - **EC2インスタンス** (月額$10-100+) - 絶対に作成禁止
  - **ECS Fargate** (月額$15-50+) - 絶対に作成禁止
  - **RDS** (月額$20-200+) - 絶対に作成禁止

### YOU MUST（必須事項）：
- YOU MUST: すべての公開APIにドキュメントを記載
- YOU MUST: エラーハンドリングを実装
- YOU MUST: 変更前に既存テストが通ることを確認
- YOU MUST: 生成したコードの動作原理を説明できること

### IMPORTANT（重要事項）：
- IMPORTANT: パフォーマンスへの影響を考慮
- IMPORTANT: 後方互換性を維持
- IMPORTANT: セキュリティベストプラクティスに従う
- IMPORTANT: 複雑な型定義には必ず使用例とコメントを追加
- IMPORTANT: シンプルで明快な実装を優先する
- IMPORTANT: 複雑なロジックにはコメントを付ける
- IMPORTANT: 既にIaCでコード化されているインフラのリソースを変更する際はawsコマンドではなくIaCを使用する
- IMPORTANT: エラーが発生したらエラー文をWebで検索し修正する
- **IMPORTANT: 費用最適化されたアーキテクチャを維持する**
  - **使用推奨**: Lambda, API Gateway, S3, CloudFront, DynamoDB, Cognito
  - **VPC設定**: natGateways: 0 を維持（Lambdaは常にVPC外で実行）
  - **証明書**: us-east-1用は別スタックで管理
  - **モニタリング**: CloudWatchで使用量を定期監視

## Authentication Flow

The application uses AWS Cognito for authentication:
1. Users can sign up/in with email or Google OAuth
2. Frontend receives JWT tokens (access, ID, refresh)
3. API validates JWT tokens via Cognito middleware
4. Automatic token refresh handled by frontend

## Data Models

### DynamoDB Tables
- **Whiskeys**: Main whiskey data (id, name, distillery, region)
- **Reviews**: User reviews (id, whiskey_id, user_id, rating, notes, image_url)
- **GSI**: NameIndex for whiskeys, UserDateIndex for reviews

### API Endpoints
- `GET /api/whiskeys/` - List whiskeys
- `POST /api/reviews/` - Create review
- `GET /api/reviews/` - List user reviews
- `GET /health/` - Health check endpoint

## Environment Variables

### Frontend (.env)
- `NUXT_PUBLIC_API_BASE_URL` - API base URL
- `NUXT_PUBLIC_USER_POOL_ID` - Cognito User Pool ID
- `NUXT_PUBLIC_USER_POOL_CLIENT_ID` - Cognito Client ID
- `NUXT_PUBLIC_REGION` - AWS region

### Backend (.env)
- `ENVIRONMENT` - Runtime environment (local/dev/prod)
- `DJANGO_SECRET_KEY` - Django secret key
- `COGNITO_USER_POOL_ID` - Cognito User Pool ID
- `DYNAMODB_WHISKEYS_TABLE` - DynamoDB table name
- `S3_IMAGES_BUCKET` - S3 bucket for images

## Deployment Strategy

### Infrastructure-as-Code
- All AWS resources defined in CDK
- Environment-specific configurations
- Automated CloudFormation deployment

### CI/CD Pipeline
- GitHub Actions triggers on branch push
- Parallel deployment of frontend and API
- Automatic invalidation of CloudFront cache
- **Lambda deployment via CDK** (not direct zip upload)
  - CDK automatically handles code packaging and deployment
  - Uses `Code.fromAsset()` for automatic zip creation
  - No manual Lambda function updates required


