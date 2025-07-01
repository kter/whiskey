# ウイスキーデータ管理手順書

## 概要
TheWhiskyEdition APIから全件ウイスキーデータを取得し、多言語翻訳してDynamoDBに保存する手順です。

## 前提条件
- AWS Profile: `dev` が設定済み
- Python環境: boto3, requests等がインストール済み
- 環境変数: `AWS_PROFILE=dev`, `ENVIRONMENT=dev`

## 手順

### 1. 既存データのクリア

#### DynamoDBテーブル確認
```bash
PAGER=cat AWS_PROFILE=dev aws dynamodb scan --table-name WhiskeySearch-dev --select COUNT
```

#### 全データ削除
```bash
AWS_PROFILE=dev python3 -c "
import boto3
import os

# 環境変数設定で確実にprofileを使用
os.environ['AWS_PROFILE'] = 'dev'

dynamodb = boto3.resource('dynamodb', region_name='ap-northeast-1')
table = dynamodb.Table('WhiskeySearch-dev')

print('DynamoDB全データ削除開始...')

response = table.scan()
items = response['Items']
total_deleted = 0

while items:
    with table.batch_writer() as batch:
        for item in items:
            batch.delete_item(Key={'id': item['id']})
            total_deleted += 1
    
    if 'LastEvaluatedKey' in response:
        response = table.scan(ExclusiveStartKey=response['LastEvaluatedKey'])
        items = response['Items']
    else:
        items = []

print(f'削除完了: {total_deleted}件')

# 確認
count_response = table.scan(Select='COUNT')
print(f'残存件数: {count_response[\"Count\"]}件')
"
```

### 2. API全件データ取得

#### スクリプト修正確認
`scripts/fetch_whiskey_data.py`の95-96行目が以下になっていることを確認：
```python
# limit=0の場合は制限なし（無限ループ防止のため最大10000件）
max_items = limit if limit > 0 else 10000
```

#### 全件取得実行
```bash
AWS_PROFILE=dev ENVIRONMENT=dev python3 scripts/fetch_whiskey_data.py --mode fetch --whiskeys 0 --distilleries 0
```

**実行結果例:**
- 実行時間: 約1.5分（418件の場合）
- レート制限: 8秒間隔で安全取得
- 出力ファイル: `raw_whiskey_data_YYYYMMDD_HHMMSS.json`

### 3. 取得データ検証

#### ファイルサイズ・件数確認
```bash
ls -la raw_whiskey_data_*.json
```

#### データ構造確認
```bash
head -20 raw_whiskey_data_*.json
```

### 4. 翻訳・DynamoDB保存

#### 処理実行
```bash
AWS_PROFILE=dev ENVIRONMENT=dev python3 scripts/fetch_whiskey_data.py --mode process --file raw_whiskey_data_YYYYMMDD_HHMMSS.json
```

**処理仕様:**
- 翻訳レート制限: 0.5秒間隔
- 蒸留所名デフォルト値: 空の場合「No distillery provided」「蒸留所情報なし」
- Float→Decimal変換: DynamoDB用
- 推定時間: 418件で約3-4分

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