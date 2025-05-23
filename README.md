# Whiskey Log Application

ウィスキーのテイスティング記録を管理するWebアプリケーションです。

## 技術スタック

### Frontend
- **Nuxt.js 3** - Vue.js フレームワーク
- **TypeScript** - 型安全性
- **Tailwind CSS** - スタイリング
- **Pinia** - 状態管理

### Backend
- **Django** - Pythonウェブフレームワーク
- **Django REST Framework** - REST API
- **DynamoDB** - NoSQLデータベース
- **AWS Cognito** - 認証
- **AWS S3** - 画像ストレージ

### Infrastructure
- **Docker & Docker Compose** - 開発環境
- **LocalStack** - ローカルAWS環境

## 機能

- ウィスキーレビューの作成・編集・削除
- ウィスキー検索
- レビューランキング
- 画像アップロード
- ユーザー認証（AWS Cognito）

## ローカル開発環境のセットアップ

### 前提条件
- Docker
- Docker Compose

### 起動手順

1. リポジトリをクローン
```bash
git clone <repository-url>
cd whiskey
```

2. Docker Composeで起動
```bash
docker-compose up --build
```

3. アプリケーションにアクセス
- フロントエンド: http://localhost:3000
- バックエンドAPI: http://localhost:8000

### DynamoDBテーブル

LocalStackが起動時に以下のテーブルを自動作成します：

#### Whiskeys テーブル
- **id** (パーティションキー): ウィスキーID
- **name**: ウィスキー名
- **distillery**: 蒸留所
- **NameIndex** (GSI): 名前での検索用

#### Reviews テーブル
- **id** (パーティションキー): レビューID
- **whiskey_id**: ウィスキーID
- **user_id**: ユーザーID
- **rating**: 評価 (1-5)
- **notes**: レビューノート
- **serving_style**: 飲み方
- **date**: レビュー日
- **UserDateIndex** (GSI): ユーザーごとの日付順表示用

## 本番環境への展開

### 必要なAWSリソース

1. **DynamoDB**
   - Whiskeysテーブル
   - Reviewsテーブル

2. **AWS Cognito**
   - ユーザープール
   - アプリクライアント

3. **S3**
   - 画像ストレージ用バケット

### 環境変数

```bash
# Django設定
DJANGO_SECRET_KEY=your-secret-key
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=your-domain.com

# AWS設定
AWS_REGION=ap-northeast-1
AWS_S3_BUCKET=your-bucket-name
COGNITO_USER_POOL_ID=your-user-pool-id
COGNITO_CLIENT_ID=your-client-id

# フロントエンド設定
NUXT_PUBLIC_API_BASE=https://your-api-domain.com
NUXT_PUBLIC_AWS_REGION=ap-northeast-1
NUXT_PUBLIC_COGNITO_USER_POOL_ID=your-user-pool-id
NUXT_PUBLIC_COGNITO_CLIENT_ID=your-client-id
```

## API仕様

### Reviews API
- `GET /api/reviews/` - レビュー一覧取得
- `POST /api/reviews/` - レビュー作成
- `GET /api/reviews/{id}/` - レビュー詳細取得
- `PUT /api/reviews/{id}/` - レビュー更新
- `DELETE /api/reviews/{id}/` - レビュー削除

### Whiskeys API
- `GET /api/whiskeys/suggest/?q={query}` - ウィスキー検索
- `GET /api/whiskeys/ranking/` - ランキング取得

### Upload API
- `GET /api/s3/upload-url/` - S3アップロードURL取得

## 開発ツール

### テスト実行
```bash
# バックエンドテスト
docker-compose exec backend python manage.py test

# フロントエンドテスト
docker-compose exec frontend npm test
```

### リンター実行
```bash
# フロントエンド
docker-compose exec frontend npm run lint

# バックエンド
docker-compose exec backend flake8 .
```

## コスト最適化

PostgreSQLのRDSからDynamoDBに移行することで、以下のコスト削減を実現：

- RDS固定コストの削除
- オンデマンド課金（使用した分のみ）
- 小規模アプリケーションではほぼ無料
- サーバーレスアーキテクチャでスケーラブル

## ライセンス

MIT License
