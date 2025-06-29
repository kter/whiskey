"""
Whiskeys Search Lambda Function
ウイスキー検索API
"""
import json
import boto3
import os
from decimal import Decimal
from datetime import datetime


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
                    'name': whiskey['name'],
                    'distillery': whiskey['distillery'],
                    'avg_rating': round(avg_rating, 2),  # フロントエンドが期待するフィールド名
                    'average_rating': round(avg_rating, 2),  # 後方互換性のため
                    'review_count': review_count
                })
            except Exception as e:
                print(f"Error processing whiskey {whiskey['id']}: {e}")
                continue
        
        # 平均評価でソート（降順）、同じ評価の場合はレビュー数でソート
        ranking.sort(key=lambda x: (x['average_rating'], x['review_count']), reverse=True)
        return ranking[:20]  # トップ20
        
    except Exception as e:
        print(f"Error in get_whiskey_ranking: {e}")
        return []


def normalize_text(text: str) -> str:
    """テキストを検索用に正規化（DynamoDBServiceと同じロジック）"""
    if not text:
        return ''
    
    # 保存時と同じ正規化ロジック：小文字に変換、スペースを除去のみ
    return text.lower().replace(' ', '').replace('　', '')


def lambda_handler(event, context):
    """
    GET /api/whiskeys/search?q=検索語&distillery=蒸留所 - ウイスキー検索
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
    
    # OPTIONS requests handled by API Gateway
    
    try:
        # パス判定でエンドポイントを分岐
        path = event.get('path', '')
        
        # DynamoDB setup
        dynamodb = boto3.resource('dynamodb')
        whiskeys_table_name = os.environ['WHISKEYS_TABLE']
        reviews_table_name = os.environ.get('REVIEWS_TABLE', '')
        whiskey_search_table_name = os.environ.get('WHISKEY_SEARCH_TABLE', f'WhiskeySearch-{os.environ.get("ENVIRONMENT", "dev")}')
        
        print(f"DEBUG: Environment variables:")
        print(f"DEBUG: WHISKEYS_TABLE = {whiskeys_table_name}")
        print(f"DEBUG: WHISKEY_SEARCH_TABLE = {whiskey_search_table_name}")
        print(f"DEBUG: ENVIRONMENT = {os.environ.get('ENVIRONMENT', 'dev')}")
        
        # ランキングエンドポイント
        if 'ranking' in path:
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
        
        # WhiskeySearchテーブルを使用（多言語対応）
        search_table = dynamodb.Table(whiskey_search_table_name)
        print(f"DEBUG: Using table: '{whiskey_search_table_name}'")
        
        # 名前のみの検索を実行
        whiskeys = []
        
        try:
            if search_query:
                print(f"DEBUG: Search query: '{search_query}'")
                
                # 名前での部分一致検索のみ（シンプル化）
                from boto3.dynamodb.conditions import Attr
                print(f"DEBUG: Starting name-only search for: '{search_query}'")
                
                # 大文字小文字両方で検索
                search_lower = search_query.lower()
                search_upper = search_query.upper()
                search_title = search_query.title()
                
                # まずテーブル内のアイテム総数を確認
                table_scan = search_table.scan(Limit=5)
                print(f"DEBUG: Table scan sample: {len(table_scan.get('Items', []))} items")
                if table_scan.get('Items'):
                    print(f"DEBUG: Sample item keys: {list(table_scan['Items'][0].keys())}")
                    sample_names = [item.get('name_en', '') for item in table_scan['Items']]
                    print(f"DEBUG: Sample names: {sample_names}")
                
                # より詳細なデバッグ: 実際の名前で検索テスト
                print(f"DEBUG: Testing filter conditions for '{search_query}'")
                
                # DynamoDB contains()が不安定なため、手動フィルタリングを使用
                print(f"DEBUG: Starting manual filtering for query: '{search_query}'")
                
                # 検索クエリの各種バリエーション
                query_lower = search_query.lower()
                query_title = search_query.title()
                query_upper = search_query.upper()
                
                # 全データを取得して手動でフィルタリング
                all_items = search_table.scan().get('Items', [])
                print(f"DEBUG: Scanning {len(all_items)} total items")
                
                filtered_items = []
                
                for item in all_items:
                    name_en = item.get('name_en', '')
                    name_ja = item.get('name_ja', '')
                    
                    # 大文字小文字を無視した検索 + 完全一致検索
                    if (search_query in name_en or search_query in name_ja or
                        query_lower in name_en.lower() or query_lower in name_ja.lower() or
                        query_title in name_en or query_title in name_ja or
                        query_upper in name_en.upper() or query_upper in name_ja.upper()):
                        filtered_items.append(item)
                
                results = filtered_items[:20]  # 最大20件
                
                print(f"DEBUG: Final search results: {len(results)}")
                
                # WhiskeySearchのデータを従来形式に変換
                for item in results:
                    whiskey = {
                        'id': item['id'],
                        'name': item.get('name_ja', item.get('name_en', '')),  # 日本語名を優先
                        'distillery': item.get('distillery_ja', item.get('distillery_en', '')),  # 表示用蒸留所名
                        'created_at': item.get('created_at', ''),
                        'updated_at': item.get('updated_at', '')
                    }
                    whiskeys.append(whiskey)
                
            else:
                # 検索クエリがない場合は全件取得
                response = search_table.scan(Limit=50)
                for item in response.get('Items', []):
                    whiskey = {
                        'id': item['id'],
                        'name': item.get('name_ja', item.get('name_en', '')),
                        'distillery': item.get('distillery_ja', item.get('distillery_en', '')),
                        'created_at': item.get('created_at', ''),
                        'updated_at': item.get('updated_at', '')
                    }
                    whiskeys.append(whiskey)
            
        except Exception as e:
            print(f"Search error: {e}")
            # フォールバック: 空の結果を返す
            whiskeys = []
        
        # Sort by relevance (exact matches first, then partial)
        if search_query:
            def sort_key(w):
                name_lower = w['name'].lower()
                query_lower = search_query.lower()
                if name_lower == query_lower:
                    return 0  # Exact match
                elif name_lower.startswith(query_lower):
                    return 1  # Starts with
                else:
                    return 2  # Contains
            
            whiskeys.sort(key=sort_key)
        else:
            # Sort alphabetically if no search query
            whiskeys.sort(key=lambda x: x['name'])
        
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