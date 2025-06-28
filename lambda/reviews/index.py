"""
Reviews Lambda Function
統合レビューCRUD API
"""
import json
import boto3
import os
import uuid
from decimal import Decimal
from datetime import datetime


def decimal_default(obj):
    """DynamoDB Decimal型をJSONシリアライズ可能に変換"""
    if isinstance(obj, Decimal):
        return float(obj)
    elif isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError


def get_user_id_from_token(event):
    """
    Cognito JWT トークンからuser_idを取得
    """
    # まずAPI Gateway Cognito Authorizerからの情報を確認
    claims = event.get('requestContext', {}).get('authorizer', {}).get('claims', {})
    user_id = claims.get('sub')
    
    if user_id:
        return user_id
    
    # 手動でJWTトークンを解析する場合
    auth_header = event.get('headers', {}).get('Authorization') or event.get('headers', {}).get('authorization')
    if auth_header and auth_header.startswith('Bearer '):
        token = auth_header.replace('Bearer ', '')
        # 簡単なJWTデコード（本来はVerifyすべき）
        import base64
        try:
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
            print(f"JWT decode error: {e}")
    
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


def lambda_handler(event, context):
    """
    Reviews API統合ハンドラー
    GET /api/reviews?public=true → パブリックレビュー
    GET /api/reviews/public/ → パブリックレビュー（後方互換性）
    GET /api/reviews → 認証ユーザーのレビュー
    POST /api/reviews → レビュー作成
    PUT /api/reviews/{id} → レビュー更新
    """
    
    # Response headers with CORS support
    origin = event.get('headers', {}).get('origin') or event.get('headers', {}).get('Origin')
    allowed_origins = ['https://dev.whiskeybar.site', 'https://whiskeybar.site', 'http://localhost:3000']
    
    headers = {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': origin if origin in allowed_origins else 'https://dev.whiskeybar.site',
        'Access-Control-Allow-Headers': 'Content-Type, Authorization',
        'Access-Control-Allow-Methods': 'GET, POST, PUT, OPTIONS',
    }
    
    # OPTIONS requests handled by API Gateway
    
    try:
        method = event['httpMethod']
        query_params = event.get('queryStringParameters') or {}
        path_params = event.get('pathParameters') or {}
        
        # DynamoDB setup
        dynamodb = boto3.resource('dynamodb')
        reviews_table_name = os.environ['REVIEWS_TABLE']
        whiskeys_table_name = os.environ['WHISKEYS_TABLE']
        
        if method == 'GET':
            # パスベースでパブリックレビューを判定（後方互換性）
            path = event.get('path', '')
            is_public_by_path = path.endswith('/public') or path.endswith('/public/')
            is_public_by_param = query_params.get('public') == 'true'
            
            if is_public_by_path or is_public_by_param:
                # パブリックレビュー
                reviews = get_public_reviews(dynamodb, reviews_table_name, whiskeys_table_name)
                return {
                    'statusCode': 200,
                    'headers': headers,
                    'body': json.dumps({
                        'results': reviews,  # フロントエンドとの互換性のため
                        'reviews': reviews,
                        'count': len(reviews)
                    }, default=decimal_default)
                }
            else:
                # 認証ユーザーのレビュー
                user_id = get_user_id_from_token(event)
                if not user_id:
                    return {
                        'statusCode': 401,
                        'headers': headers,
                        'body': json.dumps({'error': 'Authentication required'})
                    }
                
                reviews = get_user_reviews(dynamodb, reviews_table_name, whiskeys_table_name, user_id)
                return {
                    'statusCode': 200,
                    'headers': headers,
                    'body': json.dumps({
                        'results': reviews,  # フロントエンドとの互換性のため
                        'reviews': reviews,
                        'count': len(reviews)
                    }, default=decimal_default)
                }
        
        elif method == 'POST':
            # レビュー作成
            user_id = get_user_id_from_token(event)
            if not user_id:
                return {
                    'statusCode': 401,
                    'headers': headers,
                    'body': json.dumps({'error': 'Authentication required'})
                }
            
            body = json.loads(event['body'])
            review = create_review(dynamodb, reviews_table_name, user_id, body)
            
            return {
                'statusCode': 201,
                'headers': headers,
                'body': json.dumps(review, default=decimal_default)
            }
        
        elif method == 'PUT':
            # レビュー更新
            user_id = get_user_id_from_token(event)
            if not user_id:
                return {
                    'statusCode': 401,
                    'headers': headers,
                    'body': json.dumps({'error': 'Authentication required'})
                }
            
            review_id = path_params.get('id')
            if not review_id:
                return {
                    'statusCode': 400,
                    'headers': headers,
                    'body': json.dumps({'error': 'Review ID required'})
                }
            
            body = json.loads(event['body'])
            
            try:
                review = update_review(dynamodb, reviews_table_name, user_id, review_id, body)
                if not review:
                    return {
                        'statusCode': 404,
                        'headers': headers,
                        'body': json.dumps({'error': 'Review not found'})
                    }
                
                return {
                    'statusCode': 200,
                    'headers': headers,
                    'body': json.dumps(review, default=decimal_default)
                }
            except ValueError as e:
                return {
                    'statusCode': 403,
                    'headers': headers,
                    'body': json.dumps({'error': str(e)})
                }
        
        else:
            return {
                'statusCode': 405,
                'headers': headers,
                'body': json.dumps({'error': 'Method not allowed'})
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