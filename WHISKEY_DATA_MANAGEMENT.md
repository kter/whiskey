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

##### 仮想環境の作成
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r scripts/requirements.txt
```

##### 楽天APIの設定
```bash
export RAKUTEN_APP_ID="your_rakuten_api_key"
```

##### スクリプトの実行
```bash
python3 scripts/fetch_rakuten_names_only.py --max-items 500
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

### 3. DynamoDB投入【重要】

#### 事前確認
データ投入前に必ず以下を確認：

1. **AWS Profile確認**
```bash
aws configure list --profile prd
aws sts get-caller-identity --profile prd
```

2. **DynamoDB テーブル確認**
```bash
PAGER=cat AWS_PROFILE=prd aws dynamodb describe-table --table-name WhiskeySearch-prd
```

3. **現在のデータ件数確認**
```bash
PAGER=cat AWS_PROFILE=prd aws dynamodb scan --table-name WhiskeySearch-prd --select COUNT
```

#### 開発環境への投入
```bash
ENVIRONMENT=dev python scripts/insert_whiskeys_to_dynamodb.py nova_lite_extraction_results_20250702_094009.json
```

#### 本番環境への投入
```bash
ENVIRONMENT=prd python scripts/insert_whiskeys_to_dynamodb.py nova_lite_extraction_results_20250702_094009.json
```

**投入プロセス詳細:**

1. **データ読み込み**: Nova Lite抽出結果ファイルを読み込み
2. **データ検証**: confidence ≥ 0.9 のみ選別
3. **重複除去**: 完全一致のみ除去、バリエーションは保持
4. **データクリーニング**: DynamoDB制約に対応（空文字列 → "Unknown"）
5. **フォーマット変換**: DynamoDBスキーマに変換
6. **バッチ投入**: 25件ずつバッチ処理で投入
7. **エラー処理**: 失敗時の自動リトライ機能

**投入データ構造:**
```json
{
  "id": "uuid",
  "name": "ボウモア 12年",
  "name_en": "Bowmore 12 Year",
  "name_ja": "ボウモア 12年", 
  "distillery": "Bowmore",
  "distillery_en": "Bowmore",
  "distillery_ja": "ボウモア",
  "normalized_name_en": "bowmore12year",
  "normalized_name_ja": "ぼうもあ12ねん",
  "confidence": 0.95,
  "source": "rakuten_bedrock",
  "extraction_method": "nova_lite",
  "type": "Single Malt",
  "region": "Islay",
  "created_at": "2025-07-02T08:36:15.986943",
  "updated_at": "2025-07-02T08:36:15.986943"
}
```

**投入結果（実績）:**
- 投入件数: 813件
- 成功率: 100%（エラー発生も最終的に全件成功）
- 対象テーブル: WhiskeySearch-prd
- 所要時間: 約3分
- GSI更新: 自動で NameEnIndex, NameJaIndex に反映

#### データ投入エラー対応

**よくあるエラーと対処法:**

1. **Float型エラー**
```
Float types are not supported. Use Decimal types instead
```
→ 対処: confidence値をDecimal型に変換（スクリプト内で自動処理）

2. **ResourceNotFoundException**
```
Table 'WhiskeySearch-prod' not found
```
→ 対処: テーブル名をWhiskeySearch-prdに修正（環境設定確認）

3. **ValidationException**
```
One or more parameter values were invalid
```
→ 対処: 空文字列をNullまたは"Unknown"に変換

4. **ProvisionedThroughputExceededException**
```
Rate limit exceeded
```
→ 対処: バッチサイズを小さく（25件 → 10件）、待機時間追加

#### 投入後確認

1. **件数確認**
```bash
PAGER=cat AWS_PROFILE=prd aws dynamodb scan --table-name WhiskeySearch-prd --select COUNT
```

2. **統計情報確認**
```bash
ENVIRONMENT=prd python scripts/insert_whiskeys_to_dynamodb.py --stats
```

3. **サンプルデータ確認**
```bash
PAGER=cat AWS_PROFILE=prd aws dynamodb scan --table-name WhiskeySearch-prd --limit 3
```

### 4. 最終確認

#### 検索機能テスト（重要）
データ投入後は必ず検索機能をテストして正常性を確認：

```bash
# 英語検索テスト
curl -s "https://api.whiskeybar.site/api/whiskeys/search/?q=bowmore" | jq '.count'

# 日本語検索テスト（URLエンコード必須）
curl -s "https://api.whiskeybar.site/api/whiskeys/search/?q=%E3%83%9C%E3%82%A6%E3%83%A2%E3%82%A2" | jq '.count'

# 蒸留所検索テスト
curl -s "https://api.whiskeybar.site/api/whiskeys/search/?q=macallan" | jq '.count'

# サジェスト機能テスト
curl -s "https://api.whiskeybar.site/api/whiskeys/search/suggest/?q=glenlivet&limit=3" | jq '.whiskeys[].name'
```

**期待される結果:**
- 各検索で適切な件数の結果が返却される
- 日本語検索が正常に動作する
- エラーレスポンスがない

#### パフォーマンステスト
```bash
# 空クエリテスト（大量データ対応確認）
time curl -s "https://api.whiskeybar.site/api/whiskeys/search/?q=" | jq '.count'

# レスポンス時間確認（200ms以下が目標）
time curl -s "https://api.whiskeybar.site/api/whiskeys/search/?q=whisky" > /dev/null
```

### 5. データ投入完全チェックリスト

#### 事前準備 ✅
- [ ] AWS Profile確認（`aws sts get-caller-identity --profile prd`）
- [ ] DynamoDBテーブル存在確認
- [ ] 現在のデータ件数記録
- [ ] 抽出結果ファイル準備
- [ ] バックアップ計画確認

#### 投入実行 ✅
- [ ] 開発環境での動作確認
- [ ] 本番環境での投入実行
- [ ] エラーログ監視
- [ ] 投入完了確認

#### 事後確認 ✅
- [ ] データ件数確認
- [ ] 統計情報確認
- [ ] 英語検索テスト
- [ ] 日本語検索テスト
- [ ] パフォーマンステスト
- [ ] エラーレート確認

## 重要なファイルとディレクトリ

### 現行スクリプト（最新版）
- `scripts/fetch_rakuten_names_only.py` - 楽天API大規模データ取得
- `scripts/extract_whiskey_names_nova_lite.py` - Nova Lite AI抽出
- `scripts/insert_whiskeys_to_dynamodb.py` - DynamoDB投入（重複除去機能付）
- `backend/api/whiskey_search_service.py` - DynamoDBサービス（統計・管理機能）

### 生成されるデータファイル
- `rakuten_product_names_YYYYMMDD_HHMMSS.json` - 楽天API取得データ
- `nova_lite_extraction_results_YYYYMMDD_HHMMSS.json` - AI抽出結果
- `whiskey_data_*.log` - 実行ログファイル

### アーカイブディレクトリ
- `scripts/archive/` - 過去の手法・スクリプト（参考用）
  - 旧TheWhiskyEdition API手法
  - 旧Claude 3.5 Haiku手法
  - ルールベース抽出手法

## トラブルシューティング

### データ投入関連のトラブル

#### 1. AWS認証エラー
```bash
# 認証情報確認
aws configure list --profile prd
aws sts get-caller-identity --profile prd

# プロファイル再設定（必要に応じて）
aws configure --profile prd
```

#### 2. DynamoDB接続エラー
```bash
# テーブル存在確認
PAGER=cat AWS_PROFILE=prd aws dynamodb describe-table --table-name WhiskeySearch-prd

# リージョン確認（ap-northeast-1である必要）
aws configure get region --profile prd
```

#### 3. 投入スクリプトエラー
```bash
# Python依存関係確認
pip install boto3 requests

# スクリプト実行権限
chmod +x scripts/insert_whiskeys_to_dynamodb.py

# 詳細ログで実行
ENVIRONMENT=prd python -v scripts/insert_whiskeys_to_dynamodb.py <file>
```

#### 4. データ形式エラー
```bash
# 抽出結果ファイル形式確認
head -20 nova_lite_extraction_results_*.json

# ファイルサイズ確認（0バイトでないか）
ls -la nova_lite_extraction_results_*.json
```

#### 5. DynamoDB容量エラー
```bash
# テーブル使用量確認
PAGER=cat AWS_PROFILE=prd aws dynamodb describe-table --table-name WhiskeySearch-prd | jq '.Table.TableSizeBytes'

# オンデマンド課金確認
PAGER=cat AWS_PROFILE=prd aws dynamodb describe-table --table-name WhiskeySearch-prd | jq '.Table.BillingModeSummary'
```

### 検索機能関連のトラブル

#### 1. 日本語検索が動作しない
```bash
# URLエンコード確認
python3 -c "import urllib.parse; print(urllib.parse.quote('ボウモア'))"

# 正しいエンコード例
curl -s "https://api.whiskeybar.site/api/whiskeys/search/?q=%E3%83%9C%E3%82%A6%E3%83%A2%E3%82%A2"
```

#### 2. 検索結果が0件
```bash
# DynamoDBデータ確認
PAGER=cat AWS_PROFILE=prd aws dynamodb scan --table-name WhiskeySearch-prd --limit 1

# Lambda ログ確認
PAGER=cat AWS_PROFILE=prd aws logs tail /aws/lambda/whiskey-search-prd --since 5m
```

#### 3. API応答が遅い
```bash
# パフォーマンス測定
time curl -s "https://api.whiskeybar.site/api/whiskeys/search/?q=test" > /dev/null

# CloudWatch メトリクス確認
PAGER=cat AWS_PROFILE=prd aws logs tail /aws/lambda/whiskey-search-prd --since 10m | grep Duration
```

### 緊急時の対応手順

#### データベース復旧
```bash
# 1. 現在のデータバックアップ
PAGER=cat AWS_PROFILE=prd aws dynamodb scan --table-name WhiskeySearch-prd > backup_$(date +%Y%m%d_%H%M%S).json

# 2. 全データ削除（緊急時のみ）
ENVIRONMENT=prd python scripts/insert_whiskeys_to_dynamodb.py --clear

# 3. 最新データで復旧
ENVIRONMENT=prd python scripts/insert_whiskeys_to_dynamodb.py <latest_extraction_file>
```

#### ロールバック手順
```bash
# 1. CDKでインフラロールバック
cd infra && AWS_PROFILE=prd npm run deploy:prd

# 2. Lambda関数ロールバック
PAGER=cat AWS_PROFILE=prd aws lambda list-versions-by-function --function-name whiskey-search-prd

# 3. 旧バージョンに切り戻し
PAGER=cat AWS_PROFILE=prd aws lambda update-alias --function-name whiskey-search-prd --name LIVE --function-version <version>
```

## 運用チェックリスト

### 月次メンテナンス
- [ ] DynamoDB使用量・コスト確認
- [ ] 検索パフォーマンス測定
- [ ] エラーログ確認
- [ ] データ品質チェック

### 四半期メンテナンス
- [ ] 新しいウイスキーデータ追加
- [ ] 重複データクリーニング
- [ ] インデックス最適化検討
- [ ] セキュリティパッチ適用

### 年次メンテナンス  
- [ ] 全データベースリフレッシュ
- [ ] アーキテクチャ見直し
- [ ] パフォーマンス最適化
- [ ] 災害復旧テスト

## データ投入の教訓とベストプラクティス

### 成功要因
1. **事前確認の徹底**: AWS Profile、テーブル存在、権限確認
2. **段階的実行**: dev環境での検証 → 本番投入
3. **重複除去ロジック**: 完全一致のみ除去、バリエーション保持
4. **エラーハンドリング**: Decimal型変換、空文字列対応
5. **検証の自動化**: 投入後の検索機能テスト

### 避けるべき失敗パターン
1. ❌ 環境名の間違い（prod vs prd）
2. ❌ Float型でのDynamoDB投入
3. ❌ 重複除去の過剰実行
4. ❌ 投入後の検証不足
5. ❌ バックアップなしでの全削除

### 次回改善点
1. **並列処理**: バッチサイズ最適化
2. **監視強化**: CloudWatch アラーム設定
3. **自動化**: CI/CDパイプライン統合
4. **データ品質**: 信頼度閾値の動的調整

---
**最終更新**: 2025-07-02  
**作成者**: Claude Code Assistant  
**バージョン**: 2.0（データ投入手順詳細化版）