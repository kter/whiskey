# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Application Overview

This is a whiskey tasting review application built with:
- **Frontend**: Nuxt.js 3 SPA (TypeScript, Tailwind CSS)
- **Backend**: Serverless Lambda functions with DynamoDB
- **Infrastructure**: AWS CDK (Lambda, API Gateway, S3, CloudFront, Cognito)
- **Authentication**: AWS Cognito with Google OAuth
- **Search**: Multi-language (English/Japanese) whiskey search
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
AWS_PROFILE=dev npx cdk deploy WhiskeyApp-Dev --require-approval never
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

# Infrastructure (in infra/)
npm run build         # Compile TypeScript
npm run test          # Run CDK tests
npm run deploy:dev    # Deploy to dev environment
npm run deploy:prod   # Deploy to prod environment
npm run diff:dev      # Show infrastructure diff
npm run synth:dev     # Synthesize CloudFormation
```

### Data Management
```bash
# Process whiskey data from external API
python scripts/fetch_whiskey_data.py --mode fetch --whiskeys 100
python scripts/fetch_whiskey_data.py --mode process --file raw_whiskey_data_YYYYMMDD_HHMMSS.json

# Check DynamoDB data
PAGER=cat AWS_PROFILE=dev aws dynamodb scan --table-name WhiskeySearch-dev --select COUNT
```

### Testing
```bash
# Backend tests
make test             # Run Django tests via Docker
./dev.sh test         # Alternative method

# Infrastructure tests
cd infra && npm test  # Run CDK tests

# Search functionality tests
curl "https://api.dev.whiskeybar.site/api/whiskeys/search/?q=bowmore"
curl "https://api.dev.whiskeybar.site/api/whiskeys/search/?q=%E3%83%9C%E3%82%A6%E3%83%A2%E3%82%A2"  # Japanese
```

## Architecture

### Serverless Microservices Architecture（費用最適化済み）
1. **Frontend (Nuxt.js SPA)**: Static files served via S3/CloudFront
2. **API (Lambda Functions)**: Serverless microservices behind API Gateway
3. **Data Layer**: DynamoDB for application data, Cognito for authentication
4. **Search Layer**: Dedicated WhiskeySearch table with multi-language support

### Key Infrastructure Components（全て従量課金）
- **VPC**: Multi-AZ with public/private subnets (**natGateways: 0** - 費用ゼロ)
- **Lambda**: Serverless compute platform for API（実行時のみ課金）
  - `whiskey-list-dev`: Whiskey listing
  - `whiskey-search-dev`: Multi-language search with manual filtering
  - `reviews-dev`: Review management
- **API Gateway**: RESTful API endpoint with CORS support（リクエスト従量）
- **S3**: Static site hosting + image storage（ストレージ従量）
- **CloudFront**: CDN for global content delivery（転送量従量）
- **DynamoDB**: NoSQL database - Pay per request（アクセス従量）
  - `Whiskeys-dev`: Basic whiskey data
  - `WhiskeySearch-dev`: Optimized search with English/Japanese names
  - `Reviews-dev`: User reviews
  - `Users-dev`: User profiles
- **Cognito**: User authentication + Google OAuth（MAU従量）
- **Route53**: DNS management with custom domains（クエリ従量）

### 費用削減済みリソース
- ❌ **NAT Gateway**: 削除済み（月額$30-45削減）
- ❌ **ALB**: 削除済み（月額$16-25削減）
- ❌ **ECS Fargate**: 削除済み（月額$15-50削減）
- ❌ **蒸留所検索機能**: 削除済み（GSI削減でコスト最適化）
- ✅ **総削減額**: 月額$60-120の大幅削減達成

### Environment Configuration
- **Local**: Docker Compose with LocalStack
- **Dev**: `dev.whiskeybar.site` + `api.dev.whiskeybar.site`
- **Prod**: `whiskeybar.site` + `api.whiskeybar.site`

## Search Architecture

### Multi-Language Search System
- **English Search**: Full text search in `name_en` field
- **Japanese Search**: Full text search in `name_ja` field with proper UTF-8 encoding
- **Search Method**: Manual filtering approach (DynamoDB `contains()` proved unreliable)
- **URL Encoding**: Japanese queries must be properly URL-encoded (e.g., `%E3%83%9C%E3%82%A6%E3%83%A2%E3%82%A2` for ボウモア)

### DynamoDB Table Structure

#### WhiskeySearch-dev Table
```json
{
  "id": "uuid",
  "name_en": "English whiskey name",
  "name_ja": "日本語ウイスキー名",
  "distillery_en": "English distillery name",
  "distillery_ja": "日本語蒸留所名",
  "normalized_name_en": "searchable english name",
  "normalized_name_ja": "検索可能な日本語名",
  "description": "Description",
  "region": "Region",
  "type": "Type",
  "created_at": "2025-06-29T...",
  "updated_at": "2025-06-29T..."
}
```

#### Global Secondary Indexes
- **NameJaIndex**: Partition key on `normalized_name_ja`
- **NameEnIndex**: Partition key on `normalized_name_en`
- ~~DistilleryJaIndex~~: 削除済み（蒸留所検索機能削除）
- ~~DistilleryEnIndex~~: 削除済み（蒸留所検索機能削除）

## Key File Locations

### Lambda Functions
- `lambda/whiskeys-search/index.py`: Multi-language search with manual filtering
- `lambda/whiskeys-list/index.py`: Whiskey listing functionality
- `lambda/reviews/index.py`: Review management

### Frontend Structure
- `frontend/nuxt.config.ts`: Nuxt configuration
- `frontend/composables/`: Vue composables for API calls
- `frontend/pages/`: Vue page components
- `frontend/layouts/default.vue`: Main layout with auth handling

### Data Processing
- `scripts/fetch_whiskey_data.py`: External API data fetching and translation
- `raw_whiskey_data_*.json`: Processed whiskey data files

### Infrastructure
- `infra/lib/whiskey-infra-stack.ts`: Main CDK stack definition
- `infra/config/environments.ts`: Environment-specific configurations

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
- **YOU MUST: 日本語検索時は適切なURLエンコーディングを使用**

### IMPORTANT（重要事項）：
- IMPORTANT: パフォーマンスへの影響を考慮
- IMPORTANT: 後方互換性を維持
- IMPORTANT: セキュリティベストプラクティスに従う
- IMPORTANT: 既にIaCでコード化されているインフラのリソースを変更する際はawsコマンドではなくIaCを使用する
- IMPORTANT: 既存のAWSリソースをCDKにインポートするのは禁止。常に新しいリソースを作成すること
- **IMPORTANT: 蒸留所検索機能は削除済み。名前のみの検索に特化**
- **IMPORTANT: 費用最適化されたアーキテクチャを維持する**
  - **使用推奨**: Lambda, API Gateway, S3, CloudFront, DynamoDB, Cognito
  - **VPC設定**: natGateways: 0 を維持（Lambdaは常にVPC外で実行）

## Authentication Flow

The application uses AWS Cognito for authentication:
1. Users can sign up/in with email or Google OAuth
2. Frontend receives JWT tokens (access, ID, refresh)
3. API validates JWT tokens via Cognito middleware
4. Automatic token refresh handled by frontend

## API Endpoints

### Search Endpoints
- `GET /api/whiskeys/search/?q={query}` - Multi-language whiskey search
- `GET /api/whiskeys/search/suggest/?q={query}` - Search suggestions
- `GET /api/whiskeys/suggest/?q={query}` - Direct suggestions endpoint

### Data Endpoints
- `GET /api/whiskeys/` - List whiskeys
- `GET /api/whiskeys/ranking/` - Whiskey rankings
- `POST /api/reviews/` - Create review
- `GET /api/reviews/` - List user reviews

### Search Examples
```bash
# English search
curl "https://api.dev.whiskeybar.site/api/whiskeys/search/?q=talisker"

# Japanese search (URL encoded)
curl "https://api.dev.whiskeybar.site/api/whiskeys/search/?q=%E3%83%9C%E3%82%A6%E3%83%A2%E3%82%A2"

# Empty query (returns up to 50 items)
curl "https://api.dev.whiskeybar.site/api/whiskeys/search/?q="
```

## Environment Variables

### Lambda Environment Variables
```bash
ENVIRONMENT=dev                                    # Environment name
WHISKEYS_TABLE=Whiskeys-dev                       # Basic whiskey table
WHISKEY_SEARCH_TABLE=WhiskeySearch-dev            # Search-optimized table
REVIEWS_TABLE=Reviews-dev                         # Reviews table
```

### Frontend (.env)
```bash
NUXT_PUBLIC_API_BASE_URL=https://api.dev.whiskeybar.site
NUXT_PUBLIC_USER_POOL_ID=ap-northeast-1_jEgeFKRCu
NUXT_PUBLIC_USER_POOL_CLIENT_ID=5iilnqou9ndfreukuk76533o0t
NUXT_PUBLIC_REGION=ap-northeast-1
```

## Data Management

### External Data Processing
1. **Fetch Data**: `python scripts/fetch_whiskey_data.py --mode fetch --whiskeys 100`
2. **Process & Translate**: `python scripts/fetch_whiskey_data.py --mode process --file raw_whiskey_data_*.json`
3. **Verification**: Check DynamoDB table counts and test search functionality

### Current Data Status
- **Total Records**: 768+ whiskey entries
- **Languages**: English and Japanese names/distilleries
- **Source**: TheWhiskyEdition.com API with AWS Translate enhancement
- **Search Coverage**: Full text search across both languages

## AWS Profile Configuration

**IMPORTANT**: When executing AWS CLI commands, always use the appropriate profile and set PAGER=cat:

### Development Environment
```bash
PAGER=cat AWS_PROFILE=dev aws [command]
```

Examples:
```bash
# Check Lambda logs
PAGER=cat AWS_PROFILE=dev aws logs tail /aws/lambda/whiskey-search-dev --follow

# Check DynamoDB tables
PAGER=cat AWS_PROFILE=dev aws dynamodb list-tables

# Deploy infrastructure
cd infra && AWS_PROFILE=dev npm run deploy:dev
```

## Troubleshooting

### Search Issues
1. **日本語検索が失敗**: URLエンコーディングを確認（`encodeURIComponent()`使用）
2. **文字化け**: Lambda関数でクエリが正しく受信されているかCloudWatchログで確認
3. **検索結果0件**: データの存在とテーブル名を確認

### Debug Commands
```bash
# Check search functionality
curl -s "https://api.dev.whiskeybar.site/api/whiskeys/search/?q=test" | jq .

# Check Lambda logs
PAGER=cat AWS_PROFILE=dev aws logs tail /aws/lambda/whiskey-search-dev --since 5m

# Check DynamoDB data
PAGER=cat AWS_PROFILE=dev aws dynamodb scan --table-name WhiskeySearch-dev --limit 1
```

### Common Issues
1. **CDK deployment failures**: DynamoDB GSI limitations (一度に1つのGSI変更のみ可能)
2. **Lambda function updates**: CDK経由でのコード更新推奨
3. **Search performance**: 手動フィルタリングは768件以下で最適化済み

Always run lint/typecheck commands after making changes, and test search functionality with both English and Japanese queries.