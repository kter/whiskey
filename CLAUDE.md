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
<<<<<<< HEAD
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
- IMPORTANT: 既存のAWSリソースをCDKにインポートするのは禁止。常に新しいリソースを作成すること
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


=======
# Start all services (includes LocalStack for AWS services)
make up
# or ./dev.sh up

# Stop services
make down

# View logs
make logs

# Backend shell access
make shell

# Run backend tests
make test

# Initialize test data
make init-db
```

### Frontend Development
```bash
cd frontend
npm run dev          # Development server at localhost:3000
npm run build        # Production build
npm run generate     # Static site generation
npm run lint         # ESLint
npm run lint:fix     # Auto-fix lint issues
```

### Backend Development
```bash
cd backend
python manage.py runserver              # Development server
python manage.py create_test_data       # Create sample data
pytest                                  # Run tests
```

### Infrastructure & Deployment
```bash
cd infra
npm run deploy:dev      # Deploy to dev environment
npm run deploy:prod     # Deploy to prod environment
npm run diff:dev        # Show deployment diff
npm run test            # Run infrastructure tests

# Manual deployment scripts
./scripts/deploy.sh dev     # Frontend deployment
./scripts/deploy-api.sh dev # Backend deployment
```

## Key Architecture Patterns

### Authentication Flow
1. AWS Cognito User Pool manages authentication
2. Amplify SDK handles frontend auth state with automatic token refresh
3. Backend validates JWT tokens via custom middleware (`CognitoAuthMiddleware`)
4. User ID extracted from JWT `sub` claim for data isolation

### Database Design (DynamoDB)
- **Whiskeys Table**: `id` (PK), with `NameIndex` GSI on `name`
- **Reviews Table**: `id` (PK), with `UserDateIndex` GSI on `user_id` + `date`
- All user data is isolated by `user_id` from JWT token

### API Structure
- RESTful endpoints under `/api/`
- Authentication required for CRUD operations
- Public read-only endpoints for rankings and discovery
- S3 presigned URLs for image uploads via `/api/s3/upload-url/`

### Frontend Composables
- `useAuth.ts`: Authentication state management
- `useWhiskeys.ts`: Whiskey search and suggestions
- `useSuggestWhiskeys.ts`: Autocomplete functionality

### Environment Management
- **local**: Docker Compose with LocalStack
- **dev**: AWS development (auto-deploy from `main` branch)
- **prod**: AWS production (auto-deploy from `production` branch)

## Important Files & Locations

### Core Backend Logic
- `backend/api/dynamodb_service.py`: All DynamoDB operations
- `backend/api/views.py`: API endpoints and business logic
- `backend/api/middleware.py`: JWT authentication middleware
- `backend/backend/settings.py`: Django configuration

### Core Frontend Logic
- `frontend/composables/useAuth.ts`: Authentication management
- `frontend/types/whiskey.ts`: TypeScript type definitions
- `frontend/plugins/amplify.client.ts`: Amplify configuration

### Configuration
- `frontend/nuxt.config.ts`: Frontend build and runtime config
- `docker-compose.yml`: Local development environment
- `infra/config/environments.ts`: Environment-specific AWS settings

### Data Models
```typescript
// Whiskey type
interface Whiskey {
  id: string;
  name: string;
  distillery: string;
  created_at: string;
  updated_at: string;
}

// Review type
interface Review {
  id: string;
  whiskey_id: string;
  user_id: string;
  rating: number;           // 1-5
  notes: string;
  serving_style: 'NEAT' | 'ROCKS' | 'WATER' | 'HIGHBALL';
  date: string;            // YYYY-MM-DD format
  image_url?: string;
  created_at: string;
  updated_at: string;
}
```

## Development Workflows

### Adding New API Endpoints
1. Add URL pattern to `backend/api/urls.py`
2. Implement view in `backend/api/views.py`
3. Add DynamoDB operations to `backend/api/dynamodb_service.py` if needed
4. Update frontend composables in `frontend/composables/`
5. Run `make test` for backend tests

### Modifying Database Schema
- DynamoDB is schemaless, but update TypeScript types in `frontend/types/whiskey.ts`
- Update serializers in `backend/api/serializers.py`
- Consider GSI requirements for new query patterns

### Frontend Component Development
- Follow existing patterns in `frontend/pages/` and `frontend/components/`
- Use Tailwind CSS for styling (already configured)
- Implement responsive design patterns
- Use composition API with TypeScript

### Deployment Process
- **Automatic**: Push to `main` (dev) or `production` (prod) branches
- **Manual**: Use deployment scripts in `scripts/` directory
- Infrastructure changes: Use CDK in `infra/` directory
- Always test locally with `make up` before deployment

## Environment Variables

### Required for Frontend
```bash
NUXT_PUBLIC_API_BASE_URL         # Backend API URL
NUXT_PUBLIC_USER_POOL_ID         # Cognito User Pool ID
NUXT_PUBLIC_USER_POOL_CLIENT_ID  # Cognito Client ID
NUXT_PUBLIC_REGION               # AWS Region
NUXT_PUBLIC_IMAGES_BUCKET        # S3 bucket for images
NUXT_PUBLIC_ENVIRONMENT          # Environment name
```

### Required for Backend
```bash
ENVIRONMENT                      # Environment name
DJANGO_SECRET_KEY               # Django secret
AWS_REGION                      # AWS Region
DYNAMODB_WHISKEYS_TABLE         # DynamoDB table name
DYNAMODB_REVIEWS_TABLE          # DynamoDB table name
S3_IMAGES_BUCKET               # S3 bucket name
COGNITO_USER_POOL_ID           # For JWT validation
```

## AWS Profile Configuration

**IMPORTANT**: When executing AWS CLI commands, always use the appropriate profile and set PAGER=cat:

### Development Environment
```bash
PAGER=cat AWS_PROFILE=dev aws [command]
```

### Production Environment  
```bash
PAGER=cat AWS_PROFILE=prd aws [command]
```

Examples:
```bash
# Check ECS logs (dev environment)
PAGER=cat AWS_PROFILE=dev aws logs tail /ecs/whiskey-api-dev --follow

# Check ECS logs (production environment)
PAGER=cat AWS_PROFILE=prd aws logs tail /ecs/whiskey-api-prod --follow

# List DynamoDB tables (dev environment)
PAGER=cat AWS_PROFILE=dev aws dynamodb list-tables

# Deploy infrastructure (automatically uses correct profile via scripts)
cd infra && npm run deploy:dev    # Uses dev profile internally
cd infra && npm run deploy:prod   # Uses prd profile internally
```

## Testing & Quality

### Running Tests
```bash
make test                    # Backend tests with pytest
cd infra && npm run test     # Infrastructure tests with Jest
cd frontend && npm run lint  # Frontend linting
```

### Local Services
When running `make up`, these services are available:
- Frontend: http://localhost:3000
- Backend API: http://localhost:8000
- LocalStack (AWS services): http://localhost:4566

## Troubleshooting

### Common Issues
1. **ECS deployment failures**: Check `./deploy-fix.sh` for ECR permission fixes
2. **Authentication errors**: Verify Cognito configuration and JWT token validity
3. **DynamoDB errors**: Ensure proper table names and GSI usage
4. **CORS issues**: Check allowed origins in Django settings

### Debug Commands
```bash
# Check ECS logs (with appropriate profile and pager)
PAGER=cat AWS_PROFILE=dev aws logs tail /ecs/whiskey-api-dev --follow
PAGER=cat AWS_PROFILE=prd aws logs tail /ecs/whiskey-api-prod --follow

# Health check
curl https://api.dev.whiskeybar.site/health/
curl https://api.whiskeybar.site/health/

# Local DynamoDB (via LocalStack - no profile needed)
PAGER=cat aws --endpoint-url=http://localhost:4566 dynamodb list-tables

# Check target group health (with appropriate profile and pager)
PAGER=cat AWS_PROFILE=dev aws elbv2 describe-target-health --target-group-arn <target-group-arn>

# CloudFormation stack events (with appropriate profile and pager)
PAGER=cat AWS_PROFILE=dev aws cloudformation describe-stack-events --stack-name WhiskeyApp-Dev
PAGER=cat AWS_PROFILE=prd aws cloudformation describe-stack-events --stack-name WhiskeyApp-Prod

# ECS service status (with appropriate profile and pager)
PAGER=cat AWS_PROFILE=dev aws ecs describe-services --cluster whiskey-api-cluster-dev --services whiskey-api-service-dev
```

Always run lint/typecheck commands after making changes, and test locally with Docker Compose before deployment.
>>>>>>> refs/remotes/origin/main
