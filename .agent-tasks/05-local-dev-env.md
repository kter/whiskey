# Task 05: ローカル開発環境（docker-compose + FastAPI アダプタ + シード）

## Goal

フルスタックをローカルで起動可能にする: DynamoDB Local + MinIO + Lambda ハンドラを包む FastAPI アダプタ + テーブル初期化/シード + Makefile。**新規ファイル中心。lambda/ 本体は原則変更しない**（ローカル対応で必要な軽微修正のみ可）。

## 背景（必読）

- タスク01〜04適用済み前提: レイヤー `whiskey_common`（clients.py が `AWS_ENDPOINT_URL_DYNAMODB` / `AWS_ENDPOINT_URL_S3` を尊重）、認証は authorizer claims or jwt_utils、AppState テーブル、ランキングは集計 Lambda（whiskeys-search はキャッシュ読み取り専用）。
- フロント側にはモック認証の受け皿（`NUXT_PUBLIC_MOCK_AUTH=1` + import.meta.dev）が実装済み。

## 変更対象（新規作成）

- `docker-compose.yml`（ルート）
- `local_api/main.py` + `local_api/requirements.txt`
- `scripts/local/init_tables.py` / `scripts/local/seed_whiskeys.py` / `scripts/local/seed_data/whiskeys.json`
- `Makefile`（ルート）
- `docs/LOCAL_DEV.md`
- `.gitignore`（seed_data の例外1行のみ）

## 要求仕様

### 1. docker-compose.yml
- `dynamodb-local`（ホスト `127.0.0.1:8001` → コンテナ 8000、`-sharedDb`）+ `minio`（`127.0.0.1:9000`/`127.0.0.1:9001`、`MINIO_API_CORS_ALLOW_ORIGIN=http://localhost:3000`）+ バケット初期化ワンショット（mc で `whiskey-images-local` 作成）。
- **全ポートは `127.0.0.1:host:container` 形式で loopback 限定**。
- **イメージタグは不変バージョン固定**（`latest` 禁止）。
- healthcheck + `depends_on: condition: service_healthy` で起動順を安定化。

### 2. ローカル資格情報・リージョン
- 単一ペア（例: `minioadmin` / `minioadmin`）を MinIO ルート資格情報と boto3 用 `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` の両方に使用（DynamoDB Local は任意の資格情報を受理）。
- `AWS_REGION`/`AWS_DEFAULT_REGION=ap-northeast-1` と `AWS_EC2_METADATA_DISABLED=true` を Makefile/compose で固定。
- **dev AWS プロファイルへの暗黙フォールバック禁止**（プロファイル無し環境での起動テストを受入に含む）。
- **グローバル `AWS_ENDPOINT_URL` は設定しない**。`AWS_ENDPOINT_URL_DYNAMODB=http://127.0.0.1:8001` / `AWS_ENDPOINT_URL_S3=http://127.0.0.1:9000` を使用。

### 3. FastAPI アダプタ（local_api/main.py）
- ポート 8000、**uvicorn は 127.0.0.1 に bind**、`redirect_slashes=False`（パスは末尾スラッシュなしで API GW Resource 定義と一致）。
- swagger.yml のルートをミラーし、HTTP ↔ API Gateway proxy イベント変換（path/query/headers/body/requestContext）。
- **importlib.util.spec_from_file_location で一意モジュール名ロード**（全ハンドラが index.py 同名 + ディレクトリ名ハイフンのため通常 import 不可）。**ロード前に `lambda/common/python` と各関数ディレクトリを sys.path に明示追加**。リポジトリルートからの cold-import テスト付き。
- **Lambda context スタブ**: `get_remaining_time_in_millis()`（deadline ベース）+ `aws_request_id` を提供。
- FastAPI `CORSMiddleware`（`http://localhost:3000`）で OPTIONS 応答。
- **認証モードは相互排他**: `MOCK_AUTH=1` なら authorizer claims（`sub`=固定テストユーザー / `aud`=`local-client` / `token_use`=`id`）を注入。それ以外は実 JWT 検証モード（claims 注入なし、jwt_utils が dev Cognito に対して検証 — `COGNITO_USER_POOL_ID`/`COGNITO_CLIENT_ID` は環境変数から）。`COGNITO_CLIENT_ID=local-client` を MOCK 時に設定。
- 環境変数: `ENVIRONMENT=local`、テーブル名（`*-local`）、`ALLOWED_ORIGINS=http://localhost:3000`、`MOCK_AI`/`MOCK_PLACES` パススルー（実装は Phase 4 — 現時点では未使用でよい）。
- `local_api/requirements.txt`: FastAPI / uvicorn / boto3 / botocore / PyJWT[crypto] / requests をバージョン固定（全 Lambda のロック済み依存の和集合と整合）。

### 4. 初期化・シード
- `scripts/local/init_tables.py`: `Reviews-local`（UserDateIndex + PublicDateIndex）/ `WhiskeySearch-local`（NameIndex のみ — DistilleryIndex は廃止済み）/ `DrinkLogs-local`（UserDatetimeIndex — Phase 4 先行準備）/ `AppState-local`（PK pk、TTL）。冪等。
- `scripts/local/seed_whiskeys.py`: 厳選50件の `seed_data/whiskeys.json`（**新規作成のフィクスチャ** — 実在の有名銘柄で ja/en 名を持つもの）を whiskey_common.normalize の正規化で投入。**`--target local|dev` 必須**: local は `AWS_ENDPOINT_URL_DYNAMODB` 必須、dev は endpoint 禁止 + 明示 profile + STS アカウント一致（031921999648）検証。**AppState の銘柄リビジョンカウンタを increment**（タスク03の dirty 判定と整合）。
- `.gitignore` に `!scripts/local/seed_data/*.json` を追加（包括 `*.json` 規則対策）。`git check-ignore` で追跡可能なことを確認。

### 5. Makefile
- `make local-up`（compose up -d + healthy 待ち）/ `make local-init`（上限付きリトライで init_tables + seed --target local + **local-aggregate を自動実行**）/ `make local-aggregate`（ranking-aggregator ハンドラを直接起動してキャッシュ世代生成）/ `make api`（venv 冪等作成 + requirements インストール + uvicorn --reload）/ `make local-down`。

### 6. docs/LOCAL_DEV.md
- セットアップ手順、認証2モードの説明（MOCK_AUTH / 実 dev Cognito）、`NUXT_PUBLIC_MOCK_AUTH=1` + `NUXT_PUBLIC_API_BASE_URL=http://localhost:8000` のフロント設定、トラブルシューティング。

## 受入条件

1. クリーンチェックアウト相当（node_modules/venv なし・AWS プロファイル環境変数なし）から:
   `docker compose up -d && make local-init && make api` 起動後、
   `curl "http://localhost:8000/api/whiskeys/search?q=山崎"` がシード銘柄を返す（末尾スラッシュなし）
2. `curl "http://localhost:8000/api/whiskeys/ranking"` が集計済みランキング（`make local-init` 内の local-aggregate による）を返す
3. MOCK_AUTH=1 で `POST /api/reviews`（whiskey_id 必須契約）が 201、実 JWT モードでトークンなしが 401
4. `python -m pytest tests/` 既存テストが引き続き全緑（アダプタの cold-import テスト含む）
5. lambda/ 本体の変更は最小限（ローカル対応に必要な箇所のみ、差分に理由コメント）

## してはならないこと

- 実 AWS アクセス（seed --target dev の実行はしない — 実装のみ）
- フロントエンド・infra の変更（.gitignore の1行を除く）
- コミット作成
