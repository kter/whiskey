# ローカル開発環境

DynamoDB Local、MinIO、既存 Lambda ハンドラを呼び出す FastAPI アダプタを使い、AWS プロファイルなしでバックエンドを起動できます。すべての公開ポートは loopback のみに bind されます。

## 必要なもの

- Docker Engine と Docker Compose v2
- Python 3.11 以降（`venv` を利用可能であること）
- `make`、`curl`

実 AWS へのアクセスは不要です。ローカル環境では `minioadmin` / `minioadmin` を MinIO と boto3 の両方に使い、サービス別 endpoint だけを設定します。`AWS_ENDPOINT_URL` は使用しません。

## 起動

```bash
make local-up
make local-init
make api
```

`make local-up` は DynamoDB Local（`127.0.0.1:8001`）と MinIO API/Console（`127.0.0.1:9000` / `127.0.0.1:9001`）の healthcheck、および `whiskey-images-local` バケット作成の完了を待ちます。

`make local-init` は4テーブルを冪等に作成し、50銘柄を投入してからランキング集計 Lambda を直接実行します。`.venv` と固定済み Python 依存も必要に応じて作成します。

`make api` は FastAPI を `http://127.0.0.1:8000` で起動します。API パスは API Gateway と同じく末尾スラッシュなしです。

```bash
curl --get --data-urlencode 'q=山崎' \
  http://localhost:8000/api/whiskeys/search

curl http://localhost:8000/api/whiskeys/ranking
```

停止するときは次を実行します。

```bash
make local-down
```

## 認証モード

### モック認証

`make api` は既定で `MOCK_AUTH=1` です。アダプタが固定ユーザー `local-test-user` の ID-token 相当 claims（`aud=local-client`、`token_use=id`）を API Gateway イベントへ注入します。Bearer token は不要です。

```bash
curl -i -X POST http://localhost:8000/api/reviews \
  -H 'Content-Type: application/json' \
  -d '{"whiskey_id":"yamazaki-12","rating":5,"date":"2026-07-19","is_public":true}'
```

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
  http://localhost:8000/api/reviews
```

トークンなし、access token、別 Client ID 向け token は `401` になります。Cognito の公開鍵取得にはネットワーク接続が必要ですが、DynamoDB と S3 は引き続きローカル endpoint を使います。

## 個別コマンド

```bash
# シード後などにランキングを再生成
make local-aggregate

# AWS プロファイル変数を除いた状態で全手順を確認
env -u AWS_PROFILE -u AWS_DEFAULT_PROFILE make local-up
env -u AWS_PROFILE -u AWS_DEFAULT_PROFILE make local-init
```

dev テーブルへのシードは事故防止のため `--target dev --profile PROFILE` の両方が必須で、endpoint 環境変数がないことと STS のアカウント ID が `031921999648` であることを確認します。このコマンドをローカル環境のセットアップでは実行しないでください。

## トラブルシューティング

- 起動待ちが失敗する: `docker compose ps` と `docker compose logs dynamodb-local minio minio-init` を確認してください。8001、9000、9001 が別プロセスで使用中でないことも確認します。
- API が DynamoDB 接続エラーになる: `make local-up` の後に `make local-init` を再実行してください。DynamoDB Local は in-memory のため、コンテナを作り直すと再初期化が必要です。
- 検索結果が空になる: URL エンコードを避けるため、上記のように `curl --get --data-urlencode 'q=山崎'` を使ってください。
- ランキングが「集計中」のままになる: ローカルには15分スケジューラがないため、`make local-aggregate` を実行してください。
- POST が `401` になる: モックなら API を `MOCK_AUTH=1 make api` で再起動します。実 Cognito なら ID token と2つの Cognito 環境変数を確認します。
- 末尾スラッシュで `404` になる: 仕様どおりです。`/api/whiskeys/search` のように末尾スラッシュなしで呼び出してください。
