"""
Whiskeys List Lambda Function
軽量なウイスキー一覧取得API
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


def lambda_handler(event, context):
    """
    GET /whiskeys
    全てのウイスキー一覧を返す
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
        # DynamoDB setup
        dynamodb = boto3.resource('dynamodb')
        table_name = os.environ['WHISKEYS_TABLE']
        table = dynamodb.Table(table_name)
        
        # Scan all whiskeys
        response = table.scan()
        
        whiskeys = []
        for item in response['Items']:
            whiskey = {
                'id': item['id'],
                'name': item.get('name_en', item.get('name', '')),  # WhiskeySearchテーブルのスキーマに対応
                'distillery': item.get('distillery_en', item.get('distillery', '')),  # WhiskeySearchテーブルのスキーマに対応
                'created_at': item.get('created_at', ''),
                'updated_at': item.get('updated_at', '')
            }
            whiskeys.append(whiskey)
        
        # Sort by name
        whiskeys.sort(key=lambda x: x['name'])
        
        return {
            'statusCode': 200,
            'headers': headers,
            'body': json.dumps({
                'whiskeys': whiskeys,
                'count': len(whiskeys)
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