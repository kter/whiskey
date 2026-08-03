# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Application Overview

This is a photo-first whiskey drink-log application built with a cost-optimized serverless architecture:
- **Frontend**: Nuxt.js 3 SPA (TypeScript, Tailwind CSS)
- **Backend**: Serverless Lambda functions with DynamoDB
- **Infrastructure**: AWS CDK (Lambda, API Gateway, S3, CloudFront, Cognito)
- **Authentication**: AWS Cognito with Google OAuth（フロントは **ID トークン**を送信）
- **Search**: Multi-language (English/Japanese) whiskey search
- **Drink Log** 🆕: 写真を撮るだけのテイスティング記録（画像→S3、Bedrock で銘柄/飲み方判別、GPS + Google Places で店名推定、履歴表示）
- **Data**: Rakuten API から Amazon Bedrock（`jp.anthropic.claude-sonnet-4-6`）で抽出したウイスキーデータ
- **Deployment**: CDK は手動（`infra/scripts/deploy.sh`）、CI はテスト + フロントデプロイ（`main` push、dev のみ）
- **Cost Savings**: サーバーレス化 + 原子カウンタ/スロットリングで Bedrock・Places・画像ストレージの費用に上界

## AWS Account Configuration

### Development Environment
- **AWS Account ID**: 031921999648
- **AWS Profile**: `dev`
- **Region**: ap-northeast-1

### Deployment Commands
CDK デプロイは**アカウント検証付きの `infra/scripts/deploy.sh` を通す**（生の `cdk deploy` は使わない）。
スタック順序・フラグ運用は `infra/README.md` のランブック参照。
```bash
cd infra
AWS_PROFILE=dev bash scripts/deploy.sh dev --base            # アプリスタック
AWS_PROFILE=dev bash scripts/deploy.sh dev --observability   # アラーム
AWS_PROFILE=dev bash scripts/deploy.sh dev --frontend        # フロント（generate + sync + invalidation）
AWS_PROFILE=dev bash scripts/deploy.sh dev --base --diff-only # 無変更ドライラン
```
> prd はスコープ外（アカウント確定後の別ブートストラップ）。

## Development Commands

### Local Development
```bash
# Frontend development (in frontend/)
npm run dev           # Start Nuxt dev server
npm run build         # Build for production
npm run lint          # Run ESLint
npm run lint:fix      # Fix ESLint issues

# Infrastructure (in infra/)
npm run build         # Compile TypeScript
npm run test          # Run CDK tests (jest)
npm run synth:dev     # Synthesize CloudFormation (lookup-free)
# デプロイは deploy.sh を使う（上記 Deployment Commands 参照）

# Lambda tests (repo root)
python -m pytest tests

# Local full stack（詳細は docs/LOCAL_DEV.md）
docker compose up -d   # DynamoDB Local(:8001) + MinIO(:9000/9001)
make local-init        # テーブル作成 + 銘柄シード
make api               # FastAPI アダプタ(:8000)
# フロントは frontend/ で npm run dev（localhost:3000 を使う）
```

### Data Management
```bash
# 🆕 Large-scale data processing with Bedrock (Claude Sonnet 4.6)
python scripts/fetch_rakuten_names_only.py  # Fetch 3,037 products from Rakuten
AWS_PROFILE=dev python scripts/extract_whiskey_names_claude_sonnet.py --input-file rakuten_product_names_*.json  # Extract with AI
AWS_PROFILE=dev python scripts/insert_whiskeys_to_dynamodb.py scripts/catalog/extracted_expressions.json --target dev  # Insert to verified dev

# Legacy method (archived)
python scripts/fetch_whiskey_data.py --mode fetch --whiskeys 100
python scripts/fetch_whiskey_data.py --mode process --file raw_whiskey_data_YYYYMMDD_HHMMSS.json

# Check DynamoDB data
PAGER=cat AWS_PROFILE=dev aws dynamodb scan --table-name WhiskeySearch-dev --select COUNT
PAGER=cat AWS_PROFILE=prd aws dynamodb scan --table-name WhiskeySearch-prd --select COUNT  # Production
```

### Testing
```bash
# Frontend tests
cd frontend && npm test  # Run Vitest tests

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
- **VPC なし**: 未使用の VPC は削除済み。Lambda は常に VPC 外で実行（NAT Gateway/ALB/EC2/ECS/RDS は不使用）
- **Lambda**: Serverless compute platform for API（実行時のみ課金）
  - `whiskey-list-dev` / `whiskey-search-dev`: 一覧・多言語検索（手動フィルタ）
  - `drink-logs-dev`: テイスティング記録 CRUD・presigned URL・画像サニタイズ
  - `drink-log-analyze-dev`: Bedrock で銘柄/飲み方判別（Converse）
  - `drink-log-places-dev`: Google Places 検索・表示時解決
  - `drink-log-reconciler-dev`: 孤児画像/未収束レコードの日次収束
- **API Gateway**: RESTful API endpoint with CORS support（リクエスト従量）
- **S3**: Static site hosting + image storage（ストレージ従量）
- **CloudFront**: CDN for global content delivery（転送量従量）
- **DynamoDB**: NoSQL database - Pay per request（アクセス従量）
  - `WhiskeySearch-dev`: Optimized search with English/Japanese names
  - `DrinkLogs-dev`: テイスティング記録（写真・銘柄・店・飲み方。GSI `UserDatetimeIndex`）
  - `AppState-dev`: 濫用/コスト防御の原子カウンタ（PK `pk`、TTL 有効）
  - ~~`Users-dev`~~: 廃止（プロフィールは Cognito 属性の読み取り専用表示）
  - ~~`Whiskeys-dev`~~: 廃止（`WhiskeySearch-dev` に統合）
- **Bedrock**: 画像から銘柄/飲み方を判別（`jp.amazon.nova-2-lite-v1:0` 既定 / Sonnet 4.6・Haiku 4.5 は切り戻し用、APAC 域内固定プロファイル、Converse API）
  - 2026-07-27 の実写真27枚によるエクスプレッション層の全文評価では、Nova/Haiku の銘柄名の音写が実用に耐えないと判断し、Sonnet 4.6 を既定にした
  - 2026-08-02 に現在の主指標であるブランド/蒸留所層で同じ27枚を dev 評価した結果、Nova 2 Lite は20件正解 / 誤り0件 / 未確定7件だった。Sonnet 4.6 より正解は4件少ないが、誤り0件で同等の安全性を示し、差は未確定に出たため Nova 2 Lite を既定に切り替えた
- **Cognito**: User authentication + Google OAuth（MAU従量）
- **Route53**: DNS management with custom domains（クエリ従量）

### Environment Configuration
- **Local**: Direct frontend development with npm
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
3. 書き込み・個人データ系は API Gateway の Cognito オーソライザーで検証。REST の
   Cognito オーソライザーは **ID トークン**を検証するため、フロントは `getToken()` で
   **ID トークン**を送る（`aud` == クライアントID、`token_use == 'id'` を多層検証）
4. Automatic token refresh handled by frontend

## API Endpoints

### Search Endpoints
- `GET /api/whiskeys/search/?q={query}` - Multi-language whiskey search
- `GET /api/whiskeys/search/suggest/?q={query}` - Search suggestions
- `GET /api/whiskeys/suggest/?q={query}` - Direct suggestions endpoint

### Data Endpoints
- `GET /api/whiskeys/` - List whiskeys

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

### Lambda Environment Variables（主なもの）
```bash
ENVIRONMENT=dev                                    # Environment name
WHISKEY_SEARCH_TABLE=WhiskeySearch-dev            # Search-optimized table
DRINKLOGS_TABLE=DrinkLogs-dev                      # Drink logs table
APP_STATE_TABLE=AppState-dev                       # Abuse/cost counters
IMAGES_BUCKET=whiskey-images-dev-<account>         # Drink log images bucket
BEDROCK_MODEL_ID=jp.amazon.nova-2-lite-v1:0        # Analyze model (allowlist gated)
```

### Frontend (.env)
```bash
NUXT_PUBLIC_API_BASE_URL=https://api.dev.whiskeybar.site
NUXT_PUBLIC_USER_POOL_ID=ap-northeast-1_xxxxxxxx
NUXT_PUBLIC_USER_POOL_CLIENT_ID=xxxxxxxxxxxxxxxxxxxxxxxxxx
NUXT_PUBLIC_REGION=ap-northeast-1
NUXT_PUBLIC_COGNITO_DOMAIN=<Cognito Hosted UI ホスト名>
NUXT_PUBLIC_GOOGLE_AUTH_ENABLED=1
NUXT_PUBLIC_ENVIRONMENT=dev
```

## Data Management

### External Data Processing
1. **Fetch**: `python scripts/fetch_rakuten_names_only.py`（楽天から商品名取得）
2. **Extract**: `AWS_PROFILE=dev python scripts/extract_whiskey_names_claude_sonnet.py --input-file rakuten_*.json`（Bedrock で構造化抽出。`--dry-run` で件数のみ確認可）
3. **Seed/Insert**: `python scripts/local/seed_whiskeys.py --target dev --profile dev`（厳選シード）/ `AWS_PROFILE=dev python scripts/insert_whiskeys_to_dynamodb.py <input.json> --target dev`（大規模投入）
4. **Verification**: DynamoDB のカウントと検索の動作確認（英語/日本語）

### Current Data Status
- **Languages**: English and Japanese names（名前検索に特化、蒸留所検索は削除済み）
- **Source**: 楽天市場API + Amazon Bedrock で抽出
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
