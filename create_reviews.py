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
]

SERVING_STYLES = ["NEAT", "ROCKS", "WATER", "SODA", "COCKTAIL"]

def get_or_create_whiskey(name, distillery):
    """Get or create a whiskey by checking if it exists first"""
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer dummy-token"
    }
    
    # Try to find existing whiskey by searching
    response = requests.get(f"{API_BASE}/whiskeys/suggest?q={name}", headers=headers)
    if response.status_code == 200:
        whiskeys = response.json()
        for whiskey in whiskeys:
            if whiskey['name'] == name and whiskey['distillery'] == distillery:
                return whiskey['id']
    
    # If not found, we would create it, but the API might not have this endpoint
    # For now, let's manually specify IDs or create via Django admin
    return None

def create_review(whiskey_id, rating, serving_style, date_str, notes):
    """Create a review via API"""
    if whiskey_id is None:
        return False
        
    data = {
        "whiskey": whiskey_id,
        "rating": rating,
        "serving_style": serving_style,
        "date": date_str,
        "notes": notes
    }
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer dummy-token"
    }
    
    try:
        response = requests.post(f"{API_BASE}/reviews/", json=data, headers=headers)
        if response.status_code == 201:
            print(f"Created review for whiskey {whiskey_id}")
            return True
        else:
            print(f"Failed to create review: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"Error creating review: {e}")
        return False

def main():
    print("Creating test reviews...")
    
    # First, let's see what whiskeys exist by checking the suggest endpoint
    for whiskey in WHISKEYS:
        whiskey_id = get_or_create_whiskey(whiskey["name"], whiskey["distillery"])
        if whiskey_id:
            print(f"Found whiskey: {whiskey['name']} with ID {whiskey_id}")
            
            # Create a few reviews for this whiskey
            for i in range(3):
                review_date = date.today() - timedelta(days=i)
                date_str = review_date.strftime("%Y-%m-%d")
                rating = random.randint(4, 5)
                serving_style = random.choice(SERVING_STYLES)
                notes = f'{whiskey["name"]}の素晴らしいテイスティングでした。複雑で豊かな風味があり、とても満足しています。'
                
                create_review(whiskey_id, rating, serving_style, date_str, notes)
        else:
            print(f"Could not find whiskey: {whiskey['name']}")

    print("Test data creation completed!")

if __name__ == "__main__":
    main() 