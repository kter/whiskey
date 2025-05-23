# Whiskey Log Application

ウィスキーのテイスティング記録とレビューを管理するWebアプリケーションです。

## 特徴

- **ウィスキー一覧表示**: 評価順にソートされたウィスキーの表示
- **レビュー機能**: ウィスキーのテイスティングノートと評価の記録
- **ランキング機能**: 平均評価によるウィスキーランキング
- **認証システム**: ユーザー管理機能（予定）
- **データ永続化**: LocalStackのボリュームマウントによるデータ保存

## 技術スタック

### フロントエンド
- **Nuxt.js 3**: Vue.js 3ベースのフレームワーク
- **Tailwind CSS**: ユーティリティファーストのCSSフレームワーク
- **TypeScript**: 静的型付けによる開発効率向上

### バックエンド
- **Django 5.2**: Python Webフレームワーク
- **Django REST Framework**: RESTful API構築
- **DynamoDB**: NoSQLデータベース（AWS DynamoDB互換）

### インフラ
- **Docker & Docker Compose**: コンテナ化とオーケストレーション
- **LocalStack**: AWS DynamoDBのローカル環境エミュレーション
- **永続化ボリューム**: データの永続保存

## セットアップ

### 前提条件
- Docker
- Docker Compose

### 起動方法

1. **リポジトリのクローン**
```bash
git clone <repository-url>
cd whiskey
```

2. **コンテナの起動**
```bash
docker-compose up -d
```

3. **DynamoDBテーブルの作成**
```bash
# Whiskeysテーブル
docker-compose exec localstack awslocal dynamodb create-table \
  --table-name Whiskeys \
  --attribute-definitions AttributeName=id,AttributeType=S AttributeName=name,AttributeType=S \
  --key-schema AttributeName=id,KeyType=HASH \
  --global-secondary-indexes "IndexName=NameIndex,KeySchema=[{AttributeName=name,KeyType=HASH}],Projection={ProjectionType=ALL}" \
  --billing-mode PAY_PER_REQUEST \
  --region ap-northeast-1

# Reviewsテーブル  
docker-compose exec localstack awslocal dynamodb create-table \
  --table-name Reviews \
  --attribute-definitions AttributeName=id,AttributeType=S AttributeName=user_id,AttributeType=S AttributeName=date,AttributeType=S \
  --key-schema AttributeName=id,KeyType=HASH \
  --global-secondary-indexes "IndexName=UserDateIndex,KeySchema=[{AttributeName=user_id,KeyType=HASH},{AttributeName=date,KeyType=RANGE}],Projection={ProjectionType=ALL}" \
  --billing-mode PAY_PER_REQUEST \
  --region ap-northeast-1
```

4. **サンプルデータの投入**
```bash
./scripts/init_data.sh
```

### アクセス
- **フロントエンド**: http://localhost:3000
- **バックエンドAPI**: http://localhost:8000/api/

## データ永続化

このアプリケーションはLocalStackのボリュームマウント機能を使用してデータを永続化しています。

### 永続化の仕組み
- LocalStackのデータは `./data/localstack` ディレクトリにマウントされます
- コンテナの再起動後もデータが保持されます
- `PERSISTENCE=1` 環境変数により永続化が有効になります

### 永続化のテスト
```bash
# データの確認
curl http://localhost:8000/api/whiskeys/ranking/

# LocalStackの再起動
docker-compose restart localstack

# データが保持されているか確認（5秒後）
sleep 5 && curl http://localhost:8000/api/whiskeys/ranking/
```

## API エンドポイント

### ウィスキー関連
- `GET /api/whiskeys/ranking/` - ウィスキーランキング取得
- `GET /api/whiskeys/suggest/?q=<query>` - ウィスキー検索

### レビュー関連
- `GET /api/reviews/public/` - パブリックレビュー一覧（認証不要）
- `GET /api/reviews/` - ユーザーのレビュー一覧（認証必要）
- `POST /api/reviews/` - レビュー作成（認証必要）
- `GET /api/reviews/<id>/` - レビュー詳細取得
- `PUT /api/reviews/<id>/` - レビュー更新（認証必要）
- `DELETE /api/reviews/<id>/` - レビュー削除（認証必要）

## サンプルデータ

初期化スクリプトには以下のデータが含まれています：

### ウィスキー（8件）
- 山崎12年, 白州12年, 余市15年
- 響21年, 宮城峡15年, 知多
- 竹鶴17年, 富士山麓

### レビュー（10件）
- 各ウィスキーに対する詳細なテイスティングノート
- 評価（1-5段階）と飲み方の記録

## 開発者向け情報

### ディレクトリ構造
```
whiskey/
├── frontend/          # Nuxt.js アプリケーション
├── backend/           # Django アプリケーション
├── localstack/        # LocalStack初期化スクリプト
├── scripts/           # ユーティリティスクリプト
├── data/              # 永続化データディレクトリ
└── docker-compose.yml # Docker Compose設定
```

### ログの確認
```bash
# 全サービスのログ
docker-compose logs -f

# 特定のサービスのログ
docker-compose logs -f frontend
docker-compose logs -f backend
docker-compose logs -f localstack
```

### コンテナの状態確認
```bash
docker-compose ps
```

## トラブルシューティング

### データが表示されない場合
1. コンテナが正常に起動しているか確認
2. DynamoDBテーブルが作成されているか確認
3. サンプルデータが投入されているか確認

### LocalStackの問題
```bash
# LocalStackの再起動
docker-compose restart localstack

# LocalStackのヘルスチェック
curl http://localhost:4566/_localstack/health
```

## ライセンス

MIT License
