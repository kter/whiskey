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
        
        table = dynamodb.Table(whiskeys_table_name)
        
        # Scan all whiskeys (for small datasets)
        response = table.scan()
        
        whiskeys = []
        for item in response['Items']:
            whiskey = {
                'id': item['id'],
                'name': item['name'],
                'distillery': item['distillery'],
                'created_at': item.get('created_at', ''),
                'updated_at': item.get('updated_at', '')
            }
            
            # Apply filters
            matches = True
            
            if search_query:
                # Name search (case insensitive, partial match)
                if search_query.lower() not in whiskey['name'].lower():
                    matches = False
            
            if distillery_filter and matches:
                # Distillery filter (case insensitive, partial match)
                if distillery_filter.lower() not in whiskey['distillery'].lower():
                    matches = False
            
            if matches:
                whiskeys.append(whiskey)
        
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