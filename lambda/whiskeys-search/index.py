"""
Whiskeys Search Lambda Function
ウイスキー検索API (新スキーマ対応)
"""
import json
import boto3
import os
import sys
import time
from decimal import Decimal
from datetime import datetime

# プロジェクトルートをパスに追加
sys.path.append('/opt')
sys.path.append('/opt/python')
sys.path.append('.')
sys.path.append('./python')
sys.path.append('../common')

try:
    from logger import get_logger, extract_correlation_id
except ImportError:
    # フォールバック用の簡易ロガー
    class SimpleLogger:
        def info(self, msg, **kwargs): print(f"INFO: {msg}")
        def warning(self, msg, **kwargs): print(f"WARNING: {msg}")
        def error(self, msg, **kwargs): print(f"ERROR: {msg}")
        def debug(self, msg, **kwargs): print(f"DEBUG: {msg}")
        def log_api_request(self, **kwargs): print(f"API Request: {kwargs}")
        def log_api_response(self, **kwargs): print(f"API Response: {kwargs}")
        def log_database_operation(self, **kwargs): print(f"DB Operation: {kwargs}")
        def log_search_operation(self, **kwargs): print(f"Search Operation: {kwargs}")
        def set_correlation_id(self, id): pass
    
    def get_logger(**kwargs):
        return SimpleLogger()
    
    def extract_correlation_id(event):
        return event.get('requestContext', {}).get('requestId')

try:
    from whiskey_search_service import WhiskeySearchService
    USE_NEW_SERVICE = True
    logger = get_logger()
    logger.info("WhiskeySearchService imported successfully")
except ImportError as e:
    logger = get_logger()
    logger.warning("WhiskeySearchService not available, using legacy implementation", error=str(e))
    USE_NEW_SERVICE = False


def decimal_default(obj):
    """DynamoDB Decimal型をJSONシリアライズ可能に変換"""
    if isinstance(obj, Decimal):
        return float(obj)
    elif isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError


def get_whiskey_ranking(dynamodb, whiskeys_table_name, reviews_table_name, page=1, limit=20):
    """シンプルで高効率なウイスキーランキング生成（GSI使用）"""
    try:
        from boto3.dynamodb.conditions import Key
        
        whiskeys_table = dynamodb.Table(whiskeys_table_name)
        reviews_table = dynamodb.Table(reviews_table_name)
        logger = get_logger()
        
        # Step 1: レビューデータをGSIで効率的に取得・集計
        logger.debug("Aggregating review statistics using GSI")
        
        review_stats = {}
        
        # 全レビューを一度だけ取得
        all_reviews_response = reviews_table.scan()
        all_reviews = all_reviews_response['Items']
        
        # whiskey_id別に集計
        for review in all_reviews:
            whiskey_id = review.get('whiskey_id')
            if whiskey_id:
                if whiskey_id not in review_stats:
                    review_stats[whiskey_id] = []
                review_stats[whiskey_id].append(float(review.get('rating', 0)))
        
        # 統計計算
        for whiskey_id in review_stats:
            ratings = review_stats[whiskey_id]
            review_stats[whiskey_id] = {
                'avg_rating': sum(ratings) / len(ratings),
                'review_count': len(ratings)
            }
        
        logger.debug(f"Aggregated reviews for {len(review_stats)} whiskeys")
        
        # Step 2: ウイスキー基本情報取得（ページネーション用に必要分のみ）
        if page == 1:
            # 最初のページ：候補を多めに取得
            whiskeys_response = whiskeys_table.scan(Limit=min(500, limit * 10))
        else:
            # 全件必要（ソート順序保証のため）
            whiskeys_response = whiskeys_table.scan()
        
        whiskeys = whiskeys_response['Items']
        logger.debug(f"Retrieved {len(whiskeys)} whiskeys")
        
        # Step 3: ランキング作成
        ranking = []
        for whiskey in whiskeys:
            whiskey_id = whiskey.get('id')
            stats = review_stats.get(whiskey_id, {'avg_rating': 0, 'review_count': 0})
            
            ranking.append({
                'id': whiskey_id,
                'name': whiskey.get('name', whiskey.get('name_en', whiskey.get('name_ja', ''))),
                'distillery': whiskey.get('distillery', whiskey.get('distillery_en', whiskey.get('distillery_ja', ''))),
                'region': whiskey.get('region', ''),
                'avg_rating': stats['avg_rating'],
                'review_count': stats['review_count']
            })
        
        # Step 4: ソート（レビューありを優先）
        ranking.sort(key=lambda x: (
            x['review_count'] > 0,  # レビューありを優先
            x['avg_rating'],        # 平均評価
            x['review_count']       # レビュー数
        ), reverse=True)
        
        # Step 5: ページネーション
        total_items = len(ranking)
        total_pages = (total_items + limit - 1) // limit if total_items > 0 else 1
        start_index = (page - 1) * limit
        end_index = start_index + limit
        
        pagination = {
            'page': page,
            'limit': limit,
            'total_items': total_items,
            'total_pages': total_pages,
            'has_next': page < total_pages,
            'has_prev': page > 1
        }
        
        page_items = ranking[start_index:end_index]
        
        logger.debug(f"Returning page {page} with {len(page_items)} items")
        
        return {
            'rankings': page_items,
            'pagination': pagination
        }
        
    except Exception as e:
        logger = get_logger()
        logger.error("Error generating whiskey ranking", error=str(e))
        return {
            'rankings': [],
            'pagination': {
                'page': page,
                'limit': limit,
                'total_items': 0,
                'total_pages': 0,
                'has_next': False,
                'has_prev': False
            }
        }


def get_cors_headers(event):
    """CORS対応のレスポンスヘッダーを生成"""
    origin = event.get('headers', {}).get('origin') or event.get('headers', {}).get('Origin')
    environment = os.environ.get('ENVIRONMENT', 'dev')
    
    if environment == 'prd':
        allowed_origins = ['https://whiskeybar.site', 'https://www.whiskeybar.site']
        default_origin = 'https://whiskeybar.site'
    else:
        allowed_origins = ['https://dev.whiskeybar.site', 'https://www.dev.whiskeybar.site', 'http://localhost:3000']
        default_origin = 'https://dev.whiskeybar.site'
    
    return {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': origin if origin in allowed_origins else default_origin,
        'Access-Control-Allow-Headers': 'Content-Type, Authorization',
        'Access-Control-Allow-Methods': 'GET, OPTIONS',
    }


def create_response(status_code, body, headers, start_time=None, logger=None):
    """統一されたAPIレスポンスを生成"""
    response = {
        'statusCode': status_code,
        'headers': headers,
        'body': json.dumps(body, default=decimal_default) if isinstance(body, (dict, list)) else body
    }
    
    if start_time and logger:
        duration_ms = (time.time() - start_time) * 1000
        logger.log_api_response(
            status_code=status_code,
            duration_ms=duration_ms
        )
    
    return response


def transform_whiskey_item(item, schema_type='new'):
    """DynamoDBアイテムを統一フォーマットに変換"""
    if schema_type == 'new' and 'name' in item:
        # 旧スキーマ（単一言語）
        return {
            'id': item.get('id'),
            'name': item.get('name', ''),
            'name_en': item.get('name', ''),
            'name_ja': '',
            'distillery': item.get('distillery', ''),
            'region': item.get('region', ''),
            'type': item.get('type', ''),
            'confidence': float(item.get('confidence', 0)),
            'source': item.get('source', ''),
            'created_at': item.get('created_at'),
            'updated_at': item.get('updated_at')
        }
    elif 'name_ja' in item or 'name_en' in item:
        # 新しいバイリンガルスキーマ
        return {
            'id': item.get('id'),
            'name': item.get('name_ja') or item.get('name_en', ''),
            'name_en': item.get('name_en', ''),
            'name_ja': item.get('name_ja', ''),
            'distillery': item.get('distillery_ja') or item.get('distillery_en', ''),
            'region': item.get('region', ''),
            'type': item.get('type', ''),
            'confidence': float(item.get('confidence', 0)),
            'source': item.get('source', ''),
            'created_at': item.get('created_at'),
            'updated_at': item.get('updated_at')
        }
    else:
        # フォールバック
        return {
            'id': item.get('id'),
            'name': '',
            'name_en': '',
            'name_ja': '',
            'distillery': '',
            'region': item.get('region', ''),
            'type': item.get('type', ''),
            'confidence': float(item.get('confidence', 0)),
            'source': item.get('source', ''),
            'created_at': item.get('created_at'),
            'updated_at': item.get('updated_at')
        }


def handle_ranking_endpoint(query_params, logger):
    """ランキングエンドポイントの処理"""
    try:
        dynamodb = boto3.resource('dynamodb')
        whiskeys_table_name = os.environ['WHISKEYS_TABLE']
        reviews_table_name = os.environ.get('REVIEWS_TABLE', '')
        
        # ページネーションパラメータの取得とバリデーション
        try:
            page = int(query_params.get('page', 1))
            limit = int(query_params.get('limit', 20))
        except ValueError:
            page = 1
            limit = 20
        
        # パラメータの範囲チェック
        page = max(1, page)  # 最小1
        limit = max(1, min(100, limit))  # 1-100の範囲
        
        logger.debug("Ranking request", page=page, limit=limit)
        
        ranking_data = get_whiskey_ranking(dynamodb, whiskeys_table_name, reviews_table_name, page, limit)
        
        # 後方互換性のため、ページネーション情報がない場合は旧形式で返却
        if query_params.get('page') is None and query_params.get('limit') is None:
            # 旧形式（配列のみ）で返却
            return ranking_data['rankings']
        else:
            # 新形式（ページネーション情報付き）で返却
            return ranking_data
            
    except Exception as e:
        logger.error("Error in ranking endpoint", error=str(e))
        raise


def search_with_new_service(search_query, logger):
    """新しいWhiskeySearchServiceを使用した検索"""
    logger.debug("Using WhiskeySearchService")
    service = WhiskeySearchService()
    raw_results = service.search_whiskeys(search_query, limit=50)
    logger.debug("Search completed via new service", result_count=len(raw_results))
    
    whiskeys = []
    for item in raw_results:
        whiskey = transform_whiskey_item(item, 'new')
        whiskeys.append(whiskey)
    
    return whiskeys


def search_with_legacy_service(search_query, logger):
    """レガシーDynamoDB検索の実装"""
    logger.debug("Using legacy search implementation")
    
    dynamodb = boto3.resource('dynamodb')
    whiskey_search_table_name = os.environ.get('WHISKEY_SEARCH_TABLE', f'WhiskeySearch-{os.environ.get("ENVIRONMENT", "dev")}')
    search_table = dynamodb.Table(whiskey_search_table_name)
    
    if search_query:
        return _search_with_query(search_table, search_query, logger)
    else:
        return _search_empty_query(search_table, logger)


def _search_with_query(search_table, search_query, logger):
    """クエリありの検索処理"""
    from boto3.dynamodb.conditions import Attr
    
    # テーブルスキーマを確認
    table_scan = search_table.scan(Limit=1)
    if not table_scan.get('Items'):
        logger.info("No items found in search table")
        return []
    
    sample_item = table_scan['Items'][0]
    logger.debug("Table schema detected", keys=list(sample_item.keys()))
    
    # 新スキーマ（name, distillery）か旧スキーマ（name_en, name_ja）かを判定
    if 'name' in sample_item:
        logger.debug("Using new schema (name, distillery)")
        response = search_table.scan(
            FilterExpression=Attr('name').contains(search_query) | Attr('distillery').contains(search_query)
        )
        schema_type = 'new'
    else:
        logger.debug("Using legacy schema (name_en, name_ja)")
        response = search_table.scan(
            FilterExpression=Attr('name_en').contains(search_query) | Attr('name_ja').contains(search_query)
        )
        schema_type = 'legacy'
    
    raw_items = response.get('Items', [])
    logger.debug("Search completed via legacy implementation", result_count=len(raw_items))
    
    whiskeys = []
    for item in raw_items:
        whiskey = transform_whiskey_item(item, schema_type)
        whiskeys.append(whiskey)
    
    return whiskeys


def _search_empty_query(search_table, logger):
    """空クエリの場合の検索処理"""
    response = search_table.scan(Limit=10)
    raw_items = response.get('Items', [])
    
    whiskeys = []
    for item in raw_items:
        # スキーマタイプを動的に判定
        schema_type = 'new' if 'name' in item else 'legacy'
        whiskey = transform_whiskey_item(item, schema_type)
        whiskeys.append(whiskey)
    
    return whiskeys


def handle_search_endpoint(search_query, logger):
    """検索エンドポイントの処理"""
    logger.debug("Search query received", query=search_query)
    
    # 新しいサービスまたはレガシーサービスを使用
    if USE_NEW_SERVICE:
        whiskeys = search_with_new_service(search_query, logger)
    else:
        whiskeys = search_with_legacy_service(search_query, logger)
    
    # アルファベット順にソート
    if whiskeys:
        whiskeys.sort(key=lambda x: x.get('name', ''))
    
    return whiskeys


def lambda_handler(event, context):
    """
    GET /api/whiskeys/search?q=検索語 - ウイスキー検索
    GET /api/whiskeys/suggest?q=検索語 - ウイスキーサジェスト
    GET /api/whiskeys/ranking/ - ウイスキーランキング
    """
    start_time = time.time()
    
    # ロガー初期化
    correlation_id = extract_correlation_id(event)
    logger = get_logger(
        function_name='whiskeys-search',
        correlation_id=correlation_id
    )
    
    # APIリクエストログ
    method = event.get('httpMethod', 'UNKNOWN')
    path = event.get('path', 'UNKNOWN')
    query_params = event.get('queryStringParameters')
    
    logger.log_api_request(
        method=method,
        path=path,
        query_params=query_params
    )
    
    # CORS対応ヘッダー取得
    headers = get_cors_headers(event)
    
    try:
        # パス判定でエンドポイントを分岐
        path = event.get('path', '')
        
        # ランキングエンドポイント
        if '/ranking' in path:
            query_params = event.get('queryStringParameters') or {}
            ranking = handle_ranking_endpoint(query_params, logger)
            return create_response(200, ranking, headers, start_time, logger)
        
        # 検索/サジェストエンドポイント
        query_params = event.get('queryStringParameters') or {}
        search_query = query_params.get('q', '').strip()
        
        # 検索実行
        whiskeys = handle_search_endpoint(search_query, logger)
        
        # 検索ログ
        duration_ms = (time.time() - start_time) * 1000
        logger.log_search_operation(
            query=search_query,
            result_count=len(whiskeys),
            duration_ms=duration_ms,
            search_type="whiskey_search"
        )
        
        # レスポンスボディ
        response_body = {
            'whiskeys': whiskeys,
            'count': len(whiskeys),
            'query': search_query,
            'distillery': ""  # 蒸留所フィルターは削除済み
        }
        
        return create_response(200, response_body, headers, start_time, logger)
        
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        logger.error("Unhandled error in lambda_handler", 
                    error=str(e), 
                    duration_ms=duration_ms)
        
        error_body = {
            'error': 'Internal server error',
            'message': str(e)
        }
        
        return create_response(500, error_body, headers, start_time, logger)