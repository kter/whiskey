# Whiskey Tasting App

ウイスキーテイスティング記録アプリケーション - 大規模データ検索対応サーバーレスアーキテクチャ

## 🏗️ アーキテクチャ

### サーバーレス・マイクロサービス概要（費用最適化済み）

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
       │  (813件+ウイスキーデータ)   │
       │   多言語検索・高速応答     │
       └────────────────────────────┘
```

### 🆕 大規模データ対応
- **813件** の本格ウイスキーデータ（楽天API × Nova Lite抽出）
- **多言語対応**: 英語・日本語での高精度検索
- **コスト最適化**: 全サーバーレス・従量課金アーキテクチャ

### ドメイン構成

**dev環境:**
- フロントエンド: `https://dev.whiskeybar.site`
- API: `https://api.dev.whiskeybar.site`

**prod環境:**
- フロントエンド: `https://whiskeybar.site`
- API: `https://api.whiskeybar.site`

### 主要AWSサービス（全て従量課金）

#### フロントエンド
- **S3**: 静的サイトホスティング（ストレージ従量）
- **CloudFront**: CDN・SSL終端（転送量従量）
- **Route53**: DNS・ドメイン管理（クエリ従量）

#### API (サーバーレス)
- **Lambda**: マイクロサービス実行環境（実行時のみ課金）
  - `whiskey-search`: 多言語検索API
  - `whiskey-list`: ウイスキー一覧API  
  - `reviews`: レビュー管理API
- **API Gateway**: RESTful API（リクエスト従量）

#### データ・認証
- **DynamoDB**: NoSQLデータベース（アクセス従量）
  - `WhiskeySearch-prd`: 813件検索最適化データ
  - `Reviews-prd`: ユーザーレビュー
  - `Users-prd`: ユーザープロファイル
- **Cognito**: ユーザー認証（MAU従量）
- **Secrets Manager**: 機密情報管理

#### 🚫 削除済み高額リソース
- ❌ **NAT Gateway**: 削除済み（月額$30-45削減）
- ❌ **Application Load Balancer**: 削除済み（月額$16-25削減）
- ❌ **ECS Fargate**: 削除済み（月額$15-50削減）
- ✅ **総削減額**: 月額$60-120の大幅削減達成

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

### 3. Lambda関数のデプロイ

CDKによる自動デプロイ：
- Lambdaコードは CDK内で自動パッケージング
- API Gateway統合も自動設定
- 環境変数・IAM権限も自動構成

### 4. 大規模データ投入（本番環境）

```bash
# 楽天APIからデータ取得（3,037商品）
python scripts/fetch_rakuten_names_only.py

# Nova Liteでウイスキー名抽出
python scripts/extract_whiskey_names_nova_lite.py --input-file rakuten_product_names_*.json

# 本番DynamoDBに投入
ENVIRONMENT=prd python scripts/insert_whiskeys_to_dynamodb.py nova_lite_extraction_results_*.json
```

**実績: 813件のウイスキーデータを本番投入済み**

## 📁 プロジェクト構成

```
whiskey/
├── frontend/          # Nuxt.js SPA
│   ├── components/    # Vueコンポーネント
│   ├── composables/   # Composition API（多言語検索対応）
│   ├── pages/         # ページコンポーネント
│   └── plugins/       # プラグイン
├── lambda/            # サーバーレスAPI
│   ├── whiskeys-search/  # 多言語検索Lambda（メイン）
│   ├── whiskeys-list/    # ウイスキー一覧Lambda
│   ├── reviews/          # レビュー管理Lambda
│   └── common/           # 共通ライブラリ
├── backend/           # 旧Django（開発用・移行済み）
│   └── api/           # DynamoDBサービス（スクリプトで利用）
├── infra/             # AWS CDK
│   ├── lib/           # CDKスタック定義（サーバーレス）
│   ├── config/        # 環境設定
│   └── scripts/       # デプロイスクリプト
├── scripts/           # データ管理・運用スクリプト
│   ├── archive/       # 過去の手法（アーカイブ済み）
│   ├── extract_whiskey_names_nova_lite.py  # Nova Lite抽出
│   ├── insert_whiskeys_to_dynamodb.py      # DynamoDB投入
│   └── fetch_rakuten_names_only.py         # 楽天API取得
└── .github/
    └── workflows/     # GitHub Actions（サーバーレス対応）
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

### 緊急時の対応

#### ECR認証エラー
GitHub ActionsでECR権限エラーが発生した場合：
```bash
# 緊急修正スクリプトを実行
./deploy-fix.sh
```

詳細なトラブルシューティングについては [`TROUBLESHOOTING.md`](./TROUBLESHOOTING.md) を参照してください。

### 一般的な問題

#### 1. ECS タスクが起動しない
```bash
# ログ確認
aws logs tail /ecs/whiskey-api-dev --follow

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

### 短期（3ヶ月）
- [ ] ウイスキー詳細情報の充実（年数・アルコール度数等）
- [ ] 検索フィルター機能（地域・タイプ・価格帯）
- [ ] お気に入り機能
- [ ] 上級者向け検索（カスクタイプ・蒸留年等）

### 中期（6ヶ月）  
- [ ] ソーシャル機能（フォロー・いいね・コメント）
- [ ] ウイスキー推奨エンジン（AI活用）
- [ ] プッシュ通知（新着レビュー等）
- [ ] 管理者機能（データ管理・ユーザー管理）

### 長期（1年）
- [ ] モバイルアプリ（PWA）
- [ ] 分析・レポート機能（テイスティング傾向等）
- [ ] バーベル連携（在庫情報・価格比較）
- [ ] 多言語拡張（中国語・韓国語等）

### 🆕 技術的改善
- [ ] GraphQL API導入検討
- [ ] Edge Computing最適化
- [ ] AI活用テイスティングノート自動生成
- [ ] AR/VRテイスティング体験

## 🤝 コントリビューション

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📄 ライセンス

This project is licensed under the MIT License.
