# API Reference - Whiskey Search API

## 🔗 Base URLs

| Environment | URL |
|-------------|-----|
| **Production** | `https://api.whiskeybar.site` |
| **Development** | `https://api.dev.whiskeybar.site` |

## 🔍 Search API

### Whiskey Search

**エンドポイント**: `GET /api/whiskeys/search/`

多言語対応のウイスキー検索API。英語・日本語での高精度検索が可能。

#### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `q` | string | Yes | 検索クエリ（英語・日本語対応） |
| `limit` | integer | No | 結果数制限（デフォルト: 50） |

#### Request Examples

```bash
# 英語検索
curl "https://api.whiskeybar.site/api/whiskeys/search/?q=bowmore"

# 日本語検索（URLエンコード必須）
curl "https://api.whiskeybar.site/api/whiskeys/search/?q=%E3%83%9C%E3%82%A6%E3%83%A2%E3%82%A2"

# 制限付き検索
curl "https://api.whiskeybar.site/api/whiskeys/search/?q=macallan&limit=10"
```

#### Response

```json
{
  "whiskeys": [
    {
      "id": "425757e4-5d6f-4d09-89bc-1f2eb00510e9",
      "name": "ボウモア 12年",
      "name_en": "Bowmore 12 Year",
      "name_ja": "ボウモア 12年",
      "distillery": "Bowmore",
      "region": "Islay",
      "type": "Single Malt",
      "confidence": 0.9,
      "source": "rakuten_bedrock",
      "created_at": "2025-07-02T08:36:15.986943",
      "updated_at": "2025-07-02T08:36:15.986943"
    }
  ],
  "count": 4,
  "query": "bowmore",
  "distillery": ""
}
```

### Search Suggestions

**エンドポイント**: `GET /api/whiskeys/search/suggest/`

検索候補を高速で返すAPI。

#### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `q` | string | Yes | 検索クエリ |
| `limit` | integer | No | 候補数制限（デフォルト: 5） |

#### Example

```bash
curl "https://api.whiskeybar.site/api/whiskeys/search/suggest/?q=mac&limit=5"
```

## 📋 Whiskey List API

### List Whiskeys

**エンドポイント**: `GET /api/whiskeys/`

ウイスキー一覧を取得。

#### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `limit` | integer | No | 結果数制限（デフォルト: 50） |
| `offset` | integer | No | オフセット（デフォルト: 0） |

#### Example

```bash
curl "https://api.whiskeybar.site/api/whiskeys/?limit=20&offset=0"
```

### Whiskey Ranking

**エンドポイント**: `GET /api/whiskeys/ranking/`

人気ウイスキーランキングを取得。

#### Example

```bash
curl "https://api.whiskeybar.site/api/whiskeys/ranking/"
```

## 📝 Reviews API

### Create Review

**エンドポイント**: `POST /api/reviews/`

レビューを作成。認証が必要。

#### Request Headers

```
Authorization: Bearer <access_token>
Content-Type: application/json
```

#### Request Body

```json
{
  "whiskey_id": "uuid",
  "rating": 4.5,
  "notes": "テイスティングノート",
  "serving_style": "neat",
  "date": "2025-07-02",
  "image_url": "https://example.com/image.jpg"
}
```

#### Example

```bash
curl -X POST "https://api.whiskeybar.site/api/reviews/" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "whiskey_id": "425757e4-5d6f-4d09-89bc-1f2eb00510e9",
    "rating": 4.5,
    "notes": "スモーキーで複雑な味わい",
    "serving_style": "neat",
    "date": "2025-07-02"
  }'
```

### List Reviews

**エンドポイント**: `GET /api/reviews/`

ユーザーのレビュー一覧を取得。認証が必要。

#### Request Headers

```
Authorization: Bearer <access_token>
```

#### Example

```bash
curl "https://api.whiskeybar.site/api/reviews/" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}"
```

## 🔧 Health Check

### Health Status

**エンドポイント**: `GET /health/`

APIの稼働状況を確認。

#### Example

```bash
curl "https://api.whiskeybar.site/health/"
```

#### Response

```json
{
  "status": "healthy",
  "timestamp": "2025-07-02T10:08:00Z",
  "version": "1.0.0"
}
```

## 🚨 Error Responses

### Error Format

```json
{
  "error": "error_code",
  "message": "Human readable error message",
  "details": {
    "field": "Additional error details"
  },
  "timestamp": "2025-07-02T10:08:00Z"
}
```

### Common Status Codes

| Status Code | Description |
|-------------|-------------|
| `200` | Success |
| `400` | Bad Request - Invalid parameters |
| `401` | Unauthorized - Invalid or missing token |
| `403` | Forbidden - Insufficient permissions |
| `404` | Not Found - Resource not found |
| `429` | Too Many Requests - Rate limit exceeded |
| `500` | Internal Server Error |

## 🔐 Authentication

### JWT Token

API認証にはJWTトークンを使用します。

#### Token取得

Cognitoを通じてトークンを取得：

```javascript
// Frontend (Nuxt.js)
const { tokens } = await $auth.signIn(username, password)
const accessToken = tokens.AccessToken
```

#### Token使用

```bash
curl "https://api.whiskeybar.site/api/reviews/" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}"
```

#### Token Refresh

```javascript
// Automatic refresh handled by Amplify
await $auth.currentSession()
```

## 📊 Data Models

### Whiskey Object

```typescript
interface Whiskey {
  id: string;
  name: string;
  name_en?: string;
  name_ja?: string;
  distillery: string;
  region?: string;
  type?: string;
  confidence?: number;
  source?: string;
  created_at: string;
  updated_at: string;
}
```

### Review Object

```typescript
interface Review {
  id: string;
  whiskey_id: string;
  user_id: string;
  rating: number;
  notes?: string;
  serving_style?: string;
  date: string;
  image_url?: string;
  created_at: string;
  updated_at: string;
}
```

## 🌍 Multi-language Support

### Search Language Detection

APIは自動的に検索言語を判定：

- **英語**: ラテン文字で検索
- **日本語**: ひらがな・カタカナ・漢字で検索

### URL Encoding

日本語検索時はURLエンコードが必要：

```bash
# ✅ 正しい
curl "https://api.whiskeybar.site/api/whiskeys/search/?q=%E3%83%9C%E3%82%A6%E3%83%A2%E3%82%A2"

# ❌ 文字化け
curl "https://api.whiskeybar.site/api/whiskeys/search/?q=ボウモア"
```

## 📈 Rate Limiting

### Current Limits

- **Search API**: 100 requests/minute
- **Reviews API**: 50 requests/minute
- **Auth Required**: 1000 requests/hour per user

### Headers

Response headers include rate limit info:

```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 95
X-RateLimit-Reset: 1641024000
```

## 🔍 Search Examples

### Popular Searches

```bash
# スコッチウイスキー
curl "https://api.whiskeybar.site/api/whiskeys/search/?q=macallan"
curl "https://api.whiskeybar.site/api/whiskeys/search/?q=glenfiddich"

# ジャパニーズウイスキー
curl "https://api.whiskeybar.site/api/whiskeys/search/?q=%E5%B1%B1%E5%B4%8E"
curl "https://api.whiskeybar.site/api/whiskeys/search/?q=%E7%99%BD%E5%B7%9E"

# アメリカンウイスキー
curl "https://api.whiskeybar.site/api/whiskeys/search/?q=bourbon"
curl "https://api.whiskeybar.site/api/whiskeys/search/?q=jack"
```

---

**Database**: 813件の高品質ウイスキーデータ  
**Last Updated**: 2025-07-02  
**API Version**: 1.0.0