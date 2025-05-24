# フロントエンド・バックエンド連携ガイド

## 📊 現在の連携状況

### ✅ **連携できている部分**

#### 1. **基本的なAPI構造**
- ✅ RESTful API エンドポイント定義済み
- ✅ DynamoDB連携のバックエンド実装完了
- ✅ フロントエンドのAPI呼び出し関数実装済み
- ✅ Docker Compose でのローカル環境構築

#### 2. **データ型の一致**
- ✅ TypeScript型定義とバックエンドAPIの整合性
- ✅ Review, Whiskey, RankingItem 構造の一致

#### 3. **基本的な環境構築**
- ✅ Nuxt.js + Django構成
- ✅ LocalStack統合
- ✅ AWS CDKインフラ定義

### ❌ **修正が必要な部分**

#### 1. **認証連携（重要度: 高）**
- ❌ AWS Cognito認証が無効化されている
- ❌ フロントエンドでダミー認証実装
- ❌ トークンベース認証の未実装

#### 2. **環境変数の不整合（重要度: 中）**
- ❌ CDK構成とフロントエンド環境変数名の不一致
- ❌ GitHub Actionsワークフローとの変数名不整合

#### 3. **S3画像アップロード（重要度: 中）**
- ❌ プリサインドURL生成機能の未テスト
- ❌ フロントエンド画像アップロード機能の未実装

## 🔧 修正済み項目

### 1. ✅ 環境変数名の統一
```typescript
// 統一後のNuxt.js環境変数
NUXT_PUBLIC_API_BASE_URL
NUXT_PUBLIC_USER_POOL_ID
NUXT_PUBLIC_USER_POOL_CLIENT_ID
NUXT_PUBLIC_REGION
NUXT_PUBLIC_IMAGES_BUCKET
NUXT_PUBLIC_ENVIRONMENT
```

### 2. ✅ AWS Amplify認証機能の有効化
```typescript
// frontend/composables/useAuth.ts
// ダミー実装を削除して実際のCognito認証を実装
```

### 3. ✅ Docker Compose環境変数の更新
CDK構成と統一した環境変数名に更新済み

## 🚧 残りの作業

### 1. **AWS環境での認証テスト**

#### 手順
```bash
# 1. AWS環境にデプロイ
cd infra
./scripts/deploy.sh dev

# 2. 出力されたCognito情報を確認
aws cloudformation describe-stacks \
  --stack-name WhiskeyApp-Dev \
  --query 'Stacks[0].Outputs[?contains(OutputKey,`UserPool`)].{Key:OutputKey,Value:OutputValue}' \
  --output table

# 3. 環境変数ファイルの更新
cat > frontend/.env.local << EOF
NUXT_PUBLIC_USER_POOL_ID=ap-northeast-1_XXXXXXXXX
NUXT_PUBLIC_USER_POOL_CLIENT_ID=XXXXXXXXXXXXXXXXXXXXXXXXXX
NUXT_PUBLIC_REGION=ap-northeast-1
NUXT_PUBLIC_API_BASE_URL=https://api-dev.your-domain.com
NUXT_PUBLIC_ENVIRONMENT=dev
EOF
```

### 2. **Cognito認証フローのテスト**

#### 必要な作業
1. **ユーザー登録機能の実装**
   ```vue
   <!-- pages/signup.vue -->
   <template>
     <div>
       <h1>新規登録</h1>
       <form @submit.prevent="handleSignUp">
         <input v-model="form.email" type="email" placeholder="メールアドレス" required>
         <input v-model="form.password" type="password" placeholder="パスワード" required>
         <button type="submit">登録</button>
       </form>
     </div>
   </template>
   ```

2. **サインイン/サインアウト機能のテスト**
   ```vue
   <!-- pages/login.vue -->
   <template>
     <div>
       <h1>ログイン</h1>
       <form @submit.prevent="handleLogin">
         <input v-model="form.email" type="email" placeholder="メールアドレス" required>
         <input v-model="form.password" type="password" placeholder="パスワード" required>
         <button type="submit">ログイン</button>
       </form>
     </div>
   </template>
   ```

### 3. **S3画像アップロード機能の実装**

#### バックエンド（既に実装済み）
```python
# backend/api/views.py - S3UploadUrlView
# プリサインドURL生成機能は実装済み
```

#### フロントエンド実装例
```typescript
// composables/useS3Upload.ts
export const useS3Upload = () => {
  const config = useRuntimeConfig()
  
  const uploadImage = async (file: File) => {
    // 1. プリサインドURL取得
    const { uploadUrl, imageUrl } = await getPresignedUrl(file.name)
    
    // 2. S3に直接アップロード
    await fetch(uploadUrl, {
      method: 'PUT',
      body: file,
      headers: {
        'Content-Type': file.type
      }
    })
    
    return imageUrl
  }
  
  return { uploadImage }
}
```

### 4. **API認証ヘッダーの統合**

#### 現在の状況
```typescript
// useWhiskeys.ts - トークンは取得しているが検証が必要
const token = await getToken()
const response = await fetch(url, {
  headers: {
    Authorization: `Bearer ${token}`
  }
})
```

#### 必要な確認
- Cognito JWTトークンの正しい取得
- バックエンドでのトークン検証
- エラーハンドリングの実装

## 🧪 連携テスト手順

### 1. **ローカル環境テスト**
```bash
# Docker環境起動
docker-compose up -d

# 連携テスト実行
./scripts/test-connection.sh
```

### 2. **AWS環境テスト**
```bash
# インフラデプロイ
cd infra && ./scripts/deploy.sh dev

# フロントエンドデプロイ（GitHub Actions）
git push origin develop
```

### 3. **認証フローテスト**
1. Cognito User Poolでテストユーザー作成
2. フロントエンドでサインイン
3. 認証が必要なAPIエンドポイントへのアクセステスト
4. トークン有効期限のテスト

### 4. **画像アップロードテスト**
1. プリサインドURL生成API呼び出し
2. S3への画像アップロード
3. アップロードした画像の表示確認

## 📚 トラブルシューティング

### よくある問題

#### 1. **CORS エラー**
```javascript
// バックエンド設定確認
CORS_ALLOWED_ORIGINS = [
    "http://localhost:3000",      // ローカル開発
    "https://your-cloudfront-domain.com"  // AWS環境
]
```

#### 2. **Cognito認証エラー**
```bash
# 環境変数の確認
echo $NUXT_PUBLIC_USER_POOL_ID
echo $NUXT_PUBLIC_USER_POOL_CLIENT_ID

# Amplify設定の確認
console.log(Amplify.getConfig())
```

#### 3. **API接続エラー**
```bash
# ネットワーク確認
curl -v http://localhost:8000/api/whiskeys/ranking/

# 環境変数確認
echo $NUXT_PUBLIC_API_BASE_URL
```

## 🎯 優先順位

1. **高優先度**: Cognito認証の完全実装とテスト
2. **中優先度**: S3画像アップロード機能の実装
3. **低優先度**: エラーハンドリングの改善

## 📋 チェックリスト

### 認証機能
- [ ] AWS Cognito User Pool作成確認
- [ ] フロントエンド Amplify設定
- [ ] サインアップ/サインイン画面実装
- [ ] トークン認証のE2Eテスト

### API連携
- [ ] 全エンドポイントの動作確認
- [ ] エラーレスポンスの統一
- [ ] ページネーションの動作確認

### 画像機能
- [ ] S3バケット設定確認
- [ ] プリサインドURL生成テスト
- [ ] 画像アップロード機能実装
- [ ] 画像表示機能実装

### デプロイ
- [ ] GitHub Actionsの動作確認
- [ ] 環境変数の正しい設定
- [ ] AWS環境での動作確認 