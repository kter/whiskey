"""
Reviews Lambda Function
統合レビューCRUD API
"""
import json
import boto3
import os
import uuid
import sys
import time
from decimal import Decimal
from datetime import datetime

# プロジェクトルートをパスに追加
sys.path.append('/opt')
sys.path.append('/opt/python')
sys.path.append('.')
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
        def log_jwt_operation(self, **kwargs): print(f"JWT Operation: {kwargs}")
        def set_correlation_id(self, id): pass
    
    def get_logger(**kwargs):
        return SimpleLogger()
    
    def extract_correlation_id(event):
        return event.get('requestContext', {}).get('requestId')


def decimal_default(obj):
    """DynamoDB Decimal型をJSONシリアライズ可能に変換"""
    if isinstance(obj, Decimal):
        return float(obj)
    elif isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError


def get_user_id_from_token(event):
    """
    Cognito JWT トークンからuser_idを安全に取得
    """
    try:
        from jwt_utils import extract_user_id_from_token
        return extract_user_id_from_token(event)
    except ImportError:
        # フォールバック: 古い実装（テスト環境用）
        logger = get_logger()
        logger.warning("Using legacy JWT implementation - should only be used in tests")
        # まずAPI Gateway Cognito Authorizerからの情報を確認
        claims = event.get('requestContext', {}).get('authorizer', {}).get('claims', {})
        user_id = claims.get('sub')
        
        if user_id:
            return user_id
        
        # 手動でJWTトークンを解析する場合（危険 - 本番環境では使用禁止）
        auth_header = event.get('headers', {}).get('Authorization') or event.get('headers', {}).get('authorization')
        if auth_header and auth_header.startswith('Bearer '):
            token = auth_header.replace('Bearer ', '')
            # 簡単なJWTデコード（本来はVerifyすべき）
            try:
                import base64
                # JWT payload部分を取得
                parts = token.split('.')
                if len(parts) >= 2:
                    payload_part = parts[1]
                    # Base64パディング調整
                    padded = payload_part + '=' * (4 - len(payload_part) % 4)
                    decoded = base64.b64decode(padded)
                    import json
                    payload = json.loads(decoded)
                    return payload.get('sub')
            except Exception as e:
                logger = get_logger()
                logger.error("JWT decode error in legacy implementation", error=str(e))
        
        return None


def get_public_reviews(dynamodb, reviews_table_name, whiskeys_table_name):
    """パブリックレビュー一覧を取得"""
    reviews_table = dynamodb.Table(reviews_table_name)
    whiskeys_table = dynamodb.Table(whiskeys_table_name)
    
    # 全レビューをスキャン（実際のプロダクションではページネーション必要）
    response = reviews_table.scan()
    reviews = response['Items']
    
    # ウイスキー情報を付加
    for review in reviews:
        whiskey_response = whiskeys_table.get_item(Key={'id': review['whiskey_id']})
        if 'Item' in whiskey_response:
            whiskey = whiskey_response['Item']
            review['whiskey_name'] = whiskey['name']
            review['whiskey_distillery'] = whiskey['distillery']
    
    # 日付でソート（新しい順）
    reviews.sort(key=lambda x: x.get('date', ''), reverse=True)
    
    return reviews


def get_user_reviews(dynamodb, reviews_table_name, whiskeys_table_name, user_id):
    """ユーザーのレビュー一覧を取得"""
    reviews_table = dynamodb.Table(reviews_table_name)
    whiskeys_table = dynamodb.Table(whiskeys_table_name)
    
    # GSI を使用してuser_idでクエリ
    response = reviews_table.query(
        IndexName='UserDateIndex',
        KeyConditionExpression='user_id = :user_id',
        ExpressionAttributeValues={':user_id': user_id},
        ScanIndexForward=False  # 新しい順
    )
    
    reviews = response['Items']
    
    # ウイスキー情報を付加
    for review in reviews:
        whiskey_response = whiskeys_table.get_item(Key={'id': review['whiskey_id']})
        if 'Item' in whiskey_response:
            whiskey = whiskey_response['Item']
            review['whiskey_name'] = whiskey['name']
            review['whiskey_distillery'] = whiskey['distillery']
    
    return reviews


def create_review(dynamodb, reviews_table_name, user_id, data):
    """レビューを作成"""
    reviews_table = dynamodb.Table(reviews_table_name)
    
    review_id = str(uuid.uuid4())
    now = datetime.now().isoformat()
    
    review = {
        'id': review_id,
        'whiskey_id': data['whiskey_id'],
        'user_id': user_id,
        'rating': Decimal(str(data['rating'])),
        'notes': data['notes'],
        'serving_style': data['serving_style'],
        'date': data['date'],
        'image_url': data.get('image_url', ''),
        'created_at': now,
        'updated_at': now
    }
    
    reviews_table.put_item(Item=review)
    
    # Decimal を float に変換して返却
    review['rating'] = float(review['rating'])
    return review


def update_review(dynamodb, reviews_table_name, user_id, review_id, data):
    """レビューを更新"""
    reviews_table = dynamodb.Table(reviews_table_name)
    
    # 既存レビューを取得
    response = reviews_table.get_item(Key={'id': review_id})
    if 'Item' not in response:
        return None
    
    existing_review = response['Item']
    
    # 所有者確認
    if existing_review['user_id'] != user_id:
        raise ValueError("Unauthorized: Cannot update other user's review")
    
    # 更新
    now = datetime.now().isoformat()
    update_expression = "SET rating = :rating, notes = :notes, serving_style = :serving_style, #date = :date, updated_at = :updated_at"
    expression_attribute_values = {
        ':rating': Decimal(str(data['rating'])),
        ':notes': data['notes'],
        ':serving_style': data['serving_style'],
        ':date': data['date'],
        ':updated_at': now
    }
    
    expression_attribute_names = {
        '#date': 'date'  # 'date' は予約語
    }
    
    if 'image_url' in data:
        update_expression += ", image_url = :image_url"
        expression_attribute_values[':image_url'] = data['image_url']
    
    reviews_table.update_item(
        Key={'id': review_id},
        UpdateExpression=update_expression,
        ExpressionAttributeValues=expression_attribute_values,
        ExpressionAttributeNames=expression_attribute_names
    )
    
    # 更新後のレビューを取得
    response = reviews_table.get_item(Key={'id': review_id})
    updated_review = response['Item']
    updated_review['rating'] = float(updated_review['rating'])
    return updated_review


def get_cors_headers(event):
    """CORS対応ヘッダーを生成"""
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
        'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
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


def authenticate_user(event, headers):
    """ユーザー認証とエラーレスポンスを処理"""
    user_id = get_user_id_from_token(event)
    if not user_id:
        return None, create_response(401, {'error': 'Authentication required'}, headers)
    return user_id, None


def handle_get_reviews(event, dynamodb, reviews_table_name, whiskeys_table_name, headers, logger):
    """レビュー取得エンドポイントの処理"""
    query_params = event.get('queryStringParameters') or {}
    path = event.get('path', '')
    
    # パブリックレビューか判定
    is_public_by_path = path.endswith('/public') or path.endswith('/public/')
    is_public_by_param = query_params.get('public') == 'true'
    
    if is_public_by_path or is_public_by_param:
        # パブリックレビュー
        logger.debug("Fetching public reviews")
        reviews = get_public_reviews(dynamodb, reviews_table_name, whiskeys_table_name)
        response_body = {
            'results': reviews,  # フロントエンドとの互換性のため
            'reviews': reviews,
            'count': len(reviews)
        }
        return create_response(200, response_body, headers)
    else:
        # 認証ユーザーのレビュー
        user_id, error_response = authenticate_user(event, headers)
        if error_response:
            return error_response
        
        logger.debug("Fetching user reviews", user_id=user_id)
        reviews = get_user_reviews(dynamodb, reviews_table_name, whiskeys_table_name, user_id)
        response_body = {
            'results': reviews,  # フロントエンドとの互換性のため
            'reviews': reviews,
            'count': len(reviews)
        }
        return create_response(200, response_body, headers)


def handle_post_review(event, dynamodb, reviews_table_name, headers, logger):
    """レビュー作成エンドポイントの処理"""
    user_id, error_response = authenticate_user(event, headers)
    if error_response:
        return error_response
    
    try:
        body = json.loads(event['body'])
        logger.debug("Creating review", user_id=user_id, whiskey_id=body.get('whiskey_id'))
        review = create_review(dynamodb, reviews_table_name, user_id, body)
        return create_response(201, review, headers)
    except (json.JSONDecodeError, KeyError) as e:
        logger.error("Invalid request body for review creation", error=str(e))
        return create_response(400, {'error': 'Invalid request body'}, headers)


def handle_put_review(event, dynamodb, reviews_table_name, headers, logger):
    """レビュー更新エンドポイントの処理"""
    user_id, error_response = authenticate_user(event, headers)
    if error_response:
        return error_response
    
    path_params = event.get('pathParameters') or {}
    review_id = path_params.get('id')
    if not review_id:
        return create_response(400, {'error': 'Review ID required'}, headers)
    
    try:
        body = json.loads(event['body'])
        logger.debug("Updating review", user_id=user_id, review_id=review_id)
        
        review = update_review(dynamodb, reviews_table_name, user_id, review_id, body)
        if not review:
            return create_response(404, {'error': 'Review not found'}, headers)
        
        return create_response(200, review, headers)
    except ValueError as e:
        logger.warning("Unauthorized review update attempt", user_id=user_id, review_id=review_id, error=str(e))
        return create_response(403, {'error': str(e)}, headers)
    except (json.JSONDecodeError, KeyError) as e:
        logger.error("Invalid request body for review update", error=str(e))
        return create_response(400, {'error': 'Invalid request body'}, headers)


def lambda_handler(event, context):
    """
    Reviews API統合ハンドラー
    GET /api/reviews?public=true → パブリックレビュー
    GET /api/reviews/public/ → パブリックレビュー（後方互換性）
    GET /api/reviews → 認証ユーザーのレビュー
    POST /api/reviews → レビュー作成
    PUT /api/reviews/{id} → レビュー更新
    """
    start_time = time.time()
    
    # ロガー初期化
    correlation_id = extract_correlation_id(event)
    logger = get_logger(
        function_name='reviews',
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
        method = event['httpMethod']
        
        # DynamoDBセットアップ
        dynamodb = boto3.resource('dynamodb')
        reviews_table_name = os.environ['REVIEWS_TABLE']
        whiskeys_table_name = os.environ['WHISKEYS_TABLE']
        
        # HTTPメソッドごとに処理を分岐
        if method == 'GET':
            return handle_get_reviews(event, dynamodb, reviews_table_name, whiskeys_table_name, headers, logger)
        elif method == 'POST':
            return handle_post_review(event, dynamodb, reviews_table_name, headers, logger)
        elif method == 'PUT':
            return handle_put_review(event, dynamodb, reviews_table_name, headers, logger)
        else:
            return create_response(405, {'error': 'Method not allowed'}, headers)
        
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