# 📚 Documentation Index

## 🚀 Getting Started

| Document | Description | Target Audience |
|----------|-------------|-----------------|
| **[README.md](./README.md)** | プロジェクト概要・アーキテクチャ・基本セットアップ | 全員 |
| **[DEPLOY.md](./DEPLOY.md)** | デプロイクイックガイド・環境構築 | DevOps・開発者 |
| **[CLAUDE.md](./CLAUDE.md)** | Claude Code用の開発ガイド | Claude・開発者 |

## 🏗️ Architecture & Infrastructure

| Document | Description | Target Audience |
|----------|-------------|-----------------|
| **[COST_OPTIMIZATION.md](./COST_OPTIMIZATION.md)** | コスト最適化分析・サーバーレス移行効果 | 管理者・アーキテクト |
| **[AWS_SETUP_GUIDE.md](./AWS_SETUP_GUIDE.md)** | AWS環境構築・権限設定 | DevOps・管理者 |
| **[FRONTEND_BACKEND_INTEGRATION.md](./FRONTEND_BACKEND_INTEGRATION.md)** | フロントエンド・バックエンド統合 | 開発者 |

## 📊 Data Management

| Document | Description | Target Audience |
|----------|-------------|-----------------|
| **[WHISKEY_DATA_MANAGEMENT.md](./WHISKEY_DATA_MANAGEMENT.md)** | 大規模ウイスキーデータ管理・Nova Lite抽出 | データ管理者・開発者 |
| **[BEDROCK_MODEL_COST_COMPARISON.md](./BEDROCK_MODEL_COST_COMPARISON.md)** | Bedrockモデル比較・コスト分析 | アーキテクト・データサイエンティスト |

## 🔧 API & Development

| Document | Description | Target Audience |
|----------|-------------|-----------------|
| **[API_REFERENCE.md](./API_REFERENCE.md)** | API仕様・エンドポイント・認証 | 開発者・フロントエンド |
| **[TROUBLESHOOTING.md](./TROUBLESHOOTING.md)** | トラブルシューティング・よくある問題 | 開発者・運用担当 |

## 🔐 Authentication & Security

| Document | Description | Target Audience |
|----------|-------------|-----------------|
| **[docs/GOOGLE_AUTH_SETUP.md](./docs/GOOGLE_AUTH_SETUP.md)** | Google OAuth設定手順 | 開発者・管理者 |

## 📈 Current Project Status

### ✅ Completed Features

#### 🏗️ Infrastructure
- **Serverless Architecture**: 完全サーバーレス移行完了
- **Cost Optimization**: 64-83% コスト削減達成
- **Multi-Environment**: dev/prd 環境分離

#### 🔍 Search & Data
- **Large-scale Data**: 813件の高品質ウイスキーデータ
- **Multi-language Search**: 英語・日本語対応
- **AI-powered Extraction**: Nova Lite による自動抽出

#### 🚀 Deployment & CI/CD  
- **GitHub Actions**: 自動デプロイパイプライン
- **Infrastructure as Code**: AWS CDK
- **Environment Management**: 環境別設定・デプロイ

### 🚧 In Progress

#### 📱 Frontend Enhancement
- レスポンシブデザイン改善
- 検索UX最適化
- パフォーマンス向上

#### 🔐 Authentication
- Google OAuth統合完了
- セッション管理最適化
- セキュリティ強化

### 📋 Upcoming Features

#### 短期（3ヶ月）
- ウイスキー詳細情報充実
- 検索フィルター機能
- お気に入り機能

#### 中期（6ヶ月）
- ソーシャル機能
- AI推奨エンジン
- 管理者機能

#### 長期（1年）
- モバイルアプリ(PWA)
- 分析・レポート機能
- 多言語拡張

## 🔗 Quick Links

### Development
```bash
# Local development
docker-compose up -d
cd frontend && npm run dev

# Data management
python scripts/fetch_rakuten_names_only.py
python scripts/extract_whiskey_names_nova_lite.py --input-file rakuten_product_names_*.json
```

### Deployment
```bash
# Infrastructure
cd infra && npm run deploy:dev

# Production data
ENVIRONMENT=prd python scripts/insert_whiskeys_to_dynamodb.py nova_lite_extraction_results_*.json
```

### API Testing
```bash
# English search
curl "https://api.whiskeybar.site/api/whiskeys/search/?q=bowmore"

# Japanese search
curl "https://api.whiskeybar.site/api/whiskeys/search/?q=%E3%83%9C%E3%82%A6%E3%83%A2%E3%82%A2"
```

## 📊 Key Metrics

| Metric | Value | Description |
|--------|-------|-------------|
| **Whiskey Database** | 813件 | 高品質ウイスキーデータ |
| **Search Languages** | 2言語 | 英語・日本語対応 |
| **Cost Reduction** | 64-83% | サーバーレス移行効果 |
| **API Response** | <200ms | 高速検索レスポンス |
| **Uptime** | 99.9%+ | サーバーレス高可用性 |

## 🆕 Recent Updates

### 2025-07-02
- ✅ **大規模データ投入**: 813件のウイスキーデータを本番投入
- ✅ **サーバーレス移行**: Lambda + API Gateway 完全移行
- ✅ **コスト最適化**: 月額$60-120削減達成
- ✅ **多言語検索**: 英語・日本語高精度検索実装
- ✅ **ドキュメント充実**: 全ドキュメント最新化

### 2025-06-28
- ✅ 基本インフラ構築
- ✅ 認証機能実装
- ✅ 初期データ投入

---

**Last Updated**: 2025-07-02  
**Project Status**: Production Ready  
**Next Milestone**: ユーザーフィードバック収集・機能拡張