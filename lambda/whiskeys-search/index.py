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
    
    # 小文字に変換、スペースを除去
    normalized = text.lower().replace(' ', '').replace('　', '')
    
    # カタカナをひらがなに変換（簡易版）
    katakana_to_hiragana = str.maketrans(
        'アイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホマミムメモヤユヨラリルレロワヲン',
        'あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろわをん'
    )
    normalized = normalized.translate(katakana_to_hiragana)
    
    return normalized


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
        distillery_filter = query_params.get('distillery', '').strip()
        
        # WhiskeySearchテーブルを使用（多言語対応）
        search_table = dynamodb.Table(whiskey_search_table_name)
        
        # 多言語検索を実行
        whiskeys = []
        
        try:
            if search_query:
                print(f"DEBUG: Search query: '{search_query}'")
                # 複数の検索戦略を試す
                all_results = []
                
                # 1. 日本語名での完全一致検索
                try:
                    normalized_query = normalize_text(search_query)
                    print(f"DEBUG: Normalized query (JA): '{normalized_query}'")
                    if normalized_query:
                        response = search_table.query(
                            IndexName='NameJaIndex',
                            KeyConditionExpression='normalized_name_ja = :query',
                            ExpressionAttributeValues={':query': normalized_query}
                        )
                        ja_results = response.get('Items', [])
                        print(f"DEBUG: Japanese name search results: {len(ja_results)}")
                        all_results.extend(ja_results)
                except Exception as e:
                    print(f"Japanese name search error: {e}")
                
                # 2. 英語名での完全一致検索
                try:
                    normalized_query_en = normalize_text(search_query)
                    print(f"DEBUG: Normalized query (EN): '{normalized_query_en}'")
                    if normalized_query_en:
                        response = search_table.query(
                            IndexName='NameEnIndex',
                            KeyConditionExpression='normalized_name_en = :query',
                            ExpressionAttributeValues={':query': normalized_query_en}
                        )
                        en_results = response.get('Items', [])
                        print(f"DEBUG: English name search results: {len(en_results)}")
                        all_results.extend(en_results)
                except Exception as e:
                    print(f"English name search error: {e}")
                
                # 3. 部分一致検索（日本語・英語両方、大文字小文字対応）
                try:
                    from boto3.dynamodb.conditions import Attr
                    print(f"DEBUG: Starting partial match search for: '{search_query}'")
                    
                    # 大文字小文字両方で検索
                    search_lower = search_query.lower()
                    search_upper = search_query.upper()
                    search_title = search_query.title()
                    
                    response = search_table.scan(
                        FilterExpression=(
                            # 元の検索語
                            Attr('name_ja').contains(search_query) |
                            Attr('name_en').contains(search_query) |
                            Attr('distillery_ja').contains(search_query) |
                            Attr('distillery_en').contains(search_query) |
                            # 小文字版
                            Attr('name_ja').contains(search_lower) |
                            Attr('name_en').contains(search_lower) |
                            Attr('distillery_ja').contains(search_lower) |
                            Attr('distillery_en').contains(search_lower) |
                            # タイトルケース版
                            Attr('name_ja').contains(search_title) |
                            Attr('name_en').contains(search_title) |
                            Attr('distillery_ja').contains(search_title) |
                            Attr('distillery_en').contains(search_title)
                        ),
                        Limit=20
                    )
                    partial_results = response.get('Items', [])
                    print(f"DEBUG: Partial match search results: {len(partial_results)}")
                    all_results.extend(partial_results)
                except Exception as e:
                    print(f"Partial match search error: {e}")
                
                # 重複除去
                seen_ids = set()
                unique_results = []
                for item in all_results:
                    if item['id'] not in seen_ids:
                        seen_ids.add(item['id'])
                        unique_results.append(item)
                
                # WhiskeySearchのデータを従来形式に変換
                for item in unique_results:
                    whiskey = {
                        'id': item['id'],
                        'name': item.get('name_ja', item.get('name_en', '')),  # 日本語名を優先
                        'distillery': item.get('distillery_ja', item.get('distillery_en', '')),  # 日本語蒸留所名を優先
                        'created_at': item.get('created_at', ''),
                        'updated_at': item.get('updated_at', '')
                    }
                    
                    # 蒸留所フィルター適用
                    if distillery_filter:
                        distillery_matches = (
                            distillery_filter.lower() in whiskey['distillery'].lower() or
                            distillery_filter.lower() in item.get('distillery_en', '').lower()
                        )
                        if not distillery_matches:
                            continue
                    
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
                'distillery': distillery_filter
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