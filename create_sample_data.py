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
AWS_PROFILE = 'dev'  # AWSプロファイル名
ENVIRONMENT = 'dev'  # dev or prod

# テーブル名
WHISKEYS_TABLE = f'Whiskeys-{ENVIRONMENT}'
REVIEWS_TABLE = f'Reviews-{ENVIRONMENT}'

# AWSセッションとDynamoDBクライアント
session = boto3.Session(profile_name=AWS_PROFILE)
dynamodb = session.resource('dynamodb', region_name=AWS_REGION)

def create_whiskey(table, whiskey_data):
    """ウイスキーを作成"""
    try:
        table.put_item(Item=whiskey_data)
        print(f"✅ Created whiskey: {whiskey_data['name']} ({whiskey_data['distillery']})")
        return whiskey_data['id']
    except Exception as e:
        print(f"❌ Error creating whiskey {whiskey_data['name']}: {e}")
        return None

def create_review(table, review_data):
    """レビューを作成"""
    try:
        table.put_item(Item=review_data)
        return True
    except Exception as e:
        print(f"❌ Error creating review: {e}")
        return False

def test_connection():
    """AWS接続とテーブル存在確認"""
    try:
        whiskeys_table = dynamodb.Table(WHISKEYS_TABLE)
        reviews_table = dynamodb.Table(REVIEWS_TABLE)
        
        # テーブル存在確認
        whiskeys_table.load()
        reviews_table.load()
        
        print(f"✅ Connected to AWS with profile: {AWS_PROFILE}")
        print(f"✅ Whiskeys table exists: {WHISKEYS_TABLE}")
        print(f"✅ Reviews table exists: {REVIEWS_TABLE}")
        return whiskeys_table, reviews_table
    except Exception as e:
        print(f"❌ AWS connection error: {e}")
        print(f"Please check:")
        print(f"  - AWS profile '{AWS_PROFILE}' is configured")
        print(f"  - Tables '{WHISKEYS_TABLE}' and '{REVIEWS_TABLE}' exist")
        print(f"  - Profile has DynamoDB permissions")
        return None, None

def main():
    print(f"🚀 Creating sample data for environment: {ENVIRONMENT}")
    print(f"📊 Using AWS profile: {AWS_PROFILE}")
    print(f"🌍 Region: {AWS_REGION}")
    
    # AWS接続テスト
    whiskeys_table, reviews_table = test_connection()
    if not whiskeys_table or not reviews_table:
        return
    
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
    
    # サンプルレビューデータ（Django ServingStyle.CHOICESに合わせる）
    serving_styles = ['NEAT', 'ROCKS', 'WATER', 'SODA', 'COCKTAIL']
    sample_notes = [
        '非常に複雑で豊かな風味があり、バニラとカラメルの甘い香りが印象的でした。口当たりも滑らかで、余韻も長く続きます。日本のウイスキーの最高峰と言える素晴らしい一本です。',
        'フルーティーで花のような香りが素晴らしく、蜂蜜のような甘さとスパイスのバランスが絶妙です。シェリー樽の影響も感じられ、深みのある味わいです。',
        '深いコクと渋みがあり、ドライフルーツとナッツの風味が感じられます。食後のリラックスタイムに最適で、ゆっくりと味わいたい一本です。',
        'ピートの香りがしっかりとしており、スモーキーで力強い味わいです。余市と宮城峡のモルトが絶妙にブレンドされた名作で、慣れ親しんだ方におすすめです。',
        'エレガントで上品な味わいで、シェリー樽の影響が感じられます。特別な日にふさわしい最高級の一本で、贈り物にも最適です。',
    ]
    
    user_ids = ['user-1', 'user-2', 'user-3']  # サンプルユーザー
    
    # レビューを作成
    print(f"\n📝 Creating reviews...")
    review_count = 0
    for whiskey_id, whiskey_name, distillery in whiskey_ids:
        print(f"\n   Creating reviews for: {whiskey_name}")
        # 各ウイスキーに対して複数のレビューを作成
        for i in range(3):
            review_date = datetime.now() - timedelta(days=i * 7)
            rating = 4 + (i % 2)  # 4 or 5
            serving_style = serving_styles[i % len(serving_styles)]
            review_data = {
                'id': str(uuid.uuid4()),
                'whiskey_id': whiskey_id,
                'user_id': user_ids[i % len(user_ids)],
                'notes': sample_notes[i % len(sample_notes)],
                'rating': rating,
                'serving_style': serving_style,
                'date': review_date.strftime('%Y-%m-%d'),
                'created_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat(),
            }
            if create_review(reviews_table, review_data):
                review_count += 1
                print(f"   ✅ Review #{i+1}: Rating {rating}/5, Style: {serving_style}")
    
    print(f"\n🎉 Sample data creation completed!")
    print(f"📊 Successfully created:")
    print(f"   - {len(whiskey_ids)} whiskeys")
    print(f"   - {review_count} reviews")
    print(f"\n🌐 You can now test the API:")
    print(f"   - Public Reviews: https://api.dev.whiskeybar.site/api/reviews/public/")
    print(f"   - Frontend: https://dev.whiskeybar.site/")

if __name__ == "__main__":
    main() 