#!/usr/bin/env python3
"""
DynamoDBにサンプルデータを作成するスクリプト
"""
import os
import boto3
import uuid
from datetime import datetime, timedelta
from decimal import Decimal

# AWS設定
AWS_REGION = 'ap-northeast-1'
ENVIRONMENT = 'dev'  # dev or prod

# テーブル名
WHISKEYS_TABLE = f'Whiskeys-{ENVIRONMENT}'
REVIEWS_TABLE = f'Reviews-{ENVIRONMENT}'

# DynamoDBクライアント
dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)

def create_whiskey(table, whiskey_data):
    """ウイスキーを作成"""
    try:
        table.put_item(Item=whiskey_data)
        print(f"Created whiskey: {whiskey_data['name']}")
        return whiskey_data['id']
    except Exception as e:
        print(f"Error creating whiskey {whiskey_data['name']}: {e}")
        return None

def create_review(table, review_data):
    """レビューを作成"""
    try:
        table.put_item(Item=review_data)
        print(f"Created review: {review_data['id']}")
        return True
    except Exception as e:
        print(f"Error creating review {review_data['id']}: {e}")
        return False

def main():
    # テーブル取得
    whiskeys_table = dynamodb.Table(WHISKEYS_TABLE)
    reviews_table = dynamodb.Table(REVIEWS_TABLE)
    
    print(f"Creating sample data for environment: {ENVIRONMENT}")
    print(f"Whiskeys table: {WHISKEYS_TABLE}")
    print(f"Reviews table: {REVIEWS_TABLE}")
    
    # サンプルウイスキーデータ
    whiskeys = [
        {
            'id': str(uuid.uuid4()),
            'name': '山崎 12年',
            'distillery': 'サントリー山崎蒸溜所',
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat(),
        },
        {
            'id': str(uuid.uuid4()),
            'name': '響 17年',
            'distillery': 'サントリー',
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat(),
        },
        {
            'id': str(uuid.uuid4()),
            'name': '白州 12年',
            'distillery': 'サントリー白州蒸溜所',
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat(),
        },
        {
            'id': str(uuid.uuid4()),
            'name': '竹鶴 17年',
            'distillery': 'ニッカウヰスキー余市蒸溜所',
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat(),
        },
        {
            'id': str(uuid.uuid4()),
            'name': 'ザ・マッカラン 18年',
            'distillery': 'ザ・マッカラン蒸溜所',
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat(),
        },
    ]
    
    # ウイスキーを作成
    whiskey_ids = []
    for whiskey in whiskeys:
        whiskey_id = create_whiskey(whiskeys_table, whiskey)
        if whiskey_id:
            whiskey_ids.append((whiskey_id, whiskey['name'], whiskey['distillery']))
    
    # サンプルレビューデータ
    serving_styles = ['Neat', 'On the Rocks', 'Water', 'Highball', 'Cocktail']
    sample_notes = [
        '非常に複雑で豊かな風味があり、バニラとカラメルの甘い香りが印象的でした。口当たりも滑らかで、余韻も長く続きます。',
        'フルーティーで花のような香りが素晴らしく、蜂蜜のような甘さとスパイスのバランスが絶妙です。',
        '深いコクと渋みがあり、ドライフルーツとナッツの風味が感じられます。食後に最適です。',
        'ピートの香りがしっかりとしており、スモーキーで力強い味わいです。慣れ親しんだ方におすすめ。',
        'エレガントで上品な味わいで、シェリー樽の影響が感じられます。特別な日にふさわしい一本。',
    ]
    
    user_ids = ['user-1', 'user-2', 'user-3']  # サンプルユーザー
    
    # レビューを作成
    for whiskey_id, whiskey_name, distillery in whiskey_ids:
        # 各ウイスキーに対して複数のレビューを作成
        for i in range(3):
            review_date = datetime.now() - timedelta(days=i * 7)
            review_data = {
                'id': str(uuid.uuid4()),
                'whiskey_id': whiskey_id,
                'user_id': user_ids[i % len(user_ids)],
                'notes': sample_notes[i % len(sample_notes)],
                'rating': 4 + (i % 2),  # 4 or 5
                'serving_style': serving_styles[i % len(serving_styles)],
                'date': review_date.strftime('%Y-%m-%d'),
                'created_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat(),
            }
            create_review(reviews_table, review_data)
    
    print("\nSample data creation completed!")
    print(f"Created {len(whiskeys)} whiskeys and approximately {len(whiskeys) * 3} reviews")

if __name__ == "__main__":
    main() 