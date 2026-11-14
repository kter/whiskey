# ローカル開発環境

moto サーバー（DynamoDB + S3）、既存 Lambda ハンドラを呼び出す FastAPI アダプタを使い、AWS プロファイルなしでバックエンドを起動できます。すべての公開ポートは loopback のみに bind されます。

## 必要なもの

- Python 3.11 以降（`venv` を利用可能であること）
- Node.js 22、npm（`scripts/agent/setup.sh` でフロント・infra の依存も入れる場合）
- `make`、`curl`

実 AWS へのアクセスは不要です。ローカル環境では `minioadmin` / `minioadmin` をローカル専用のダミー認証情報として使い、サービス別 endpoint だけを設定します。`AWS_ENDPOINT_URL` は使用しません。

## 起動

```bash
bash scripts/agent/setup.sh  # クラウドでは先に Node 22 を PATH に設定
make local-up
make local-init
make api
```

`make local-up` は固定版 moto 5.1.22 を `127.0.0.1:5000` の1プロセスでバックグラウンド起動し、応答まで待ちます。DynamoDB / S3 ともこの endpoint を使用します。Docker は不要です。
ログは `.cache/moto/server.log`、PID とプロセス識別情報は `.cache/moto/server.pid`（いずれも git 管理外）。繰り返し起動は同じプロセスを使い、ポートが他のプロセスに使われている場合は失敗します。`make local-down` は記録したプロセスだけを停止します。データはメモリ上のみで、停止後は再初期化が必要です。

`make local-init` は3テーブルと `whiskey-images-local` バケットを冪等に作成し、`http://localhost:3000` 向けの CORS（GET / HEAD / POST）を設定し、カタログの全銘柄（現在51件）を投入します。`.venv` と固定済み Python 依存も必要に応じて作成します。

`make api` は FastAPI を `http://127.0.0.1:8000` で起動します。API パスは API Gateway と同じく末尾スラッシュなしです。

```bash
curl --get --data-urlencode 'q=山崎' \
  http://localhost:8000/api/whiskeys/search
```

## テイスティング記録をローカルで動かす

テイスティング記録も上記の起動手順で利用できます。

ローカルAPIは`MOCK_AI=1`と`MOCK_PLACES=1`が既定です。
写真解析は「モックウイスキー」、周辺店舗検索は「モックバー」を決定的に返すため、Bedrock、Google Places、Secrets Managerへはアクセスしません。
写真のpresigned POST先は moto で、ブラウザからのアップロードは S3 バケットの CORS（`http://localhost:3000`）を経由します。

### moto と実 S3 の差（5.1.22 で実測）

モック認証で、英語・日本語検索 → upload-url → JPEG の multipart POST → analyze（モック）→ 記録作成（`status=complete`）→ 一覧表示を curl で確認しました。ブラウザ origin を付けた OPTIONS は 200 となり、`Access-Control-Allow-Origin: http://localhost:3000` と `Access-Control-Allow-Methods: GET, HEAD, POST` が返ります。

ただし、moto の presigned POST 成功は実 S3 のポリシー検証を保証しません。発行されたポリシーには `Content-Type=image/jpeg`、固定 bucket/key、`content-length-range: 0..3670016`、有効期限120秒が入りますが、次の不正フォームもすべて **204** で受け入れられました。

| 変更した条件 | moto の結果 | 実 S3 の要件 |
| --- | --- | --- |
| ファイルを3,670,017 bytes（上限+1）にする | 204 | サイズ範囲外は拒否 |
| Content-Type を text/plain に変更 | 204 | ポリシー条件との不一致は拒否 |
| key を別のキーに変更 | 204 | 固定 key との不一致は拒否 |
| signature を invalid に変更 | 204 | 有効な署名が必要 |
| 正しく署名した有効期限1秒のフォームで2秒待って転送 | 204 | 有効期限後は拒否 |

上限・署名・有効期限などのセキュリティ検証は、このローカルスタックだけでは確認できません。アプリの入力検証・画像サニタイズのテストと、実 S3 での確認を別途行ってください。AWS 上での実測はこの移行では行っていません。

### 実Google Places APIを使う場合

PlacesハンドラはAPIキーを環境変数から直接読まず、`PLACES_SECRET_NAME`のSecrets Manager JSONから読みます。
そのため、実Placesを試す場合は別途ローカルのSecrets Manager互換エンドポイントを用意してください（moto は Secrets Manager も提供します。利用時はサービス別 endpoint を明示してください）。

未追跡の`.env.local`はこんな感じです。

```dotenv
MOCK_PLACES=0
PLACES_SECRET_NAME=whiskey-places-local
AWS_ENDPOINT_URL_SECRETS_MANAGER=http://127.0.0.1:5000
PLACES_API_KEY=replace-with-your-key
```

`.env.local`は`.gitignore`の対象です。
APIキーをSecrets Manager互換サービスへ投入します。

```bash
set -a
source .env.local
set +a

secret_json="$(python -c 'import json, os; print(json.dumps({"apiKey": os.environ["PLACES_API_KEY"]}))')"
aws --endpoint-url "$AWS_ENDPOINT_URL_SECRETS_MANAGER" \
  secretsmanager create-secret \
  --name "$PLACES_SECRET_NAME" \
  --secret-string "$secret_json"
unset secret_json PLACES_API_KEY

make api
```

※同名のsecretを作成済みなら`create-secret`ではなく`put-secret-value`を使います。
※`AWS_ENDPOINT_URL`全体は設定しないでください。DynamoDB、S3、Secrets Managerのサービス別endpointだけを使います。

停止するときは次を実行します。

```bash
make local-down
```

## ブラウザのスモークテスト（`make e2e`）

Playwright（`frontend/e2e/`、設定は `frontend/playwright.config.ts`）で主要な操作をスマホ幅（390×844）の Chromium で確かめます。

```bash
# Chromium の取得（どちらか）
export PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/google-chrome   # 既存の Chromium を使う
(cd frontend && npx playwright install chromium)                     # 手元・CI: Playwright 管理の Chromium

make e2e
make e2e E2E_ARGS="--grep 検索"   # playwright test への追加引数
```

`make e2e`（`scripts/local/e2e.sh`）は次を順に行い、成功・失敗・中断のいずれでも自分が起動したプロセスを止めます。

1. moto を起動（既に動いていれば再利用し、終了後も止めない）→ `make local-init`
2. FastAPI アダプタを `127.0.0.1:8000` で起動（`--reload` なし。`MOCK_AUTH` / `MOCK_AI` / `MOCK_PLACES` は既定の `1`）
3. `nuxt dev` を `localhost:3000` で起動（`NUXT_PUBLIC_MOCK_AUTH=1`）
4. 各ルートを一度開いて Vite の依存最適化によるリロードを先に済ませてから、`playwright test` を実行

3000 か 8000 が使用中なら、古いサーバーに対してテストしないよう失敗します。`make api` や `npm run dev` を止めてから実行してください。

| シナリオ | 内容 |
| --- | --- |
| 検索 | `bowmore` と `山崎` で結果が表示される |
| 記録 | `/logs/new` で JPEG をファイル入力から選ぶ → 解析（モック）→ 位置情報をエミュレートして店候補（モックバー）を選ぶ → 保存 |
| 履歴 | `/logs` に保存した記録が表示され、`/logs/{id}` が開ける |

- モック解析は銘柄候補を1件だけ返すため、銘柄の選択ボタン（2件以上のとき表示）は使わず、自動で入った銘柄を確認します。
- ブラウザのコンソールエラーと未捕捉の例外はテストを失敗にします（`frontend/e2e/fixtures.ts`）。
- ログは `.cache/e2e/`（`api.log`・`nuxt.log`・`local-init.log`）、失敗時のスクリーンショットとトレースは `.cache/e2e/test-results/` に残ります（git 管理外）。トレースは `cd frontend && npx playwright show-trace ../.cache/e2e/test-results/<テスト>/trace.zip` で開けます。
- CI では `ci` とは別の `e2e` ジョブが同じ `make e2e` を実行し、失敗時は `.cache/e2e/` を成果物として保存します。

## 認証モード

### モック認証

`make api` は既定で `MOCK_AUTH=1` です。アダプタが固定ユーザー `local-user` の ID-token 相当 claims（`aud=local-client`、`token_use=id`）を API Gateway イベントへ注入します。Bearer token は不要です。

テイスティング記録 API は固定ユーザーの記録として利用できます。

フロントエンドのローカル設定例です。

```dotenv
NUXT_PUBLIC_MOCK_AUTH=1
NUXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

モック認証は Nuxt の dev build でのみ有効になる実装です。フロントエンドは `http://localhost:3000` で起動してください。

### 実 dev Cognito

実際の Cognito ID token を検証する場合は、モックを無効にして dev User Pool と Client ID を明示します。アダプタは authorizer claims を注入せず、`whiskey_common.jwt_utils` が Cognito JWKS、issuer、audience、`token_use=id` を検証します。

```bash
MOCK_AUTH=0 \
COGNITO_USER_POOL_ID=ap-northeast-1_xxxxx \
COGNITO_CLIENT_ID=xxxxxxxxxxxxxxxxxxxxxxxxxx \
make api

curl -H "Authorization: Bearer $ID_TOKEN" \
  http://localhost:8000/api/drink-logs
```

トークンなし、access token、別 Client ID 向け token は `401` になります。Cognito の公開鍵取得にはネットワーク接続が必要ですが、DynamoDB と S3 は引き続きローカル endpoint を使います。

## 個別コマンド

```bash
# AWS プロファイル変数を除いた状態で全手順を確認
env -u AWS_PROFILE -u AWS_DEFAULT_PROFILE make local-up
env -u AWS_PROFILE -u AWS_DEFAULT_PROFILE make local-init
```

dev テーブルへのシードは事故防止のため `--target dev --profile PROFILE` の両方が必須で、endpoint 環境変数がないことと STS のアカウント ID が `031921999648` であることを確認します。このコマンドをローカル環境のセットアップでは実行しないでください。

## トラブルシューティング

- 起動待ちが失敗する: `.cache/moto/server.log` を確認してください。5000 が別プロセスで使用中でないことも確認します。
- API が DynamoDB 接続エラーになる: `make local-up` の後に `make local-init` を再実行してください。moto は in-memory のため、再起動すると再初期化が必要です。
- 検索結果が空になる: URL エンコードを避けるため、上記のように `curl --get --data-urlencode 'q=山崎'` を使ってください。
- POST が `401` になる: モックなら API を `MOCK_AUTH=1 make api` で再起動します。実 Cognito なら ID token と2つの Cognito 環境変数を確認します。
- 末尾スラッシュで `404` になる: 仕様どおりです。`/api/whiskeys/search` のように末尾スラッシュなしで呼び出してください。
