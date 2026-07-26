# Whiskey Log

**写真を撮るだけの飲酒ログ**に一本化したウイスキー記録アプリケーション。
画像から銘柄と飲み方をAIが判別し、位置情報から店名候補を提案して、タイムラインで振り返れる。
銘柄の英語・日本語検索も備えた、費用最適化されたサーバーレス構成。

## 🏗️ アーキテクチャ

```
┌─────────────────┐        ┌─────────────────┐
│   CloudFront    │        │   API Gateway   │
│  (静的SPA配信)   │        │   (REST API)    │
└────────┬────────┘        └────────┬────────┘
         │                          │
┌────────▼────────┐        ┌────────▼────────┐
│       S3        │        │     Lambda       │
│  (静的SPA/画像)  │        │  (Python 関数群) │
└─────────────────┘        └────────┬────────┘
                                    │
     ┌──────────────┬──────────────┼───────────────┐
     │              │              │               │
┌────▼────┐  ┌──────▼─────┐  ┌─────▼─────┐  ┌──────▼──────┐
│DynamoDB │  │  Cognito   │  │  Bedrock  │  │Google Places│
│(各テーブル)│ │(認証/OAuth) │ │(Nova Lite) │  │  (店名推定)  │
└─────────┘  └────────────┘  └───────────┘  └─────────────┘
```

**コスト方針**: NAT Gateway / ALB / EC2 / ECS Fargate / RDS は使用しない（全て従量課金の
サーバーレス）。VPC は `natGateways: 0`、DynamoDB は pay-per-request。

### 主要機能
- **多言語ウイスキー検索**: 楽天市場API + Amazon Bedrock Nova Lite で抽出したデータを英語/日本語で検索
- **フォトファースト飲酒ログ**: 写真アップロード → Bedrock で銘柄・飲み方を自動判別 →
  GPS + Google Places で店名候補を提案 → タイムラインで閲覧・編集・削除
- **認証**: AWS Cognito（メール/パスワード + Google OAuth）

### ドメイン構成

| 環境 | フロントエンド | API |
|------|---------------|-----|
| dev  | `https://dev.whiskeybar.site` | `https://api.dev.whiskeybar.site` |
| prd  | `https://whiskeybar.site`（**未展開・別計画**） | `https://api.whiskeybar.site` |

> prd はアカウント確定後に別ブートストラップで展開する。現状のスコープは dev のみ。

### 使用技術

- **フロントエンド**: Nuxt.js 3 (Vue 3 SPA / TypeScript / Tailwind CSS) → S3 + CloudFront で静的配信
- **バックエンド**: Python Lambda（Docker バンドリング + `whiskey_common` 共有レイヤー）+ API Gateway (REST)
- **データ/認証**: DynamoDB、Cognito、Secrets Manager
- **AI**: Amazon Bedrock（`jp.amazon.nova-2-lite-v1:0` 既定 / `jp.anthropic.claude-haiku-4-5` フォールバック、Converse API、APAC 域内固定プロファイル）
- **店名推定**: Google Places API (New) searchNearby / Place Details
- **インフラ**: AWS CDK (TypeScript) / GitHub Actions (CI + フロントデプロイ)

## 📊 データモデル（DynamoDB）

| テーブル | 用途 | 主なキー / GSI |
|----------|------|----------------|
| `WhiskeySearch-{env}` | ウイスキー検索データ（英語/日本語名） | PK `id` / `NameIndex` |
| `DrinkLogs-{env}` | 飲酒ログ（写真・銘柄・店・飲み方） | PK `id` / `UserDatetimeIndex`(user_id,datetime) |
| `AppState-{env}` | 濫用/コスト防御の原子カウンタ | PK `pk`（TTL 有効） |

> `Users` テーブルは廃止（プロフィールは Cognito 属性の読み取り専用表示）。
> 蒸留所検索は削除済み（名前検索に特化、`DistilleryIndex` なし）。

### 主なアイテム形状（抜粋）

```jsonc
// DrinkLogs（GPS座標とGoogle表示名は保存しない）
{ "id": "...", "user_id": "...", "status": "complete", "datetime": "2026-07-01T12:00:00.000Z",
  "s3_image_key": "logs/{user}/{uuid}.jpg", "whiskey_id": "...", "brand_text": "タリスカー",
  "brand_source": "ai|matched|manual", "serving_style": "NEAT",
  "store": { "name": "自由入力の店名", "place_id": "ChIJ..." } }
```

## 🖥️ Lambda 関数

| 関数 | 役割 |
|------|------|
| `whiskey-search-{env}` | 多言語検索（手動フィルタ + ページネーション） |
| `whiskey-list-{env}` | ウイスキー一覧 |
| `drink-logs-{env}` | 飲酒ログ CRUD・presigned URL・画像サニタイズ |
| `drink-log-analyze-{env}` | Bedrock で銘柄/飲み方判別（Converse） |
| `drink-log-places-{env}` | Google Places 検索・表示時解決 |
| `drink-log-reconciler-{env}` | 孤児画像・未収束レコードの日次収束 |

## 🔐 認証

- **AWS Cognito + Amplify**（SRP / Google OAuth code flow、`USER_PASSWORD_AUTH` 無効、ユーザー存在秘匿）
- **トークン**: API Gateway の Cognito オーソライザー検証に合わせ、フロントは **ID トークン**を送信
  （`aud` == クライアントID、`token_use == 'id'` を多層で検証）
- 公開読み取り（銘柄一覧・検索）は認証不要、飲酒ログは要認証

## 🚀 デプロイ

### インフラ（CDK・手動）

CDK デプロイは**アカウント検証付きの `infra/scripts/deploy.sh` を通す**（生の `cdk deploy` は使わない）。
スタックの順序・フラグ運用は [`infra/README.md`](infra/README.md) のランブックを参照。

```bash
cd infra
AWS_PROFILE=dev bash scripts/deploy.sh dev --base            # アプリスタック
AWS_PROFILE=dev bash scripts/deploy.sh dev --observability   # アラーム
AWS_PROFILE=dev bash scripts/deploy.sh dev --frontend        # フロント（出力→.env→generate→sync→invalidation）
AWS_PROFILE=dev bash scripts/deploy.sh dev --base --diff-only # 無変更ドライラン
```

### フロントエンド（CI・自動）

`main` への push で GitHub Actions がテスト後にフロントエンドを dev へデプロイする（下記 CI/CD 参照）。

### データ投入

```bash
python scripts/fetch_rakuten_names_only.py                                   # 楽天から商品名取得
python scripts/extract_whiskey_names_nova_lite.py --input-file rakuten_*.json # Bedrock Nova Lite で抽出
python scripts/local/seed_whiskeys.py --target dev                           # 厳選シードを投入
```

## 🧪 ローカル開発

Docker のローカルスタック（DynamoDB Local + MinIO）+ FastAPI アダプタで、AWS に触れず全機能を動かせる。
詳細は [`docs/LOCAL_DEV.md`](docs/LOCAL_DEV.md)。

```bash
docker compose up -d          # DynamoDB Local(:8001) + MinIO(:9000/9001)
make local-init               # テーブル作成 + 銘柄シード
make api                      # FastAPI アダプタ(:8000、Lambda ハンドラを import)
cd frontend && npm run dev     # Nuxt dev(:3000)  ※ localhost:3000 を使うこと
```

### 前提条件
- Node.js 22+ / Python 3.11+ / AWS CLI v2 / AWS CDK / Docker

### フロントエンド環境変数（`frontend/.env`）
```bash
NUXT_PUBLIC_API_BASE_URL=https://api.dev.whiskeybar.site
NUXT_PUBLIC_USER_POOL_ID=ap-northeast-1_xxxxxxxx
NUXT_PUBLIC_USER_POOL_CLIENT_ID=xxxxxxxxxxxxxxxxxxxxxxxxxx
NUXT_PUBLIC_REGION=ap-northeast-1
NUXT_PUBLIC_COGNITO_DOMAIN=<Cognito Hosted UI ホスト名>
NUXT_PUBLIC_GOOGLE_AUTH_ENABLED=1
NUXT_PUBLIC_ENVIRONMENT=dev
# ローカルのみ: NUXT_PUBLIC_MOCK_AUTH=1（モック認証、import.meta.dev と併用時のみ有効）
```

## 📁 プロジェクト構成

```
whiskey/
├── frontend/            # Nuxt.js SPA（pages/logs で飲酒ログ、composables で API クライアント）
├── lambda/              # Python Lambda 群
│   ├── whiskeys-search/ whiskeys-list/
│   ├── drink-logs/      # CRUD + reconciler.py
│   ├── drink-log-analyze/  # index.py(Bedrock) + places.py(Places)
│   └── common/python/whiskey_common/  # 共有レイヤー（logger/responses/jwt_utils/images/clients）
├── infra/               # AWS CDK（lib/ スタック, config/ 環境, scripts/deploy.sh, test/ jest）
├── local_api/           # ローカル FastAPI アダプタ
├── scripts/             # データ管理 + scripts/local/（seed, init_tables）
├── tests/               # Lambda の pytest
└── .github/workflows/   # CI + フロントデプロイ
```

## 🔄 CI/CD（GitHub Actions）

`.github/workflows/deploy.yml`（`main` の PR / push で起動）。third-party アクションは commit SHA に
ピン止め、Dependabot（`.github/dependabot.yml`）で追随。

- **`ci`**（PR + push、AWS 認証情報なし）: `pytest`（Lambda）/ `npm ci`+`build`+`jest`+`cdk synth`（infra）
  / `lint`+`typecheck`+`vitest`+`generate`（frontend）
- **`setup` / `deploy-frontend`**（**push のみ** + `needs: ci`）: OIDC ロールを引き受け、スタック出力から
  `.env` を生成してフロントを dev へ deploy（S3 sync + CloudFront invalidation）
- OIDC trust は `repo:kter/whiskey:environment:dev` に限定、CI ロールは S3 sync / CloudFront invalidation /
  CloudFormation 読み取りのみ
- **CDK インフラのデプロイは手動維持**（`infra/scripts/deploy.sh`）。prd はスコープ外

## 🛡️ セキュリティ

- **HTTPS 強制**: CloudFront で SSL 終端 + HSTS、S3 バケットは `enforceSSL`（非TLS拒否）
- **CORS**: 環境別許可オリジン（静的単一オリジン、ワイルドカード反射なし）、Lambda 応答は `Vary: Origin`
- **IAM 最小権限**: 関数ごとにロール分割、AppState は「アクション × LeadingKeys プレフィックス」で相互隔離
- **プライバシー**: 画像は EXIF/GPS を除去して再エンコード、GPS 座標と Google 表示名は永続化しない、
  presigned URL 経由の画像は `private, no-store`
- **濫用/コスト防御**: AppState の原子カウンタ（日次/月次）で Bedrock・Places・画像ストレージの上界を固定、
  API Gateway メソッドスロットリング、AWS Budgets 通知

## 🚨 トラブルシューティング

```bash
# 検索の動作確認
curl -s "https://api.dev.whiskeybar.site/api/whiskeys/search/?q=talisker" | jq .

# Lambda ログ
PAGER=cat AWS_PROFILE=dev aws logs tail /whiskey/dev/drink-log-analyze --since 5m

# CloudFormation イベント
PAGER=cat AWS_PROFILE=dev aws cloudformation describe-stack-events --stack-name WhiskeyApp-Dev
```

## 🤝 コントリビューション

1. フィーチャーブランチを作成（`git checkout -b feature/...`）
2. 変更をコミット（`main` への直コミットは禁止）
3. Pull Request を作成（CI が自動実行される）

## 📄 ライセンス

MIT License.
