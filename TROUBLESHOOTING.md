# Whiskey App トラブルシューティングガイド

## 🚨 ECR認証エラー

### エラー内容
```
arn:aws:sts::031921999648:assumed-role/whiskey-github-actions-role-dev/GitHubActions-API-15243436364 is not authorized to perform: ecr:GetAuthorizationToken on resource: * because no identity-based policy allows the ecr:GetAuthorizationToken action
```

### 原因
GitHub ActionsロールにECR認証トークン取得権限が不足している。

### 解決方法

#### 1. 緊急修正（推奨）
```bash
# 権限修正スクリプトを実行
./deploy-fix.sh
```

#### 2. 手動修正
```bash
cd infra
npm install
npx cdk deploy WhiskeyApp-Dev --require-approval never
```

#### 3. 権限確認
```bash
# GitHub Actionsロールの権限を確認
aws iam list-attached-role-policies --role-name whiskey-github-actions-role-dev
aws iam list-role-policies --role-name whiskey-github-actions-role-dev
```

### 必要な権限
GitHub Actionsロールには以下の権限が必要：

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ecr:GetAuthorizationToken"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "ecr:BatchCheckLayerAvailability",
        "ecr:GetDownloadUrlForLayer",
        "ecr:BatchGetImage",
        "ecr:InitiateLayerUpload",
        "ecr:UploadLayerPart",
        "ecr:CompleteLayerUpload",
        "ecr:PutImage"
      ],
      "Resource": "arn:aws:ecr:ap-northeast-1:*:repository/whiskey-api-dev"
    }
  ]
}
```

## 🔧 その他の一般的な問題

### ECS タスクが起動しない

#### 症状
- ECSサービスのタスクが0/1で止まっている
- ヘルスチェックが失敗する

#### 確認方法
```bash
# ECS タスクのログを確認
aws logs tail /ecs/whiskey-api-dev --follow

# ECS サービスの状態確認
aws ecs describe-services \
  --cluster whiskey-api-cluster-dev \
  --services whiskey-api-service-dev

# タスク定義の確認
aws ecs describe-task-definition \
  --task-definition whiskey-api-dev
```

#### 一般的な原因と解決方法

1. **Dockerイメージの問題**
   ```bash
   # ローカルでDockerイメージをテスト
   cd backend
   docker build -t test-image .
   docker run -p 8000:8000 test-image
   ```

2. **環境変数の不足**
   - ECSタスク定義の環境変数を確認
   - DynamoDBテーブル名、S3バケット名などが正しく設定されているか

3. **ヘルスチェックの設定**
   - `/health/` エンドポイントが正しく動作しているか
   - ヘルスチェックのタイムアウト設定

### API が応答しない

#### 症状
- `https://api.dev.whiskeybar.site/health/` にアクセスできない
- 502 Bad Gatewayエラー

#### 確認方法
```bash
# ALB ターゲットグループの状態確認
aws elbv2 describe-target-health \
  --target-group-arn $(aws elbv2 describe-target-groups \
    --names whiskey-api-tg-dev \
    --query 'TargetGroups[0].TargetGroupArn' \
    --output text)

# Route53 レコードの確認
aws route53 list-resource-record-sets \
  --hosted-zone-id $(aws route53 list-hosted-zones \
    --query 'HostedZones[?Name==`whiskeybar.site.`].Id' \
    --output text | cut -d'/' -f3)
```

#### 解決方法
1. **ECS タスクが正常に動作しているか確認**
2. **セキュリティグループの設定確認**
3. **SSL証明書の状態確認**

### フロントエンドが表示されない

#### 症状
- `https://dev.whiskeybar.site` にアクセスできない
- CloudFrontエラー

#### 確認方法
```bash
# S3バケットの内容確認
aws s3 ls s3://whiskey-webapp-dev/ --recursive

# CloudFront配信の確認
aws cloudfront get-distribution \
  --id $(aws cloudformation describe-stacks \
    --stack-name WhiskeyApp-Dev \
    --query "Stacks[0].Outputs[?OutputKey=='CloudFrontDistributionId'].OutputValue" \
    --output text)
```

### 認証エラー

#### 症状
- ログインできない
- JWTトークンエラー

#### 確認方法
```bash
# Cognito User Poolの設定確認
aws cognito-idp describe-user-pool \
  --user-pool-id $(aws cloudformation describe-stacks \
    --stack-name WhiskeyApp-Dev \
    --query "Stacks[0].Outputs[?OutputKey=='UserPoolId'].OutputValue" \
    --output text)
```

## 📊 ログとモニタリング

### CloudWatch ログ
```bash
# ECS API ログ
aws logs tail /ecs/whiskey-api-dev --follow

# CloudFormation イベント
aws cloudformation describe-stack-events \
  --stack-name WhiskeyApp-Dev

# GitHub Actions実行ログ
# GitHubのWebUIで確認
```

### 重要なメトリクス
- ECS タスク実行数
- ALB ヘルスチェック状態
- DynamoDB スロットル
- CloudFront キャッシュヒット率

## 🛠️ 緊急時の対応

### 1. 全サービス再起動
```bash
# ECS サービス強制再デプロイ
aws ecs update-service \
  --cluster whiskey-api-cluster-dev \
  --service whiskey-api-service-dev \
  --force-new-deployment

# CloudFront キャッシュクリア
aws cloudfront create-invalidation \
  --distribution-id <distribution-id> \
  --paths "/*"
```

### 2. ロールバック
```bash
# 前のバージョンにロールバック
cd infra
git checkout <previous-commit>
npx cdk deploy WhiskeyApp-Dev
```

### 3. 緊急連絡先
- AWS サポート
- 開発チーム
- インフラ担当者

## ✅ デプロイ前チェックリスト

### インフラ
- [ ] AWS認証情報が設定されている
- [ ] CDKがbootstrapされている
- [ ] ドメインのRoute53ホストゾーンが存在する
- [ ] SSL証明書が有効

### GitHub Actions
- [ ] AWS_ROLE_ARN環境変数が設定されている
- [ ] リポジトリ名がCDKで正しく設定されている
- [ ] ブランチ保護ルールが適切

### アプリケーション
- [ ] Dockerイメージがローカルでビルドできる
- [ ] 環境変数が正しく設定されている
- [ ] ヘルスチェックエンドポイントが動作する
- [ ] フロントエンドがローカルでビルドできる 