"""
Whiskeys Search Lambda Function
ウイスキー検索API (新スキーマ対応)
"""
import json
import boto3
import os
import sys
from decimal import Decimal
from datetime import datetime

# プロジェクトルートをパスに追加
sys.path.append('/opt')
sys.path.append('/opt/python')
sys.path.append('.')
sys.path.append('./python')

try:
    from whiskey_search_service import WhiskeySearchService
    USE_NEW_SERVICE = True
    print("WhiskeySearchService imported successfully")
except ImportError as e:
    print(f"WhiskeySearchService not available: {e}, using legacy implementation")
    USE_NEW_SERVICE = False


def decimal_default(obj):
    """DynamoDB Decimal型をJSONシリアライズ可能に変換"""
    if isinstance(obj, Decimal):
        return float(obj)
    elif isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError


def get_whiskey_ranking(dynamodb, whiskeys_table_name, reviews_table_name):
    """簡単なウイスキーランキングを生成（後方互換性のため）"""
    try:
        whiskeys_table = dynamodb.Table(whiskeys_table_name)
        reviews_table = dynamodb.Table(reviews_table_name)
        
        # 全ウイスキーを取得
        whiskeys_response = whiskeys_table.scan()
        whiskeys = whiskeys_response['Items']
        
        # 各ウイスキーの平均評価を計算
        ranking = []
        for whiskey in whiskeys:
            try:
                # このウイスキーのレビューを取得
                reviews_response = reviews_table.scan(
                    FilterExpression='whiskey_id = :whiskey_id',
                    ExpressionAttributeValues={':whiskey_id': whiskey['id']}
                )
                
                reviews = reviews_response['Items']
                if reviews:
                    avg_rating = sum(float(r['rating']) for r in reviews) / len(reviews)
                    review_count = len(reviews)
                else:
                    avg_rating = 0
                    review_count = 0
                
                ranking.append({
                    'id': whiskey['id'],
                    'name': whiskey.get('name', ''),
                    'distillery': whiskey.get('distillery', ''),
                    'region': whiskey.get('region', ''),
                    'average_rating': avg_rating,
                    'review_count': review_count
                })
            except Exception as e:
                print(f"Error processing whiskey {whiskey.get('id', 'unknown')}: {e}")
                continue
        
        # 平均評価とレビュー数でソート
        ranking.sort(key=lambda x: (x['average_rating'], x['review_count']), reverse=True)
        return ranking[:20]  # 上位20件
        
    except Exception as e:
        print(f"Error generating ranking: {e}")
        return []


def lambda_handler(event, context):
    """
    GET /api/whiskeys/search?q=検索語 - ウイスキー検索
    GET /api/whiskeys/suggest?q=検索語 - ウイスキーサジェスト
    GET /api/whiskeys/ranking/ - ウイスキーランキング
    """
    
    # Response headers with CORS support
    origin = event.get('headers', {}).get('origin') or event.get('headers', {}).get('Origin')
    allowed_origins = ['https://dev.whiskeybar.site', 'https://whiskeybar.site', 'http://localhost:3000']
    
    headers = {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': origin if origin in allowed_origins else 'https://dev.whiskeybar.site',
        'Access-Control-Allow-Headers': 'Content-Type, Authorization',
        'Access-Control-Allow-Methods': 'GET, OPTIONS',
    }
    
    try:
        # パス判定でエンドポイントを分岐
        path = event.get('path', '')
        
        # ランキングエンドポイント
        if '/ranking' in path:
            dynamodb = boto3.resource('dynamodb')
            whiskeys_table_name = os.environ['WHISKEYS_TABLE']
            reviews_table_name = os.environ.get('REVIEWS_TABLE', '')
            
            ranking = get_whiskey_ranking(dynamodb, whiskeys_table_name, reviews_table_name)
            
            return {
                'statusCode': 200,
                'headers': headers,
                'body': json.dumps(ranking, default=decimal_default)
            }
        
        # 検索/サジェストエンドポイント
        query_params = event.get('queryStringParameters') or {}
        search_query = query_params.get('q', '').strip()
        
        print(f"DEBUG: Search query received: '{search_query}'")
        
        # 新しいサービスを使用
        whiskeys = []
        
        if USE_NEW_SERVICE:
            print("DEBUG: Using WhiskeySearchService")
            service = WhiskeySearchService()
            raw_results = service.search_whiskeys(search_query, limit=50)
            print(f"DEBUG: Found {len(raw_results)} whiskeys via new service")
            
            # 従来形式に変換
            for item in raw_results:
                whiskey = {
                    'id': item.get('id'),
                    'name': item.get('name', ''),
                    'name_en': item.get('name', ''),  # 新スキーマでは name を name_en として使用
                    'name_ja': '',  # 新スキーマでは日本語名は分離されていない
                    'distillery': item.get('distillery', ''),
                    'region': item.get('region', ''),
                    'type': item.get('type', ''),
                    'confidence': float(item.get('confidence', 0)),
                    'source': item.get('source', ''),
                    'created_at': item.get('created_at'),
                    'updated_at': item.get('updated_at')
                }
                whiskeys.append(whiskey)
        else:
            print("DEBUG: Using legacy search")
            # フォールバック実装
            dynamodb = boto3.resource('dynamodb')
            whiskey_search_table_name = os.environ.get('WHISKEY_SEARCH_TABLE', f'WhiskeySearch-{os.environ.get("ENVIRONMENT", "dev")}')
            search_table = dynamodb.Table(whiskey_search_table_name)
            
            if search_query:
                from boto3.dynamodb.conditions import Attr
                
                # テーブルスキーマを確認
                table_scan = search_table.scan(Limit=1)
                if table_scan.get('Items'):
                    sample_item = table_scan['Items'][0]
                    print(f"DEBUG: Sample item keys: {list(sample_item.keys())}")
                    
                    # 新スキーマ（name, distillery）か旧スキーマ（name_en, name_ja）かを判定
                    if 'name' in sample_item:
                        print("DEBUG: Using new schema (name, distillery)")
                        response = search_table.scan(
                            FilterExpression=Attr('name').contains(search_query) | Attr('distillery').contains(search_query)
                        )
                    else:
                        print("DEBUG: Using legacy schema (name_en, name_ja)")
                        response = search_table.scan(
                            FilterExpression=Attr('name_en').contains(search_query) | Attr('name_ja').contains(search_query)
                        )
                    
                    raw_items = response.get('Items', [])
                    print(f"DEBUG: Found {len(raw_items)} whiskeys via legacy search")
                    
                    # 統一形式に変換
                    for item in raw_items:
                        if 'name' in item:  # 新スキーマ
                            whiskey = {
                                'id': item.get('id'),
                                'name': item.get('name', ''),
                                'name_en': item.get('name', ''),
                                'name_ja': '',
                                'distillery': item.get('distillery', ''),
                                'region': item.get('region', ''),
                                'type': item.get('type', ''),
                                'confidence': float(item.get('confidence', 0)),
                                'created_at': item.get('created_at'),
                                'updated_at': item.get('updated_at')
                            }
                        else:  # 旧スキーマ
                            whiskey = {
                                'id': item.get('id'),
                                'name': item.get('name_en') or item.get('name_ja'),
                                'name_en': item.get('name_en', ''),
                                'name_ja': item.get('name_ja', ''),
                                'distillery': item.get('distillery_en') or item.get('distillery_ja'),
                                'region': item.get('region', ''),
                                'type': item.get('type', ''),
                                'created_at': item.get('created_at'),
                                'updated_at': item.get('updated_at')
                            }
                        whiskeys.append(whiskey)
                else:
                    print("DEBUG: No items in table")
            else:
                # 空クエリの場合は最初の数件を返す
                response = search_table.scan(Limit=10)
                raw_items = response.get('Items', [])
                
                for item in raw_items:
                    if 'name' in item:  # 新スキーマ
                        whiskey = {
                            'id': item.get('id'),
                            'name': item.get('name', ''),
                            'name_en': item.get('name', ''),
                            'name_ja': '',
                            'distillery': item.get('distillery', ''),
                            'region': item.get('region', ''),
                            'type': item.get('type', ''),
                            'confidence': float(item.get('confidence', 0)),
                            'created_at': item.get('created_at'),
                            'updated_at': item.get('updated_at')
                        }
                    else:  # 旧スキーマ
                        whiskey = {
                            'id': item.get('id'),
                            'name': item.get('name_en') or item.get('name_ja'),
                            'name_en': item.get('name_en', ''),
                            'name_ja': item.get('name_ja', ''),
                            'distillery': item.get('distillery_en') or item.get('distillery_ja'),
                            'region': item.get('region', ''),
                            'type': item.get('type', ''),
                            'created_at': item.get('created_at'),
                            'updated_at': item.get('updated_at')
                        }
                    whiskeys.append(whiskey)
        
        # Sort alphabetically
        if whiskeys:
            whiskeys.sort(key=lambda x: x.get('name', ''))
        
        return {
            'statusCode': 200,
            'headers': headers,
            'body': json.dumps({
                'whiskeys': whiskeys,
                'count': len(whiskeys),
                'query': search_query,
                'distillery': ""  # 蒸留所フィルターは削除済み
            }, default=decimal_default)
        }
        
    except Exception as e:
        print(f"Error: {str(e)}")
        return {
            'statusCode': 500,
            'headers': headers,
            'body': json.dumps({
                'error': 'Internal server error',
                'message': str(e)
            })
        }