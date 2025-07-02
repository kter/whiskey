"""
楽天市場API+Bedrock専用の簡素化されたウイスキー検索サービス
バイリンガル対応を削除し、日本語のみに最適化
"""

import boto3
import os
import uuid
import time
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional, Any
from boto3.dynamodb.conditions import Key, Attr


class WhiskeySearchService:
    def __init__(self):
        self.region = os.getenv('AWS_REGION', 'ap-northeast-1')
        endpoint_url = os.getenv('AWS_ENDPOINT_URL')
        
        # 環境に応じたテーブル名を設定
        environment = os.getenv('ENVIRONMENT', 'dev')
        self.whiskey_table_name = f'WhiskeySearch-{environment}'
        
        if endpoint_url:
            # LocalStack環境
            self.dynamodb = boto3.resource(
                'dynamodb',
                region_name=self.region,
                endpoint_url=endpoint_url,
                aws_access_key_id='dummy',
                aws_secret_access_key='dummy'
            )
        else:
            # 本番環境
            self.dynamodb = boto3.resource('dynamodb', region_name=self.region)
        
        # テーブル参照の初期化（遅延読み込み）
        self._whiskey_table = None
    
    @property
    def whiskey_table(self):
        if self._whiskey_table is None:
            try:
                self._whiskey_table = self.dynamodb.Table(self.whiskey_table_name)
                # テーブルの存在確認
                self._whiskey_table.load()
            except Exception as e:
                print(f"WhiskeySearch table {self.whiskey_table_name} not found, creating: {e}")
                self._create_whiskey_table()
                # 作成後に少し待機
                time.sleep(2)
                self._whiskey_table = self.dynamodb.Table(self.whiskey_table_name)
        return self._whiskey_table
    
    def _create_whiskey_table(self):
        """ウイスキー検索テーブルを作成（日本語専用）"""
        try:
            table = self.dynamodb.create_table(
                TableName=self.whiskey_table_name,
                KeySchema=[
                    {'AttributeName': 'id', 'KeyType': 'HASH'}
                ],
                AttributeDefinitions=[
                    {'AttributeName': 'id', 'AttributeType': 'S'},
                    {'AttributeName': 'normalized_name', 'AttributeType': 'S'},
                    {'AttributeName': 'normalized_distillery', 'AttributeType': 'S'}
                ],
                GlobalSecondaryIndexes=[
                    {
                        'IndexName': 'NameIndex',
                        'KeySchema': [
                            {'AttributeName': 'normalized_name', 'KeyType': 'HASH'}
                        ],
                        'Projection': {'ProjectionType': 'ALL'}
                    },
                    {
                        'IndexName': 'DistilleryIndex', 
                        'KeySchema': [
                            {'AttributeName': 'normalized_distillery', 'KeyType': 'HASH'}
                        ],
                        'Projection': {'ProjectionType': 'ALL'}
                    }
                ],
                BillingMode='PAY_PER_REQUEST'
            )
            print("Created WhiskeySearch table (Japanese only)")
            return table
        except Exception as e:
            print(f"Error creating WhiskeySearch table: {e}")
            return None

    def _serialize_item(self, item: Dict) -> Dict:
        """Decimal型を適切な型に変換"""
        if isinstance(item, dict):
            return {k: self._serialize_item(v) for k, v in item.items()}
        elif isinstance(item, list):
            return [self._serialize_item(v) for v in item]
        elif isinstance(item, Decimal):
            return float(item) if item % 1 else int(item)
        else:
            return item

    def create_whiskey_entry(self, whiskey_data: Dict) -> Dict:
        """ウィスキーエントリを作成（簡素化版）"""
        try:
            self.whiskey_table.put_item(Item=whiskey_data)
            return self._serialize_item(whiskey_data)
        except Exception as e:
            print(f"Error creating whiskey entry: {e}")
            raise

    def bulk_insert_whiskeys(self, whiskey_list: List[Dict]) -> int:
        """ウィスキーデータを一括挿入"""
        success_count = 0
        batch_size = 25  # DynamoDB BatchWriteItemの制限
        
        # バッチ処理
        for i in range(0, len(whiskey_list), batch_size):
            batch = whiskey_list[i:i + batch_size]
            
            try:
                with self.whiskey_table.batch_writer() as batch_writer:
                    for whiskey_data in batch:
                        batch_writer.put_item(Item=whiskey_data)
                        success_count += 1
                
                print(f"バッチ {i//batch_size + 1} 完了: {len(batch)}件")
                
            except Exception as e:
                print(f"バッチ挿入エラー: {e}")
                # 個別挿入でリトライ
                for whiskey_data in batch:
                    try:
                        self.create_whiskey_entry(whiskey_data)
                        success_count += 1
                    except Exception as individual_error:
                        print(f"個別挿入失敗: {individual_error}")
                        continue
        
        print(f"一括挿入完了: {success_count}/{len(whiskey_list)}件")
        return success_count

    def search_whiskeys(self, query: str, limit: int = 10) -> List[Dict]:
        """ウィスキーを検索（日本語専用）"""
        if not query or len(query) < 1:
            # 空クエリの場合は全件取得
            try:
                response = self.whiskey_table.scan(Limit=limit)
                return [self._serialize_item(item) for item in response.get('Items', [])]
            except Exception as e:
                print(f"Error getting all whiskeys: {e}")
                return []
        
        normalized_query = self._normalize_text(query)
        results = []
        
        try:
            # 1. 部分一致検索（メイン検索）
            # 名前とディスティラリーの両方で部分一致
            response = self.whiskey_table.scan(
                FilterExpression=Attr('name').contains(query) | 
                                Attr('distillery').contains(query) |
                                Attr('normalized_name').contains(normalized_query) |
                                Attr('normalized_distillery').contains(normalized_query),
                Limit=limit
            )
            results.extend(response.get('Items', []))
            
            # 2. 完全一致検索（GSI使用）
            if len(results) < limit and normalized_query:
                try:
                    response = self.whiskey_table.query(
                        IndexName='NameIndex',
                        KeyConditionExpression=Key('normalized_name').eq(normalized_query),
                        Limit=limit - len(results)
                    )
                    results.extend(response.get('Items', []))
                except Exception:
                    pass  # GSIエラーは無視
            
            # 3. 蒸留所での完全一致検索
            if len(results) < limit and normalized_query:
                try:
                    response = self.whiskey_table.query(
                        IndexName='DistilleryIndex',
                        KeyConditionExpression=Key('normalized_distillery').eq(normalized_query),
                        Limit=limit - len(results)
                    )
                    results.extend(response.get('Items', []))
                except Exception:
                    pass  # GSIエラーは無視
            
            # 重複除去
            seen_ids = set()
            unique_results = []
            for item in results:
                if item['id'] not in seen_ids:
                    seen_ids.add(item['id'])
                    unique_results.append(self._serialize_item(item))
            
            return unique_results[:limit]
        except Exception as e:
            print(f"Error searching whiskeys: {e}")
            return []

    def get_whiskey_by_id(self, whiskey_id: str) -> Optional[Dict]:
        """IDでウィスキーを取得"""
        try:
            response = self.whiskey_table.get_item(Key={'id': whiskey_id})
            return self._serialize_item(response.get('Item')) if 'Item' in response else None
        except Exception as e:
            print(f"Error getting whiskey {whiskey_id}: {e}")
            return None

    def get_high_confidence_whiskeys(self, confidence_threshold: float = 0.9, limit: int = 100) -> List[Dict]:
        """高信頼度ウィスキーリストを取得"""
        try:
            response = self.whiskey_table.scan(
                FilterExpression=Attr('confidence').gte(confidence_threshold),
                Limit=limit
            )
            items = [self._serialize_item(item) for item in response['Items']]
            
            # 信頼度でソート
            items.sort(key=lambda x: x.get('confidence', 0), reverse=True)
            return items
        except Exception as e:
            print(f"Error getting high confidence whiskeys: {e}")
            return []

    def get_whiskey_statistics(self) -> Dict:
        """ウィスキーデータの統計情報を取得"""
        try:
            response = self.whiskey_table.scan()
            items = response['Items']
            
            total_count = len(items)
            confidence_counts = {}
            source_counts = {}
            
            for item in items:
                confidence = float(item.get('confidence', 0))
                source = item.get('source', 'unknown')
                
                # 信頼度別カウント
                confidence_range = f"{int(confidence * 10) / 10:.1f}"
                confidence_counts[confidence_range] = confidence_counts.get(confidence_range, 0) + 1
                
                # ソース別カウント
                source_counts[source] = source_counts.get(source, 0) + 1
            
            return {
                'total_count': total_count,
                'confidence_distribution': confidence_counts,
                'source_distribution': source_counts,
                'high_confidence_count': len([item for item in items if float(item.get('confidence', 0)) >= 0.9])
            }
        except Exception as e:
            print(f"Error getting whiskey statistics: {e}")
            return {}

    def delete_all_whiskeys(self) -> bool:
        """全てのウィスキーデータを削除"""
        try:
            deleted_count = 0
            
            # ページネーションを考慮して全てのアイテムを取得
            last_evaluated_key = None
            while True:
                if last_evaluated_key:
                    response = self.whiskey_table.scan(ExclusiveStartKey=last_evaluated_key)
                else:
                    response = self.whiskey_table.scan()
                
                items = response.get('Items', [])
                
                # バッチ削除
                if items:
                    with self.whiskey_table.batch_writer() as batch:
                        for item in items:
                            batch.delete_item(Key={'id': item['id']})
                            deleted_count += 1
                
                # 次のページがあるか確認
                last_evaluated_key = response.get('LastEvaluatedKey')
                if not last_evaluated_key:
                    break
            
            print(f"全ウィスキーデータを削除: {deleted_count}件")
            return True
        except Exception as e:
            print(f"Error deleting all whiskeys: {e}")
            return False

    def _normalize_text(self, text: str) -> str:
        """テキストを検索用に正規化（日本語専用）"""
        if not text:
            return ''
        
        # 小文字に変換、スペースを除去
        normalized = text.lower().replace(' ', '').replace('　', '')
        
        # 完全なカタカナをひらがなに変換（濁音・半濁音・拗音含む）
        katakana_to_hiragana = str.maketrans(
            'アイウエオカキクケコガギグゲゴサシスセソザジズゼゾタチツテトダヂヅデドナニヌネノハヒフヘホバビブベボパピプペポマミムメモヤユヨラリルレロワヲンァィゥェォッャュョ',
            'あいうえおかきくけこがぎぐげごさしすせそざじずぜぞたちつてとだぢづでどなにぬねのはひふへほばびぶべぼぱぴぷぺぽまみむめもやゆよらりるれろわをんぁぃぅぇぉっゃゅょ'
        )
        normalized = normalized.translate(katakana_to_hiragana)
        
        return normalized