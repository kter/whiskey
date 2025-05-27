# Google認証設定ガイド

## 📋 概要

AWS CognitoとGoogle OAuth2.0を連携して、メールアドレス入力なしでのサインインを実現します。

## 🛠️ 設定手順

### 1. Google Cloud Consoleでプロジェクト作成

1. [Google Cloud Console](https://console.cloud.google.com/) にアクセス
2. 新しいプロジェクトを作成（既存プロジェクトでも可）
3. プロジェクト名: `whiskey-auth` など

### 2. OAuth同意画面の設定

1. **APIとサービス** > **OAuth同意画面** に移動
2. **外部** を選択（一般ユーザー向け）
3. 以下の情報を入力：
   ```
   アプリケーション名: Whiskey Log
   ユーザーサポートメール: your-email@example.com
   承認済みドメイン: 
     - whiskeybar.site
     - dev.whiskeybar.site
   開発者の連絡先情報: your-email@example.com
   ```

### 3. OAuth2.0クライアントIDの作成

1. **APIとサービス** > **認証情報** に移動
2. **認証情報を作成** > **OAuth クライアント ID**
3. アプリケーションの種類: **ウェブアプリケーション**
4. 名前: `Whiskey Auth Client`
5. **承認済みのJavaScript生成元**:
   ```
   https://dev.whiskeybar.site
   https://whiskeybar.site
   http://localhost:3000  (開発用)
   ```
6. **承認済みのリダイレクト URI**:
   ```
   https://whiskey-users-dev.auth.ap-northeast-1.amazoncognito.com/oauth2/idpresponse
   https://whiskey-users-prod.auth.ap-northeast-1.amazoncognito.com/oauth2/idpresponse
   ```

### 4. 認証情報の取得

作成後、以下の情報をメモ：
- **クライアント ID**: `xxxxxxxxx.apps.googleusercontent.com`
- **クライアント シークレット**: `GOCSPX-xxxxxxxxx`

## 🔑 AWS Secrets Managerへの保存

```bash
# 開発環境
aws secretsmanager put-secret-value \
  --secret-id whiskey-app-secrets-dev \
  --secret-string '{
    "GOOGLE_CLIENT_ID": "your-google-client-id",
    "GOOGLE_CLIENT_SECRET": "your-google-client-secret"
  }'

# 本番環境  
aws secretsmanager put-secret-value \
  --secret-id whiskey-app-secrets-prod \
  --secret-string '{
    "GOOGLE_CLIENT_ID": "your-google-client-id", 
    "GOOGLE_CLIENT_SECRET": "your-google-client-secret"
  }'
```

## 📝 注意事項

1. **ドメイン認証**: Googleの承認済みドメインには実際に所有しているドメインのみ追加
2. **HTTPS必須**: 本番環境ではHTTPS必須
3. **スコープ設定**: email、profile、openidスコープが必要
4. **リダイレクトURI**: CognitoのUser Pool Domain URLと一致させる

## 🔄 次のステップ

1. Google認証情報を取得
2. AWS Secrets Managerに保存
3. CDK設定を更新してCognitoにGoogle Identity Providerを追加
4. フロントエンドにGoogle認証ボタンを実装 