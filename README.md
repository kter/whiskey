# Whiskey Tasting App

ウイスキーテイスティング記録アプリケーション

## 🏗️ アーキテクチャ

### システム概要

```
┌─────────────────┐    ┌─────────────────┐
│   CloudFront    │    │   API Gateway   │
│   (Frontend)    │    │  (REST API)     │
└─────────┬───────┘    └─────────┬───────┘
          │                      │
          │                      │
┌─────────▼───────┐    ┌─────────▼───────┐
│       S3        │    │    Lambda       │
│  (Static SPA)   │    │  (Serverless)   │
└─────────────────┘    └─────────────────┘
          │                      │
          └──────────┬───────────┘
                     │
       ┌─────────────▼──────────────┐
       │         DynamoDB           │
       │    ウイスキーデータベース    │
       │     多言語検索対応        │
       └────────────────────────────┘
```

### 主要機能
- **813件** のウイスキーデータベース
- **多言語検索**: 英語・日本語対応
- **レビュー機能**: ユーザーレビュー・評価
- **認証**: AWS Cognito + Google OAuth

### ドメイン構成

**dev環境:**
- フロントエンド: `https://dev.whiskeybar.site`
- API: `https://api.dev.whiskeybar.site`

**prod環境:**
- フロントエンド: `https://whiskeybar.site`
- API: `https://api.whiskeybar.site`

### 使用技術

#### フロントエンド
- **Nuxt.js 3**: Vue.js SPAフレームワーク
- **TypeScript**: 型安全な開発
- **Tailwind CSS**: ユーティリティファーストCSS
- **S3 + CloudFront**: 静的サイトホスティング

#### バックエンド API
- **Lambda Functions**: サーバーレスAPI
  - `whiskey-search`: 多言語検索API
  - `whiskey-list`: ウイスキー一覧API  
  - `reviews`: レビュー管理API
- **API Gateway**: RESTful API
- **Python**: Lambda実行環境

#### データベース・認証
- **DynamoDB**: NoSQLデータベース
  - `WhiskeySearch`: 検索最適化テーブル
  - `Reviews`: ユーザーレビュー
  - `Users`: ユーザープロファイル
- **AWS Cognito**: ユーザー認証・Google OAuth
- **Secrets Manager**: 機密情報管理

#### インフラ・デプロイ
- **AWS CDK**: Infrastructure as Code
- **GitHub Actions**: CI/CD
- **Docker**: 開発環境

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

### 3. Lambda関数のデプロイ

CDKによる自動デプロイ：
- Lambdaコードは CDK内で自動パッケージング
- API Gateway統合も自動設定
- 環境変数・IAM権限も自動構成

### 4. データ管理（必要に応じて）

#### Python環境のセットアップ

##### 仮想環境の作成
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r scripts/requirements.txt
```

##### 楽天APIの設定
```bash
export RAKUTEN_APP_ID="your_rakuten_api_key"
```

##### スクリプトの実行
```bash
python3 scripts/fetch_rakuten_names_only.py --max-items 500
```

```bash
# 楽天APIからデータ取得
python scripts/fetch_rakuten_names_only.py

# AI抽出でウイスキー名抽出
python scripts/extract_whiskey_names_nova_lite.py --input-file rakuten_product_names_*.json

# DynamoDBに投入
ENVIRONMENT=dev python scripts/insert_whiskeys_to_dynamodb.py nova_lite_extraction_results_*.json
```

## 📁 プロジェクト構成

```
whiskey/
├── frontend/          # Nuxt.js SPA
│   ├── components/    # Vueコンポーネント
│   ├── composables/   # Composition API（多言語検索対応）
│   ├── pages/         # ページコンポーネント
│   └── plugins/       # プラグイン
├── lambda/            # サーバーレスAPI
│   ├── whiskeys-search/  # 多言語検索Lambda
│   ├── whiskeys-list/    # ウイスキー一覧Lambda
│   ├── reviews/          # レビュー管理Lambda
│   └── common/           # 共通ライブラリ
├── infra/             # AWS CDK
│   ├── lib/           # CDKスタック定義
│   ├── config/        # 環境設定
│   └── scripts/       # デプロイスクリプト
├── scripts/           # データ管理・運用スクリプト
│   ├── extract_whiskey_names_nova_lite.py  # AI抽出
│   ├── insert_whiskeys_to_dynamodb.py      # DB投入
│   └── fetch_rakuten_names_only.py         # データ取得
└── .github/
    └── workflows/     # GitHub Actions CI/CD
```

## 🔧 開発環境

### 前提条件

- Node.js 18+
- Python 3.11+
- AWS CLI v2
- AWS CDK

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
- ✅ RESTful API (API Gateway)
- ✅ Cognito JWT認証
- ✅ DynamoDB操作
- ✅ S3画像アップロード
- ✅ CORS設定

### インフラ
- ✅ AWS CDK (TypeScript)
- ✅ 環境別デプロイ (dev/prod)
- ✅ カスタムドメイン・SSL
- ✅ CI/CD (GitHub Actions)
- ✅ セキュリティベストプラクティス

## 📈 モニタリング・ログ

### CloudWatch
- **DynamoDB**: リクエスト数・エラー率
- **CloudFront**: キャッシュヒット率

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
```

## 🚨 トラブルシューティング

#### 3. 認証エラー
- Cognito ユーザープール設定確認
- JWT トークン期限確認
- CORS 設定確認

# CloudFormation イベント
aws cloudformation describe-stack-events --stack-name WhiskeyApp-Dev

## 🤝 コントリビューション

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📄 ライセンス

This project is licensed under the MIT License.
