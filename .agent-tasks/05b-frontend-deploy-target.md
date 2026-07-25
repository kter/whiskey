# Task 05b: deploy.sh の --frontend ターゲット実装（ガード付きフロントデプロイ）

## 背景

`infra/scripts/deploy.sh` の `--frontend` は現在スタブ（exit 2）。計画では「スタック出力から .env を生成し、STS アカウント検証後に generate + s3 sync + invalidation を実行するガード付きスクリプト」が必要。dev のベーススタックはデプロイ済みで、出力キーは: `ApiGatewayUrl` / `CloudFrontDomainName` / `CloudFrontDistributionId`（存在を確認して使うこと。無ければ describe-stacks で確認できる名前を使う）/ `UserPoolId` / `UserPoolClientId` / `CognitoHostedUiHostname` / `WebAppBucketName` / `ImagesBucketName`。

## 要求仕様（deploy.sh 内 `--frontend`）

1. 既存のアカウント/プロファイルガードを通過後、`aws cloudformation describe-stacks` でアプリスタックの出力を取得。
2. `frontend/.env` を生成（上書き前に既存 .env があれば `.env.backup` に退避）:
   - `NUXT_PUBLIC_API_BASE_URL`（ApiGatewayUrl。カスタムドメイン有効時は `https://api.<domain>` を優先 — enableCustomDomain 設定値で分岐）
   - `NUXT_PUBLIC_USER_POOL_ID` / `NUXT_PUBLIC_USER_POOL_CLIENT_ID` / `NUXT_PUBLIC_REGION=ap-northeast-1`
   - `NUXT_PUBLIC_COGNITO_DOMAIN`（CognitoHostedUiHostname — 裸ホスト名）
   - `NUXT_PUBLIC_GOOGLE_AUTH_ENABLED`（environments.ts の enableGoogleAuth が true のときだけ `1`、それ以外は `0` — fail-closed）
   - `NUXT_PUBLIC_ENVIRONMENT=dev|prd`
   - `NUXT_PUBLIC_MOCK_AUTH` は**絶対に書かない**
3. `cd frontend && npm ci && npm run generate`（NODE_ENV=production で。generate 失敗時は sync せず中断）
4. `aws s3 sync .output/public s3://<WebAppBucketName> --delete`
5. `aws cloudfront create-invalidation --distribution-id <id> --paths '/*'`
6. 各ステップの失敗で即中断（set -e 準拠）、実行ログに使った値（シークレットなし）を出力。

## 検証

- `bash -n infra/scripts/deploy.sh`（構文）
- shellcheck があれば実行（無ければスキップ可）
- 実デプロイはオーケストレーターが実施するため不要

## してはならないこと

他ターゲットのロジック変更・フロントエンドコード変更・実 AWS アクセス・コミット作成。
