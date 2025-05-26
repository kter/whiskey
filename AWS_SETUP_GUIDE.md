# AWS認証情報設定とCDKデプロイガイド

## 🔑 AWS認証情報の設定

### オプション1: AWS CLI設定（推奨）

```bash
# AWS CLIで認証情報を設定
aws configure

# 以下の情報を入力
# AWS Access Key ID: [your-access-key]
# AWS Secret Access Key: [your-secret-key]
# Default region name: ap-northeast-1
# Default output format: json
```

### オプション2: 環境変数

```bash
export AWS_ACCESS_KEY_ID=your-access-key
export AWS_SECRET_ACCESS_KEY=your-secret-key
export AWS_DEFAULT_REGION=ap-northeast-1
```

### オプション3: AWSプロファイル

```bash
# 特定のプロファイルを使用
export AWS_PROFILE=your-profile-name
```

## 🚀 ECR権限修正のためのCDKデプロイ

### 1. 緊急修正スクリプトの実行

```bash
# 権限修正を実行
./deploy-fix.sh
```

### 2. 手動デプロイ

```bash
# インフラディレクトリに移動
cd infra

# 依存関係のインストール
npm install

# CDK差分確認
npx cdk diff WhiskeyApp-Dev

# CDKデプロイ実行
npx cdk deploy WhiskeyApp-Dev --require-approval never
```

### 3. デプロイ状況の確認

```bash
# CloudFormationスタックの状態確認
aws cloudformation describe-stacks --stack-name WhiskeyApp-Dev --region ap-northeast-1

# IAMロールの権限確認
aws iam list-attached-role-policies --role-name whiskey-github-actions-role-dev
aws iam list-role-policies --role-name whiskey-github-actions-role-dev

# GitHub Actionsロールの詳細確認
aws iam get-role --role-name whiskey-github-actions-role-dev
```

## 🔄 GitHub Actionsでの自動デプロイ

CDKの変更をGitHub Actionsで自動デプロイするには：

### 1. 変更をコミット・プッシュ

```bash
# 変更をステージング
git add .

# コミット
git commit -m "fix: ECR authorization permissions for GitHub Actions"

# mainブランチにプッシュ（dev環境へのデプロイ）
git push origin main
```

### 2. GitHub Actionsの実行確認

1. GitHubリポジトリのActionsタブを確認
2. "Deploy Whiskey App" ワークフローの実行状況を監視
3. エラーが解決されているか確認

## 🛠️ トラブルシューティング

### CDKデプロイエラー

#### 1. Bootstrap未実行エラー
```bash
# CDKをbootstrap
npx cdk bootstrap --region ap-northeast-1
```

#### 2. 権限不足エラー
```bash
# IAMユーザー/ロールに以下の権限が必要：
# - CloudFormation
# - IAM
# - EC2
# - S3
# - DynamoDB
# - Cognito
# - ECR
# - ECS
# - ELB
# - Route53
# - ACM
```

#### 3. スタック状態確認
```bash
# スタックの詳細状態
aws cloudformation describe-stack-events --stack-name WhiskeyApp-Dev

# リソースの状態
aws cloudformation describe-stack-resources --stack-name WhiskeyApp-Dev
```

### GitHub Actions権限エラー

#### 1. OIDC設定確認
```bash
# OIDCプロバイダーの確認
aws iam list-open-id-connect-providers

# GitHub Actionsロールの信頼関係確認
aws iam get-role --role-name whiskey-github-actions-role-dev --query 'Role.AssumeRolePolicyDocument'
```

#### 2. リポジトリ設定確認
- GitHub リポジトリの Settings > Secrets and variables > Actions
- `AWS_ROLE_ARN` 環境変数が正しく設定されているか確認

## 📋 必要なAWS権限一覧

### 最小限必要な権限

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "cloudformation:*",
                "iam:*",
                "ec2:*",
                "s3:*",
                "dynamodb:*",
                "cognito-idp:*",
                "ecr:*",
                "ecs:*",
                "elasticloadbalancing:*",
                "route53:*",
                "acm:*",
                "logs:*",
                "secretsmanager:*"
            ],
            "Resource": "*"
        }
    ]
}
```

## 🎯 次のステップ

1. **AWS認証情報を設定**
2. **CDKデプロイを実行**
3. **GitHub Actionsワークフローを再実行**
4. **APIデプロイが成功することを確認**

ECR権限修正が適用されれば、GitHub ActionsからのAPIデプロイが正常に動作するようになります。 