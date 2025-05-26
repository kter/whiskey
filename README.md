# Whiskey Tasting App

ウイスキーテイスティング記録アプリケーション

## 🏗️ アーキテクチャ

### インフラストラクチャ概要

```
┌─────────────────┐    ┌─────────────────┐
│   CloudFront    │    │      ALB        │
│   (Frontend)    │    │     (API)       │
└─────────┬───────┘    └─────────┬───────┘
          │                      │
          │                      │
┌─────────▼───────┐    ┌─────────▼───────┐
│       S3        │    │   ECS Fargate   │
│  (Static Files) │    │   (Django API)  │
└─────────────────┘    └─────────────────┘
          │                      │
          └──────────┬───────────┘
                     │
       ┌─────────────▼──────────────┐
       │         DynamoDB           │
       │     (Whiskeys/Reviews)     │
       └────────────────────────────┘
```

### ドメイン構成

**dev環境:**
- フロントエンド: `https://dev.whiskeybar.site`
- API: `https://api.dev.whiskeybar.site`

**prod環境:**
- フロントエンド: `https://whiskeybar.site`
- API: `https://api.whiskeybar.site`

### 主要AWSサービス

#### フロントエンド
- **S3**: 静的サイトホスティング
- **CloudFront**: CDN・SSL終端
- **Route53**: DNS・ドメイン管理

#### API
- **ECR**: Dockerイメージリポジトリ
- **ECS Fargate**: コンテナ実行環境
- **ALB**: ロードバランサー・SSL終端
- **Route53**: APIドメイン管理

#### 共通
- **DynamoDB**: NoSQLデータベース
- **Cognito**: ユーザー認証
- **VPC**: ネットワーク分離
- **IAM**: アクセス制御
- **Secrets Manager**: 機密情報管理

## 🚀 デプロイ手順

### 1. インフラストラクチャのデプロイ

```bash
# 開発環境
cd infra
npm run deploy:dev

# 本番環境（productionブランチから）
npm run deploy:prod
```

### 2. フロントエンドのデプロイ

GitHub Actionsで自動デプロイされます：
- `main`ブランチ → dev環境
- `production`ブランチ → prod環境

手動デプロイ：
```bash
./scripts/deploy.sh dev    # 開発環境
./scripts/deploy.sh prod   # 本番環境
```

### 3. APIのデプロイ

GitHub Actionsで自動デプロイされます：
- フロントエンドと並行して実行
- DockerイメージのビルドとECRプッシュ
- ECSサービスの更新

手動デプロイ：
```bash
./scripts/deploy-api.sh dev    # 開発環境
./scripts/deploy-api.sh prod   # 本番環境
```

## 📁 プロジェクト構成

```
whiskey/
├── frontend/          # Nuxt.js SPA
│   ├── components/    # Vueコンポーネント
│   ├── composables/   # Composition API
│   ├── pages/         # ページコンポーネント
│   └── plugins/       # プラグイン
├── backend/           # Django REST API
│   ├── api/           # APIアプリケーション
│   ├── backend/       # Django設定
│   └── Dockerfile     # 本番用Dockerファイル
├── infra/             # AWS CDK
│   ├── lib/           # CDKスタック定義
│   ├── config/        # 環境設定
│   └── scripts/       # デプロイスクリプト
├── scripts/           # 運用スクリプト
└── .github/
    └── workflows/     # GitHub Actions
```

## 🔧 開発環境

### 前提条件

- Node.js 18+
- Python 3.11+
- Docker & Docker Compose
- AWS CLI v2
- AWS CDK

### ローカル開発

```bash
# リポジトリクローン
git clone <repository-url>
cd whiskey

# 依存関係インストール
cd frontend && npm install
cd ../backend && pip install -r requirements.txt
cd ../infra && npm install

# ローカル環境起動
docker-compose up -d

# フロントエンド開発サーバー
cd frontend && npm run dev

# 別ターミナルでAPIサーバー
cd backend && python manage.py runserver
```

### 環境変数

#### フロントエンド (`frontend/.env`)
```bash
NUXT_PUBLIC_API_BASE_URL=http://localhost:8000
NUXT_PUBLIC_USER_POOL_ID=ap-northeast-1_xxxxxxxx
NUXT_PUBLIC_USER_POOL_CLIENT_ID=xxxxxxxxxxxxxxxxxxxxxxxxxx
NUXT_PUBLIC_REGION=ap-northeast-1
NUXT_PUBLIC_IMAGES_BUCKET=whiskey-images-dev
NUXT_PUBLIC_ENVIRONMENT=local
```

#### バックエンド (`backend/.env`)
```bash
ENVIRONMENT=local
DJANGO_DEBUG=True
AWS_ENDPOINT_URL=http://localhost:4566
DYNAMODB_WHISKEYS_TABLE=Whiskeys-local
DYNAMODB_REVIEWS_TABLE=Reviews-local
S3_IMAGES_BUCKET=whiskey-images-local
COGNITO_USER_POOL_ID=ap-northeast-1_xxxxxxxx
```

## 🔐 認証

### AWS Cognito + Amplify

- **ユーザープール**: メール/ユーザー名でのサインアップ
- **認証フロー**: SRP (Secure Remote Password)
- **トークン**: JWT（アクセス・ID・リフレッシュトークン）
- **セッション管理**: ローカルストレージ + 自動リフレッシュ

### 認証フロー

1. **サインアップ**: メール検証必須
2. **サインイン**: JWT トークン取得
3. **API呼び出し**: Authorization ヘッダーにアクセストークン
4. **自動リフレッシュ**: リフレッシュトークンで自動更新

## 📊 データモデル

### DynamoDB テーブル

#### Whiskeys テーブル
```json
{
  "id": "whiskey-uuid",
  "name": "Macallan 12",
  "distillery": "Macallan",
  "region": "Speyside",
  "created_at": "2024-01-01T00:00:00Z"
}
```

#### Reviews テーブル
```json
{
  "id": "review-uuid",
  "whiskey_id": "whiskey-uuid",
  "user_id": "user-uuid",
  "rating": 4.5,
  "notes": "テイスティングノート",
  "serving_style": "neat",
  "date": "2024-01-01",
  "image_url": "https://...",
  "created_at": "2024-01-01T00:00:00Z"
}
```

### GSI (Global Secondary Index)

- **WhiskeysTable**: `NameIndex` (name)
- **ReviewsTable**: `UserDateIndex` (user_id, date)

## 🎯 主な機能

### フロントエンド
- ✅ ウイスキー検索・選択
- ✅ レビュー記録（評価・ノート・写真）
- ✅ マイレビュー一覧
- ✅ ウイスキーランキング
- ✅ パブリックレビュー表示
- ✅ レスポンシブデザイン

### バックエンド API
- ✅ RESTful API (Django REST Framework)
- ✅ Cognito JWT認証
- ✅ DynamoDB操作
- ✅ S3画像アップロード
- ✅ ヘルスチェックエンドポイント
- ✅ CORS設定

### インフラ
- ✅ AWS CDK (TypeScript)
- ✅ 環境別デプロイ (dev/prod)
- ✅ カスタムドメイン・SSL
- ✅ CI/CD (GitHub Actions)
- ✅ セキュリティベストプラクティス

## 📈 モニタリング・ログ

### CloudWatch
- **ECS**: タスク・サービスメトリクス
- **ALB**: ヘルスチェック・レスポンス時間
- **DynamoDB**: リクエスト数・エラー率
- **CloudFront**: キャッシュヒット率

### ログ
- **Django**: 構造化ログ (JSON)
- **ECS**: コンテナログ
- **ALB**: アクセスログ

## 🛡️ セキュリティ

### HTTPS強制
- CloudFront・ALBでSSL終端
- HTTP → HTTPS リダイレクト
- HSTS ヘッダー設定

### CORS設定
- 環境別許可オリジン
- 資格情報付きリクエスト対応

### IAM最小権限
- ECSタスク用ロール
- GitHub Actions用ロール
- リソース別アクセス制御

## 🔄 CI/CD

### GitHub Actions ワークフロー

#### トリガー
- `main`ブランチ → dev環境
- `production`ブランチ → prod環境

#### 並行デプロイ
1. **Setup**: インフラ情報取得
2. **Frontend**: Nuxt.js ビルド・S3デプロイ
3. **API**: Docker ビルド・ECRプッシュ・ECS更新
4. **Notify**: デプロイ結果通知

### 手動デプロイ
```bash
# インフラ
cd infra && npm run deploy:dev

# フロントエンド
./scripts/deploy.sh dev

# API
./scripts/deploy-api.sh dev
```

## 🚨 トラブルシューティング

### 一般的な問題

#### 1. ECS タスクが起動しない
```bash
# ログ確認
aws logs get-log-events --log-group-name /ecs/whiskey-api-dev

# タスク定義確認
aws ecs describe-task-definition --task-definition whiskey-api-dev
```

#### 2. API が応答しない
```bash
# ヘルスチェック
curl https://api.dev.whiskeybar.site/health/

# ALB ターゲットグループ確認
aws elbv2 describe-target-health --target-group-arn <target-group-arn>
```

#### 3. 認証エラー
- Cognito ユーザープール設定確認
- JWT トークン期限確認
- CORS 設定確認

### ログ確認コマンド
```bash
# ECS ログ
aws logs tail /ecs/whiskey-api-dev --follow

# CloudFormation イベント
aws cloudformation describe-stack-events --stack-name WhiskeyApp-Dev

# ECS サービス状態
aws ecs describe-services --cluster whiskey-api-cluster-dev --services whiskey-api-service-dev
```

## 📋 今後の拡張予定

- [ ] ウイスキー詳細情報の充実
- [ ] ソーシャル機能（フォロー・いいね）
- [ ] 検索・フィルター機能の強化
- [ ] プッシュ通知
- [ ] モバイルアプリ（PWA）
- [ ] 管理者機能
- [ ] 分析・レポート機能

## 🤝 コントリビューション

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📄 ライセンス

This project is licensed under the MIT License.
