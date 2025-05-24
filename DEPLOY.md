# 🚀 デプロイクイックガイド

## ローカル開発環境

```bash
# 1. 起動
docker-compose up -d

# 2. テーブル作成
./scripts/init_data.sh

# 3. アクセス
# Frontend: http://localhost:3000
# Backend API: http://localhost:8000/api/
```

## AWS環境デプロイ

### 初回セットアップ

```bash
# 1. AWS認証
aws configure

# 2. CDK準備
cd infra
npm install
npx cdk bootstrap

# 3. OIDC Provider作成（GitHub Actions用）
aws iam create-open-id-connect-provider \
  --url https://token.actions.githubusercontent.com \
  --client-id-list sts.amazonaws.com \
  --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1
```

### 開発環境デプロイ

```bash
cd infra
./scripts/deploy.sh dev
```

### 本番環境デプロイ

```bash
cd infra
./scripts/deploy.sh prod
```

### GitHub Actions設定

1. **GitHub Secretsに追加**:
   ```
   AWS_ROLE_ARN: <デプロイ後に表示されるGitHubActionsRoleArn>
   ```

2. **リポジトリ制限の設定**:
   `infra/lib/whiskey-infra-stack.ts` の278行目を編集：
   ```typescript
   'token.actions.githubusercontent.com:sub': 'repo:your-username/your-repo:*'
   ```

## 主要なデプロイコマンド

```bash
# 差分確認
./scripts/deploy.sh dev --diff

# 強制実行（確認なし）
./scripts/deploy.sh dev --no-confirm

# スタック削除
./scripts/deploy.sh dev --destroy

# 出力値確認
aws cloudformation describe-stacks \
  --stack-name WhiskeyApp-Dev \
  --query 'Stacks[0].Outputs[*].[OutputKey,OutputValue]' \
  --output table
```

## デプロイ後の確認

```bash
# 1. スタック状態確認
aws cloudformation describe-stacks --stack-name WhiskeyApp-Dev

# 2. CloudFrontドメイン確認
aws cloudformation describe-stacks \
  --stack-name WhiskeyApp-Dev \
  --query 'Stacks[0].Outputs[?OutputKey==`CloudFrontDomainName`].OutputValue' \
  --output text

# 3. Cognito設定確認
aws cloudformation describe-stacks \
  --stack-name WhiskeyApp-Dev \
  --query 'Stacks[0].Outputs[?contains(OutputKey,`UserPool`)].{Key:OutputKey,Value:OutputValue}' \
  --output table
```

## トラブルシューティング

### よくあるエラー

1. **CDK Bootstrap未実行**
   ```bash
   npx cdk bootstrap
   ```

2. **権限不足**
   ```bash
   aws sts get-caller-identity
   # AdministratorAccess権限が必要
   ```

3. **GitHub Actions失敗**
   - OIDC Providerの作成確認
   - AWS_ROLE_ARN Secretの設定確認
   - リポジトリ名の制限設定確認

### ログ確認

```bash
# CloudFormationイベント
aws cloudformation describe-stack-events --stack-name WhiskeyApp-Dev

# CDKデバッグモード
export CDK_DEBUG=true
npx cdk deploy -c env=dev --verbose
``` 