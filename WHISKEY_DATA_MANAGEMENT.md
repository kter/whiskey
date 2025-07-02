# ウイスキーデータ管理手順書

## 概要
楽天市場API + Amazon Bedrock Nova Liteを使用して大規模ウイスキーデータを収集・抽出し、多言語対応DynamoDBに投入する手順書です。

## 🆕 最新実績（2025-07-02）
- **楽天API**: 3,037商品を取得
- **Nova Lite抽出**: 813件の高品質ウイスキーデータ
- **本番投入**: WhiskeySearch-prd テーブルに正常投入完了
- **検索対応**: 英語・日本語での高精度検索が可能

## 前提条件
- AWS Profile: `dev` または `prd` が設定済み
- Python環境: boto3, requests等がインストール済み
- Bedrock Nova Lite アクセス権限
- 楽天API キー（.env.rakuten ファイル）

## 🚀 新手順（大規模データ対応）

### 1. 楽天市場APIからデータ取得

#### 楽天APIキー設定
`.env.rakuten` ファイルに楽天APIキーを設定：
```bash
RAKUTEN_API_KEY=your_rakuten_api_key_here
```

#### 大規模データ取得実行
```bash
python scripts/fetch_rakuten_names_only.py
```

**実行結果（実績）:**
- 取得件数: 3,037商品名
- 実行時間: 約4分
- 出力ファイル: `rakuten_product_names_YYYYMMDD_HHMMSS.json`

### 2. Nova Liteによるウイスキー名抽出

#### AI抽出実行
```bash
python scripts/extract_whiskey_names_nova_lite.py --input-file rakuten_product_names_20250702_084016.json
```

**処理仕様:**
- AI モデル: Amazon Nova Lite（コスト最適化）
- バッチサイズ: 20件/バッチ
- 抽出精度: 45.3%（3,037件 → 1,375件抽出 → 813件高品質）
- 実行時間: 45分

**抽出実績:**
- 総ウイスキー: 1,375件
- 高信頼度: 1,352件（confidence ≥ 0.9）
- 重複除去後: 813件（最終投入数）

### 3. DynamoDB投入

#### 開発環境への投入
```bash
ENVIRONMENT=dev python scripts/insert_whiskeys_to_dynamodb.py nova_lite_extraction_results_20250702_094009.json
```

#### 本番環境への投入
```bash
ENVIRONMENT=prd python scripts/insert_whiskeys_to_dynamodb.py nova_lite_extraction_results_20250702_094009.json
```

**投入結果（実績）:**
- 投入件数: 813件
- 成功率: 100%（エラー発生も最終的に全件成功）
- 対象テーブル: WhiskeySearch-prd

### 5. 最終確認

#### DynamoDB件数確認
```bash
PAGER=cat AWS_PROFILE=dev aws dynamodb scan --table-name WhiskeySearch-dev --select COUNT
```

#### 検索機能テスト
```bash
# 英語検索テスト
curl -s "https://api.dev.whiskeybar.site/api/whiskeys/search/suggest/?q=tomatin&limit=5"

# 蒸留所検索テスト
curl -s "https://api.dev.whiskeybar.site/api/whiskeys/search/suggest/?q=bruichladdich&limit=5"
```

## 重要なファイル

### スクリプト
- `scripts/fetch_whiskey_data.py` - メインスクリプト
- `whiskey_data_fetch.log` - 実行ログ

### データファイル
- `raw_whiskey_data_YYYYMMDD_HHMMSS.json` - API取得データ
- `fetch_result_YYYYMMDD_HHMMSS.json` - 取得結果サマリ
- `process_result_YYYYMMDD_HHMMSS.json` - 処理結果サマリ

## トラブルシューティング

### 一般的な問題

1. **AWS認証エラー**
   ```bash
   aws configure list --profile dev
   ```

2. **スクリプト実行権限**
   ```bash
   chmod +x scripts/fetch_whiskey_data.py
   ```

3. **DynamoDB接続エラー**
   - リージョン確認: ap-northeast-1
   - テーブル名確認: WhiskeySearch-dev

### パフォーマンス最適化

- **API取得**: レート制限を6-10秒で調整可能
- **翻訳処理**: レート制限を0.3-1.0秒で調整可能
- **並列処理**: 現在は安全性重視でシーケンシャル処理

## 実行実績（2025-06-28）

- **取得件数**: 418件（TheWhiskyEdition API全件）
- **処理時間**: API取得1.5分 + 翻訳処理3-4分
- **成功率**: 100%（全件正常処理）
- **データサイズ**: 1.1MB（取得ファイル）

## セキュリティ注意事項

- AWS認証情報の安全な管理
- APIキーの適切な保護
- レート制限の遵守
- ログファイルの機密情報チェック

## 次回実行時の準備

1. 前回のデータファイルをバックアップ
2. ログファイルを確認
3. DynamoDB使用料金を確認
4. API変更がないか確認

---
**最終更新**: 2025-06-28  
**作成者**: Claude Code Assistant  
**バージョン**: 1.0