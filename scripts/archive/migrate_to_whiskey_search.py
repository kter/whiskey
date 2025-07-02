#!/usr/bin/env python3
"""
Whiskeys-devテーブルからWhiskeySearch-devテーブルにデータをマイグレート
新しいスキーマ（name, distillery）に対応
"""

import boto3
import os
import sys
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Dict, List

# プロジェクトルートをパスに追加
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'backend', 'api'))

try:
    from whiskey_search_service import WhiskeySearchService
except ImportError:
    print("Warning: WhiskeySearchService not available, using direct DynamoDB operations")
    WhiskeySearchService = None


def normalize_text(text: str) -> str:
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


def migrate_whiskey_data():
    """ウイスキーデータをマイグレート"""
    
    # DynamoDB接続
    dynamodb = boto3.resource('dynamodb', region_name='ap-northeast-1')
    
    # テーブル参照
    source_table = dynamodb.Table('Whiskeys-dev')
    target_table = dynamodb.Table('WhiskeySearch-dev')
    
    print("Whiskeys-dev → WhiskeySearch-dev データマイグレーション開始")
    
    try:
        # ソーステーブルから全データを取得
        response = source_table.scan()
        items = response['Items']
        
        # ページネーション対応
        while 'LastEvaluatedKey' in response:
            response = source_table.scan(ExclusiveStartKey=response['LastEvaluatedKey'])
            items.extend(response['Items'])
        
        print(f"ソースデータ取得完了: {len(items)}件")
        
        # データ変換・挿入
        migrated_count = 0
        
        with target_table.batch_writer() as batch:
            for item in items:
                try:
                    # 必須フィールドの確認
                    if 'id' not in item or 'name' not in item:
                        print(f"必須フィールドなし、スキップ: {item}")
                        continue
                    
                    # 新スキーマに変換
                    whiskey_data = {
                        'id': item['id'],
                        'name': item['name'],
                        'distillery': item.get('distillery', 'Unknown'),
                        'region': item.get('region', ''),
                        'type': item.get('type', ''),
                        'confidence': float(item.get('confidence', 1.0)),
                        'source': item.get('source', 'migrated'),
                        'created_at': item.get('created_at', datetime.utcnow().isoformat()),
                        'updated_at': datetime.utcnow().isoformat(),
                        # 正規化フィールドを追加
                        'normalized_name': normalize_text(item['name']),
                        'normalized_distillery': normalize_text(item.get('distillery', 'Unknown'))
                    }
                    
                    # DynamoDB用にDecimalを変換
                    for key, value in whiskey_data.items():
                        if isinstance(value, float):
                            whiskey_data[key] = Decimal(str(value))
                    
                    batch.put_item(Item=whiskey_data)
                    migrated_count += 1
                    
                    if migrated_count % 10 == 0:
                        print(f"マイグレート進捗: {migrated_count}件")
                
                except Exception as e:
                    print(f"アイテム処理エラー: {item.get('id', 'unknown')}: {e}")
                    continue
        
        print(f"マイグレーション完了: {migrated_count}/{len(items)}件")
        
        # 検証
        print("\nマイグレーション結果検証:")
        target_response = target_table.scan(Limit=1)
        if target_response.get('Items'):
            sample_item = target_response['Items'][0]
            print(f"サンプルアイテム: {sample_item}")
        
        # カウント確認
        count_response = target_table.scan(Select='COUNT')
        print(f"ターゲットテーブル件数: {count_response['Count']}")
        
        return True
        
    except Exception as e:
        print(f"マイグレーションエラー: {e}")
        return False


def test_search_functionality():
    """検索機能をテスト"""
    print("\n検索機能テスト開始")
    
    if WhiskeySearchService:
        try:
            service = WhiskeySearchService()
            
            # テストクエリ
            test_queries = ['響', 'サントリー', '17年']
            
            for query in test_queries:
                results = service.search_whiskeys(query, limit=5)
                print(f"クエリ '{query}': {len(results)}件")
                if results:
                    for result in results[:2]:
                        print(f"  - {result.get('name')} ({result.get('distillery')})")
        
        except Exception as e:
            print(f"検索テストエラー: {e}")
    else:
        print("WhiskeySearchService利用不可、スキップ")


if __name__ == '__main__':
    print("=" * 60)
    print("Whiskey データマイグレーション")
    print("=" * 60)
    
    # マイグレーション実行
    success = migrate_whiskey_data()
    
    if success:
        print("\nマイグレーション成功!")
        
        # 検索機能テスト
        test_search_functionality()
    else:
        print("\nマイグレーション失敗")
        sys.exit(1)