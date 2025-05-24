# Whiskey App Infrastructure

AWS CDK (TypeScript) を使用したウィスキーアプリケーションのインフラストラクチャ定義です。

## 📋 概要

このインフラストラクチャは以下のAWSリソースを構築します：

### 🏗️ 構築されるリソース

- **VPC**: パブリック/プライベートサブネット構成
- **Cognito**: ユーザープール + アプリクライアント
- **S3**: 
  - ウイスキー画像保存用バケット（署名付きURL、CORS設定済み）
  - Nuxt.js SPA用Webホスティングバケット
- **CloudFront**: SPA配信用CDN
- **DynamoDB**: 
  - Whiskeysテーブル（GSI: NameIndex）
  - Reviewsテーブル（GSI: UserDateIndex）
- **IAM**: Lambda/ECS実行ロール、GitHub Actions用ロール
- **Secrets Manager**: アプリケーション機密情報管理

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

## 🔧 デプロイ

### 簡単デプロイ

```bash
# 開発環境
./scripts/deploy.sh dev

# 本番環境
./scripts/deploy.sh prod
```

### 詳細オプション

```bash
# 差分確認してからデプロイ
./scripts/deploy.sh dev --diff

# 確認プロンプトをスキップ
./scripts/deploy.sh dev --no-confirm

# スタック削除
./scripts/deploy.sh dev --destroy
```

### 手動デプロイ

```bash
# 開発環境
npm run build
npx cdk deploy -c env=dev

# 本番環境
npm run build
npx cdk deploy -c env=prod
```

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

```
┌─────────────────────────────────────────────────────────────────┐
│                            Internet                              │
└─────────────────────┬───────────────────────────────────────────┘
                      │
                ┌─────▼─────┐
                │CloudFront │
                │Distribution│
                └─────┬─────┘
                      │
                ┌─────▼─────┐      ┌─────────────┐
                │S3 (WebApp)│      │  S3 (Images)│
                │  Bucket   │      │   Bucket    │
                └───────────┘      └─────────────┘
                                           │
┌─────────────────────────────────────────┼─────────────────────────┐
│                VPC (10.0.0.0/16)        │                         │
│  ┌─────────────────────────────────────┐ │                         │
│  │        Public Subnets               │ │                         │
│  │  ┌──────────────┐  ┌──────────────┐ │ │                         │
│  │  │   AZ-1a      │  │   AZ-1c      │ │ │                         │
│  │  │10.0.0.0/24   │  │10.0.1.0/24   │ │ │                         │
│  │  └──────────────┘  └──────────────┘ │ │                         │
│  └─────────────────────────────────────┘ │                         │
│  ┌─────────────────────────────────────┐ │                         │
│  │       Private Subnets               │ │                         │
│  │  ┌──────────────┐  ┌──────────────┐ │ │                         │
│  │  │   AZ-1a      │  │   AZ-1c      │ │ │                         │
│  │  │10.0.2.0/24   │  │10.0.3.0/24   │ │ │                         │
│  │  │              │  │              │ │ │                         │
│  │  │ Lambda/ECS   │  │ Lambda/ECS   │ │ │                         │
│  │  └──────┬───────┘  └──────┬───────┘ │ │                         │
│  └─────────┼──────────────────┼─────────┘ │                         │
└────────────┼──────────────────┼───────────┼─────────────────────────┘
             │                  │           │
        ┌────▼────┐         ┌───▼────┐ ┌────▼────┐
        │DynamoDB │         │Cognito │ │Secrets  │
        │ Tables  │         │UserPool│ │Manager  │
        └─────────┘         └────────┘ └─────────┘
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
