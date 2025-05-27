#!/usr/bin/env python3
"""
API経由でサンプルデータを作成するスクリプト
"""
import requests
import json
from datetime import datetime, timedelta
import time

# API設定
API_BASE = "https://api.dev.whiskeybar.site"

def create_review_via_api(whiskey_name, distillery, rating, serving_style, date_str, notes):
    """API経由でレビューを作成"""
    data = {
        "whiskey": "dummy-whiskey-id",  # ダミーID（APIが新しいウイスキーを作成する）
        "whiskey_name": whiskey_name,
        "whiskey_distillery": distillery,
        "rating": rating,
        "serving_style": serving_style,
        "date": date_str,
        "notes": notes
    }
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer dummy-token"  # 開発環境では無視される
    }
    
    try:
        response = requests.post(f"{API_BASE}/api/reviews/", json=data, headers=headers)
        if response.status_code == 201:
            print(f"✅ Created review for {whiskey_name}")
            return True
        else:
            print(f"❌ Failed to create review for {whiskey_name}: {response.status_code}")
            if response.text:
                print(f"   Response: {response.text}")
            return False
    except Exception as e:
        print(f"❌ Error creating review for {whiskey_name}: {e}")
        return False

def test_api_connection():
    """API接続をテスト"""
    try:
        response = requests.get(f"{API_BASE}/health/")
        if response.status_code == 200:
            print("✅ API connection successful")
            return True
        else:
            print(f"❌ API connection failed: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ API connection error: {e}")
        return False

def main():
    print("🚀 Creating sample whiskey reviews via API...")
    print(f"API Base URL: {API_BASE}")
    
    # API接続テスト
    if not test_api_connection():
        print("💥 Cannot connect to API. Please check the API is running.")
        return
    
    # サンプルウイスキーとレビューデータ
    sample_data = [
        {
            "whiskey_name": "山崎 12年",
            "distillery": "サントリー山崎蒸溜所",
            "reviews": [
                                 {
                     "rating": 5,
                     "serving_style": "NEAT",
                     "notes": "非常に複雑で豊かな風味があり、バニラとカラメルの甘い香りが印象的でした。口当たりも滑らかで、余韻も長く続きます。日本のウイスキーの最高峰と言える素晴らしい一本です。"
                 },
                 {
                     "rating": 4,
                     "serving_style": "ROCKS",
                     "notes": "氷を加えることで香りが開き、より飲みやすくなります。水割りとは違う、洗練された味わいが楽しめました。"
                 }
            ]
        },
        {
            "whiskey_name": "響 17年",
            "distillery": "サントリー",
            "reviews": [
                                 {
                     "rating": 5,
                     "serving_style": "NEAT",
                     "notes": "エレガントで上品な味わいで、シェリー樽の影響が感じられます。特別な日にふさわしい最高級の一本。フルーティーで花のような香りが素晴らしく絶妙なバランスです。"
                 },
                 {
                     "rating": 5,
                     "serving_style": "WATER",
                     "notes": "少量の水を加えることで、香りがさらに開花します。響らしい調和の取れた味わいが一層引き立ちます。"
                 }
            ]
        },
        {
            "whiskey_name": "白州 12年",
            "distillery": "サントリー白州蒸溜所",
            "reviews": [
                                 {
                     "rating": 4,
                     "serving_style": "SODA",
                     "notes": "ハイボールにすると、白州の爽やかな特徴が際立ちます。森林浴をしているような清々しい香りと味わいが楽しめます。"
                 },
                 {
                     "rating": 4,
                     "serving_style": "NEAT",
                     "notes": "ピートの香りがほのかに感じられ、フレッシュで軽やかな味わいです。夏場に特におすすめしたいウイスキーです。"
                 }
            ]
        },
        {
            "whiskey_name": "竹鶴 17年",
            "distillery": "ニッカウヰスキー余市蒸溜所",
            "reviews": [
                                 {
                     "rating": 5,
                     "serving_style": "NEAT",
                     "notes": "ピートの香りがしっかりとしており、スモーキーで力強い味わいです。余市と宮城峡のモルトの絶妙なブレンドが感じられる名作です。"
                 },
                 {
                     "rating": 4,
                     "serving_style": "ROCKS",
                     "notes": "氷を加えることで、強いピート感がやや和らぎ、より親しみやすい味わいになります。深いコクと複雑さは健在です。"
                 }
            ]
        },
        {
            "whiskey_name": "ザ・マッカラン 18年",
            "distillery": "ザ・マッカラン蒸溜所",
            "reviews": [
                                 {
                     "rating": 5,
                     "serving_style": "NEAT",
                     "notes": "シェリー樽由来の豊かな果実味と、ドライフルーツ、ナッツの風味が絶妙に調和しています。スコッチウイスキーの王道を行く素晴らしい一本です。"
                 },
                 {
                     "rating": 4,
                     "serving_style": "WATER",
                     "notes": "少量の水を加えることで、隠れていた複雑な香りが現れます。チョコレートやスパイスのニュアンスも感じられました。"
                 }
            ]
        }
    ]
    
    success_count = 0
    total_count = 0
    
    for whiskey_data in sample_data:
        whiskey_name = whiskey_data["whiskey_name"]
        distillery = whiskey_data["distillery"]
        
        print(f"\n📝 Creating reviews for {whiskey_name}...")
        
        for i, review_data in enumerate(whiskey_data["reviews"]):
            # 日付を少しずつずらす
            review_date = datetime.now() - timedelta(days=i * 7)
            date_str = review_date.strftime("%Y-%m-%d")
            
            success = create_review_via_api(
                whiskey_name=whiskey_name,
                distillery=distillery,
                rating=review_data["rating"],
                serving_style=review_data["serving_style"],
                date_str=date_str,
                notes=review_data["notes"]
            )
            
            if success:
                success_count += 1
            total_count += 1
            
            # API制限を避けるため少し待機
            time.sleep(1)
    
    print(f"\n🎉 Sample data creation completed!")
    print(f"📊 Created {success_count}/{total_count} reviews successfully")
    
    # パブリックレビューAPIをテスト
    print(f"\n🔍 Testing public reviews API...")
    try:
        response = requests.get(f"{API_BASE}/api/reviews/public/?page=1&per_page=5")
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Public reviews API working: {data.get('count', 0)} reviews found")
        else:
            print(f"❌ Public reviews API test failed: {response.status_code}")
    except Exception as e:
        print(f"❌ Public reviews API test error: {e}")

if __name__ == "__main__":
    main() 