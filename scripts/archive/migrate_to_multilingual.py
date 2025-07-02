#!/usr/bin/env python3
"""
既存のWhiskeysテーブルデータをWhiskeySearchテーブルに移行
英語名を追加して多言語対応
"""

import os
import sys
import json
from typing import Dict, List

# Django設定を読み込み
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')

import django
django.setup()

from backend.api.dynamodb_service import DynamoDBService

# 英語-日本語マッピング（既存データ用）
WHISKEY_TRANSLATION_MAP = {
    # 日本語名: 英語名
    'ザ・マッカラン 18年': 'The Macallan 18 Years',
    '山崎 12年': 'Yamazaki 12 Years',
    '白州 12年': 'Hakushu 12 Years', 
    '竹鶴 17年': 'Taketsuru 17 Years',
    '響 17年': 'Hibiki 17 Years',
    'test1': 'test1',
}

DISTILLERY_TRANSLATION_MAP = {
    # 日本語蒸留所名: 英語蒸留所名
    'ザ・マッカラン蒸留所': 'The Macallan Distillery',
    'サントリー山崎蒸留所': 'Suntory Yamazaki Distillery',
    'サントリー白州蒸留所': 'Suntory Hakushu Distillery',
    'ニッカウヰスキー余市蒸留所': 'Nikka Whisky Yoichi Distillery',
    'サントリー': 'Suntory',
    'test2': 'test2',
}


class MultilingualMigration:
    def __init__(self):
        self.db_service = DynamoDBService()
        
    def get_existing_whiskeys(self) -> List[Dict]:
        """既存のWhiskeysテーブルからデータを取得"""
        try:
            response = self.db_service.whiskey_table.scan()
            return response.get('Items', [])
        except Exception as e:
            print(f"Error getting existing whiskeys: {e}")
            return []
    
    def translate_whiskey_name(self, japanese_name: str) -> str:
        """日本語ウイスキー名を英語に翻訳"""
        return WHISKEY_TRANSLATION_MAP.get(japanese_name, japanese_name)
    
    def translate_distillery_name(self, japanese_distillery: str) -> str:
        """日本語蒸留所名を英語に翻訳"""
        return DISTILLERY_TRANSLATION_MAP.get(japanese_distillery, japanese_distillery)
    
    def migrate_whiskey_to_search_table(self, whiskey: Dict) -> bool:
        """単一のウイスキーをWhiskeySearchテーブルに移行"""
        try:
            # 英語名を生成
            name_ja = whiskey.get('name', '')
            distillery_ja = whiskey.get('distillery', '')
            
            name_en = self.translate_whiskey_name(name_ja)
            distillery_en = self.translate_distillery_name(distillery_ja)
            
            # WhiskeySearchテーブル用のデータ構造
            search_data = {
                'name': name_en,  # 英語名をメインに
                'name_ja': name_ja,
                'distillery': distillery_en,  # 英語蒸留所名をメインに  
                'distillery_ja': distillery_ja,
                'description': f'{name_ja} from {distillery_ja}',
                'region': 'Japan' if any(jp in distillery_ja for jp in ['サントリー', '山崎', '白州', '響', 'ニッカ']) else '',
                'type': 'Single Malt' if '山崎' in name_ja or '白州' in name_ja else 'Whisky',
                'original_id': whiskey.get('id'),  # 元のID保存
                'created_at': whiskey.get('created_at'),
                'updated_at': whiskey.get('updated_at')
            }
            
            # WhiskeySearchテーブルに保存
            result = self.db_service.create_whiskey_search_entry(search_data)
            
            print(f"✅ 移行完了: {name_ja} -> {name_en}")
            return True
            
        except Exception as e:
            print(f"❌ 移行失敗: {whiskey.get('name', 'Unknown')}: {e}")
            return False
    
    def run_migration(self) -> Dict:
        """全体の移行を実行"""
        print("=== 多言語対応移行開始 ===")
        
        # 既存データを取得
        existing_whiskeys = self.get_existing_whiskeys()
        print(f"移行対象: {len(existing_whiskeys)}件")
        
        if not existing_whiskeys:
            print("移行するデータがありません")
            return {'migrated': 0, 'failed': 0}
        
        # 既存のWhiskeySearchテーブルのデータ確認
        try:
            search_response = self.db_service.whiskey_search_table.scan()
            existing_search_count = len(search_response.get('Items', []))
            if existing_search_count > 0:
                print(f"⚠️  WhiskeySearchテーブルに既存データが {existing_search_count}件 あります")
                response = input("続行しますか？ (y/N): ")
                if response.lower() != 'y':
                    print("移行をキャンセルしました")
                    return {'migrated': 0, 'failed': 0}
        except Exception as e:
            print(f"WhiskeySearchテーブル確認中にエラー: {e}")
        
        # データを1件ずつ移行
        migrated_count = 0
        failed_count = 0
        
        for whiskey in existing_whiskeys:
            if self.migrate_whiskey_to_search_table(whiskey):
                migrated_count += 1
            else:
                failed_count += 1
        
        print(f"\n=== 移行完了 ===")
        print(f"成功: {migrated_count}件")
        print(f"失敗: {failed_count}件")
        
        # 移行後のWhiskeySearchテーブル確認
        try:
            search_response = self.db_service.whiskey_search_table.scan()
            search_count = len(search_response.get('Items', []))
            print(f"WhiskeySearchテーブル総件数: {search_count}件")
        except Exception as e:
            print(f"移行後確認エラー: {e}")
        
        return {
            'migrated': migrated_count,
            'failed': failed_count,
            'total_in_search_table': search_count
        }
    
    def show_translation_map(self):
        """現在の翻訳マッピングを表示"""
        print("\n=== 現在の翻訳マッピング ===")
        print("ウイスキー名:")
        for ja, en in WHISKEY_TRANSLATION_MAP.items():
            print(f"  {ja} -> {en}")
        
        print("\n蒸留所名:")
        for ja, en in DISTILLERY_TRANSLATION_MAP.items():
            print(f"  {ja} -> {en}")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='多言語対応移行スクリプト')
    parser.add_argument('--show-map', action='store_true', help='翻訳マッピングを表示')
    parser.add_argument('--dry-run', action='store_true', help='実際の移行を行わずに確認のみ')
    
    args = parser.parse_args()
    
    migration = MultilingualMigration()
    
    if args.show_map:
        migration.show_translation_map()
        return
    
    if args.dry_run:
        print("=== DRY RUN モード ===")
        existing = migration.get_existing_whiskeys()
        print(f"移行対象: {len(existing)}件")
        for whiskey in existing:
            name_ja = whiskey.get('name', '')
            distillery_ja = whiskey.get('distillery', '')
            name_en = migration.translate_whiskey_name(name_ja)
            distillery_en = migration.translate_distillery_name(distillery_ja)
            print(f"  {name_ja} ({distillery_ja}) -> {name_en} ({distillery_en})")
        return
    
    # 実際の移行実行
    result = migration.run_migration()
    
    # 結果をJSONファイルに保存
    import datetime
    result_file = f"migration_result_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(result_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    print(f"\n移行結果を {result_file} に保存しました")


if __name__ == '__main__':
    main()