#!/usr/bin/env python3
import requests
import json
from datetime import date, timedelta
import random

# API base URL
API_BASE = "http://localhost:8000/api"

# Sample whiskey data
WHISKEYS = [
    {"name": "山崎 12年", "distillery": "サントリー山崎蒸溜所"},
    {"name": "響 17年", "distillery": "サントリー"},
    {"name": "白州 12年", "distillery": "サントリー白州蒸溜所"},
    {"name": "竹鶴 17年", "distillery": "ニッカウヰスキー余市蒸溜所"},
    {"name": "余市", "distillery": "ニッカウヰスキー余市蒸溜所"},
    {"name": "知多", "distillery": "サントリー知多蒸溜所"},
    {"name": "イチローズモルト", "distillery": "ベンチャーウイスキー"},
    {"name": "駒ヶ岳", "distillery": "マルスウイスキー"},
    {"name": "富士山麓", "distillery": "富士御殿場蒸溜所"},
    {"name": "ニッカ フロム ザ バレル", "distillery": "ニッカウヰスキー"},
]

SERVING_STYLES = ["NEAT", "ROCKS", "WATER", "SODA", "COCKTAIL"]

def create_review(whiskey_name, distillery, rating, serving_style, date_str, notes):
    """Create a review via API"""
    data = {
        "whiskey_name": whiskey_name,
        "whiskey_distillery": distillery,
        "rating": rating,
        "serving_style": serving_style,
        "date": date_str,
        "notes": notes
    }
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer dummy-token"  # The middleware will ignore this in debug mode
    }
    
    try:
        response = requests.post(f"{API_BASE}/reviews", json=data, headers=headers)
        if response.status_code == 201:
            print(f"Created review for {whiskey_name}")
            return True
        else:
            print(f"Failed to create review for {whiskey_name}: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"Error creating review for {whiskey_name}: {e}")
        return False

def main():
    print("Creating test reviews...")
    
    # Create reviews for the last 30 days
    for i in range(30):
        review_date = date.today() - timedelta(days=i)
        date_str = review_date.strftime("%Y-%m-%d")
        
        # Some days have multiple reviews
        for _ in range(random.randint(0, 2)):
            whiskey = random.choice(WHISKEYS)
            rating = random.randint(3, 5)  # Better ratings for demo
            serving_style = random.choice(SERVING_STYLES)
            notes = f'{whiskey["name"]}の素晴らしいテイスティングでした。複雑で豊かな風味があり、とても満足しています。'
            
            create_review(
                whiskey["name"],
                whiskey["distillery"],
                rating,
                serving_style,
                date_str,
                notes
            )

    print("Test data creation completed!")

if __name__ == "__main__":
    main() 