# Whiskey App Infrastructure

AWS CDK (TypeScript) を使用したウィスキーアプリケーションのインフラストラクチャ定義です。

## 📋 概要

このインフラストラクチャは以下のAWSリソースを構築します：

### 🏗️ 構築されるリソース

- **Lambda**: whiskeys-search/list、reviews、ranking-aggregator、drink-logs、drink-log-analyze、drink-log-places、drink-log-reconciler（VPC 外実行、VPC なし）
- **Cognito**: ユーザープール + アプリクライアント（Google OAuth）
- **S3**:
  - 飲酒ログ画像バケット（presigned URL、`tmp/` は2日ライフサイクル、CORS 設定済み）
  - Nuxt.js SPA 用 Web ホスティングバケット
- **CloudFront**: SPA 配信用 CDN（ResponseHeadersPolicy / HSTS）
- **DynamoDB**:
  - `WhiskeySearch`（GSI: NameEnIndex/NameJaIndex）
  - `Reviews`（GSI: UserDateIndex, PublicDateIndex）
  - `DrinkLogs`（GSI: UserDatetimeIndex）
  - `AppState`（PK `pk`、TTL）
- **Bedrock**: 銘柄/飲み方判別（Nova Lite 既定、APAC 域内固定プロファイル）
- **IAM**: 関数ごとの最小権限ロール、GitHub Actions 用 OIDC ロール（保護スタック）
- **Secrets Manager**: アプリ機密（`whiskey-app-secrets`）+ Places キー（`whiskey-places-{env}`）

### 🌍 環境

- **dev**: 開発環境（コスト最適化）
- **prod**: 本番環境（高可用性、データ保持）

## 🚀 セットアップ

### 前提条件

- Node.js 18+
- AWS CLI
- AWS アカウントと適切な権限

### 1. 依存関係のインストール

```bash
cd infra
npm install
```

### 2. AWS認証設定

```bash
aws configure
# または
export AWS_PROFILE=your-profile
```

### 3. CDK Bootstrap（初回のみ）

```bash
npx cdk bootstrap
```

## 🔧 デプロイ（deploy.sh ランブック）

`deploy.sh` は **アカウント検証付き**（`sts get-caller-identity` の Account が
`environments.ts` の期待値と一致しないと中断）。**必ず対象（target）を明示**する。
生の `npx cdk deploy` はガードを迂回するため使わない。

```
Usage: ./scripts/deploy.sh <dev|prd> <target> [target ...] [options]
targets: --dns --oidc --cert --base --notifications --observability --frontend
options: --diff --diff-only --no-confirm --destroy
```

| target | スタック / 動作 |
|--------|----------------|
| `--dns` | `WhiskeyDns`（登録ドメインの HostedZone、RETAIN + termination protection） |
| `--oidc` | `WhiskeyGithubOidc`（GitHub Actions ロール、保護スタック） |
| `--cert` | `WhiskeyCertificate-<Env>`（us-east-1 証明書） |
| `--base` | `WhiskeyApp-<Env>`（テーブル・Lambda・API GW・Cognito・S3・CloudFront） |
| `--notifications` | `WhiskeyNotifications`(us-east-1 Budgets) + `-Tokyo`(アラーム用トピック)。SSM `/whiskey/notifications/email` を両リージョンに要求 |
| `--observability` | `WhiskeyObservability-<Env>`（S3/リコンサイラのアラーム。**base + notifications-Tokyo の後**にデプロイ） |
| `--frontend` | スタック出力 → `.env` 生成 → `generate` → `s3 sync --delete` → CloudFront invalidation |

### 初回構築の順序（dev）
```bash
cd infra
AWS_PROFILE=dev bash scripts/deploy.sh dev --dns          # ① NS を出力 → レジストラ更新（ユーザー作業）
AWS_PROFILE=dev bash scripts/deploy.sh dev --oidc         # ② GitHub OIDC ロール
AWS_PROFILE=dev bash scripts/deploy.sh dev --cert         # ③ 証明書（DNS 伝播後）
AWS_PROFILE=dev bash scripts/deploy.sh dev --base         # ④ アプリ本体
AWS_PROFILE=dev bash scripts/deploy.sh dev --notifications # ⑤ 通知（SSM email 必要）
AWS_PROFILE=dev bash scripts/deploy.sh dev --observability # ⑥ アラーム
AWS_PROFILE=dev bash scripts/deploy.sh dev --frontend      # ⑦ フロント
```

### 通常運用
```bash
AWS_PROFILE=dev bash scripts/deploy.sh dev --base --diff-only  # 無変更ドライラン
AWS_PROFILE=dev bash scripts/deploy.sh dev --base --observability --no-confirm
AWS_PROFILE=dev bash scripts/deploy.sh dev --frontend          # フロントだけ更新
```

### 段階投入フラグ（`infra/config/environments.ts` に永続化）
CLI の `-c` ではなく **設定値**で管理し、通過時にコミットする（揮発性 CLI フラグだと
次の通常デプロイで剥がれる）。
- `enableCustomDomain`: カスタムドメイン + 証明書（DNS 完了後に true）
- `enableGoogleAuth`: Google IdP + クライアントの provider 参照（OAuth クライアント作成後に true）
- `createOidcProvider`: OIDC プロバイダを新規作成するか import するか

> **絶対に destroy しない**: `WhiskeyDns` / `WhiskeyGithubOidc`（deploy.sh も拒否）。
> ゾーン/OIDC が消えると DNS 委任と CI 認証が即停止する。prd はスコープ外。

## 📊 出力値の確認

```bash
# スタック出力の確認
aws cloudformation describe-stacks \
  --stack-name WhiskeyApp-Dev \
  --query 'Stacks[0].Outputs[*].[OutputKey,OutputValue]' \
  --output table
```

## 🔗 GitHub Actions設定

### 1. OIDC プロバイダーの設定

```bash
# 一度だけ実行が必要
aws iam create-open-id-connect-provider \
  --url https://token.actions.githubusercontent.com \
  --client-id-list sts.amazonaws.com \
  --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1
```

### 2. GitHub Secrets設定

```bash
# デプロイ後に表示されるロールARNをGitHub Secretsに設定
AWS_ROLE_ARN: <GitHubActionsRoleArn>
```

### 3. リポジトリ名の制限

`lib/whiskey-infra-stack.ts` の以下の行を修正：

```typescript
'token.actions.githubusercontent.com:sub': 'repo:your-username/your-repo:*'
```

## 🌐 フロントエンド環境変数

デプロイ後、以下の環境変数をNuxt.jsアプリで使用できます：

```bash
NUXT_PUBLIC_USER_POOL_ID=<UserPoolId>
NUXT_PUBLIC_USER_POOL_CLIENT_ID=<UserPoolClientId>
NUXT_PUBLIC_REGION=ap-northeast-1
NUXT_PUBLIC_IMAGES_BUCKET=<ImagesBucketName>
NUXT_PUBLIC_API_BASE_URL=<API_URL>
NUXT_PUBLIC_ENVIRONMENT=dev|prod
```

## 🏗️ アーキテクチャ

VPC はなし（Lambda は VPC 外で実行）。全てサーバーレス・従量課金。

```
                         Internet
                            │
                    ┌───────▼───────┐        ┌──────────────┐
                    │  CloudFront   │        │  API Gateway │
                    │ (静的SPA配信) │         │  (REST + JWT) │
                    └───────┬───────┘        └───────┬──────┘
              ┌─────────────┴────────┐               │
        ┌─────▼─────┐        ┌───────▼──────┐   ┌────▼──────────────┐
        │ S3 WebApp │        │  S3 Images   │   │  Lambda 関数群      │
        │ (静的SPA) │        │(tmp/2日, logs)│◄──┤ search/list/reviews│
        └───────────┘        └──────────────┘   │ ranking-aggregator │
                                                 │ drink-logs/analyze │
                                                 │ places/reconciler  │
                                                 └────┬──────┬────┬───┘
                          ┌───────────┬───────────────┘      │    │
                    ┌─────▼───┐ ┌─────▼────┐         ┌────────▼─┐ ┌▼──────────┐
                    │DynamoDB │ │ Cognito  │         │ Bedrock  │ │  Google   │
                    │(4 tables)│ │(認証/OAuth)│        │(Nova Lite)│ │  Places   │
                    └─────────┘ └──────────┘         └──────────┘ └───────────┘
```

## 🔧 設定カスタマイズ

### 本番ドメイン設定

`config/environments.ts` を編集：

```typescript
prod: {
  domain: 'your-actual-domain.com',
  allowedOrigins: ['https://your-actual-domain.com'],
  // SSL証明書ARN（Route53 + ACM使用時）
  // certificateArn: 'arn:aws:acm:...',
}
```

### 環境固有リソース設定

```typescript
// lib/whiskey-infra-stack.ts
natGateways: environment === 'prod' ? 2 : 1,  // 本番は冗長化
removalPolicy: environment === 'prod' 
  ? cdk.RemovalPolicy.RETAIN    // 本番はデータ保持
  : cdk.RemovalPolicy.DESTROY   // 開発は削除
```

## 📝 運用コマンド

### 差分確認

```bash
npx cdk diff -c env=dev
```

### リソース一覧

```bash
npx cdk list -c env=dev
```

### CloudFormationテンプレート生成

```bash
npx cdk synth -c env=dev
```

### スタック削除

```bash
npx cdk destroy -c env=dev
```

## 🔍 トラブルシューティング

### よくある問題

1. **Bootstrap未実行**
   ```bash
   npx cdk bootstrap
   ```

2. **権限不足**
   - AdministratorAccess または適切なIAM権限が必要

3. **バケット名重複**
   - S3バケット名にアカウントIDを含めているため通常は回避可能

4. **GitHub Actions権限エラー**
   - OIDC プロバイダーが設定されているか確認
   - リポジトリ名の制限が正しく設定されているか確認

### デバッグ

```bash
# CDKログ有効化
export CDK_DEBUG=true
npx cdk deploy -c env=dev --verbose
```

## 📚 参考リンク

- [AWS CDK Developer Guide](https://docs.aws.amazon.com/cdk/)
- [AWS CDK API Reference](https://docs.aws.amazon.com/cdk/api/v2/)
- [GitHub Actions OIDC](https://docs.github.com/en/actions/deployment/security-hardening-your-deployments/about-security-hardening-with-openid-connect)

## 🤝 コントリビューション

1. 環境設定ファイルのカスタマイズ
2. セキュリティ設定の見直し
3. コスト最適化の提案
4. モニタリング・アラートの追加
