#!/usr/bin/env python3
"""
既存のWhiskeysテーブルデータをWhiskeySearchテーブルに移行
シンプルなDynamoDBアクセス版
"""

import boto3
import json
import uuid
from datetime import datetime
from typing import Dict, List

# 英語-日本語マッピング
WHISKEY_TRANSLATION_MAP = {
    'ザ・マッカラン 18年': 'The Macallan 18 Years',
    '山崎 12年': 'Yamazaki 12 Years',
    '白州 12年': 'Hakushu 12 Years', 
    '竹鶴 17年': 'Taketsuru 17 Years',
    '響 17年': 'Hibiki 17 Years',
    'test1': 'test1',
}

DISTILLERY_TRANSLATION_MAP = {
    'ザ・マッカラン蒸留所': 'The Macallan Distillery',
    'ザ・マッカラン蒸溜所': 'The Macallan Distillery',
    'サントリー山崎蒸留所': 'Suntory Yamazaki Distillery',
    'サントリー山崎蒸溜所': 'Suntory Yamazaki Distillery',
    'サントリー白州蒸留所': 'Suntory Hakushu Distillery',
    'サントリー白州蒸溜所': 'Suntory Hakushu Distillery',
    'ニッカウヰスキー余市蒸留所': 'Nikka Whisky Yoichi Distillery',
    'ニッカウヰスキー余市蒸溜所': 'Nikka Whisky Yoichi Distillery',
    'サントリー': 'Suntory',
    'test2': 'test2',
}


class SimpleMigration:
    def __init__(self):
        self.dynamodb = boto3.resource('dynamodb', region_name='ap-northeast-1')
        self.whiskeys_table = self.dynamodb.Table('Whiskeys-dev')
        self.search_table = self.dynamodb.Table('WhiskeySearch-dev')
    
    def normalize_text(self, text: str) -> str:
        """テキストを検索用に正規化"""
        if not text:
            return ''
        return text.lower().replace(' ', '').replace('　', '')
    
    def get_existing_whiskeys(self) -> List[Dict]:
        """既存のWhiskeysテーブルからデータを取得"""
        try:
            response = self.whiskeys_table.scan()
            return response.get('Items', [])
        except Exception as e:
            print(f"Error getting existing whiskeys: {e}")
            return []
    
    def migrate_whiskey(self, whiskey: Dict) -> bool:
        """単一のウイスキーを移行"""
        try:
            name_ja = whiskey.get('name', '')
            distillery_ja = whiskey.get('distillery', '')
            
            # 英語名を取得
            name_en = WHISKEY_TRANSLATION_MAP.get(name_ja, name_ja)
            distillery_en = DISTILLERY_TRANSLATION_MAP.get(distillery_ja, distillery_ja)
            
            # WhiskeySearchテーブル用データ
            entry_id = str(uuid.uuid4())
            now = datetime.now().isoformat()
            
            item = {
                'id': entry_id,
                'name_en': name_en,
                'name_ja': name_ja,
                'distillery_en': distillery_en,
                'distillery_ja': distillery_ja,
                'normalized_name_en': self.normalize_text(name_en),
                'normalized_name_ja': self.normalize_text(name_ja),
                'normalized_distillery_en': self.normalize_text(distillery_en),
                'normalized_distillery_ja': self.normalize_text(distillery_ja),
                'description': f'{name_ja} from {distillery_ja}',
                'region': 'Japan' if any(jp in distillery_ja for jp in ['サントリー', '山崎', '白州', '響', 'ニッカ']) else '',
                'type': 'Single Malt' if '山崎' in name_ja or '白州' in name_ja else 'Whisky',
                'original_whiskey_id': whiskey.get('id'),
                'created_at': whiskey.get('created_at', now),
                'updated_at': now
            }
            
            # WhiskeySearchテーブルに保存
            self.search_table.put_item(Item=item)
            
            print(f"✅ 移行完了: {name_ja} -> {name_en}")
            return True
            
        except Exception as e:
            print(f"❌ 移行失敗: {whiskey.get('name', 'Unknown')}: {e}")
            return False
    
    def run_migration(self) -> Dict:
        """移行実行"""
        print("=== 多言語対応移行開始 ===")
        
        # 既存データ取得
        existing_whiskeys = self.get_existing_whiskeys()
        print(f"移行対象: {len(existing_whiskeys)}件")
        
        if not existing_whiskeys:
            print("移行するデータがありません")
            return {'migrated': 0, 'failed': 0}
        
        # 移行実行
        migrated_count = 0
        failed_count = 0
        
        for whiskey in existing_whiskeys:
            if self.migrate_whiskey(whiskey):
                migrated_count += 1
            else:
                failed_count += 1
        
        print(f"\n=== 移行完了 ===")
        print(f"成功: {migrated_count}件")
        print(f"失敗: {failed_count}件")
        
        return {'migrated': migrated_count, 'failed': failed_count}
    
    def show_current_data(self):
        """現在のデータを表示"""
        print("=== 現在のWhiskeysテーブルデータ ===")
        whiskeys = self.get_existing_whiskeys()
        for whiskey in whiskeys:
            name = whiskey.get('name', '')
            distillery = whiskey.get('distillery', '')
            name_en = WHISKEY_TRANSLATION_MAP.get(name, name)
            distillery_en = DISTILLERY_TRANSLATION_MAP.get(distillery, distillery)
            print(f"  {name} ({distillery}) -> {name_en} ({distillery_en})")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='多言語対応移行スクリプト')
    parser.add_argument('--show-data', action='store_true', help='現在のデータを表示')
    parser.add_argument('--dry-run', action='store_true', help='実際の移行を行わずに確認のみ')
    
    args = parser.parse_args()
    
    migration = SimpleMigration()
    
    if args.show_data:
        migration.show_current_data()
        return
    
    if args.dry_run:
        print("=== DRY RUN モード ===")
        migration.show_current_data()
        return
    
    # 実際の移行実行
    result = migration.run_migration()
    
    # 結果保存
    result_file = f"migration_result_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(result_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    print(f"\n移行結果を {result_file} に保存しました")


if __name__ == '__main__':
    main()