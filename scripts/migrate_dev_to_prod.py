#!/usr/bin/env python3
"""
開発環境から本番環境へのデータ移行スクリプト
開発環境のWhiskeySearchテーブルのデータを本番環境に複製
"""

import boto3
import json
from decimal import Decimal
from datetime import datetime
from typing import List, Dict


def decimal_default(obj):
    """Decimal型をJSONシリアライズ可能に変換"""
    if isinstance(obj, Decimal):
        return float(obj)
    elif isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError


class DevToProdMigrator:
    def __init__(self):
        """開発環境と本番環境のDynamoDBクライアントを初期化"""
        # 開発環境
        self.dev_session = boto3.Session(profile_name='dev')
        self.dev_dynamodb = self.dev_session.resource('dynamodb', region_name='ap-northeast-1')
        
        # 本番環境
        self.prd_session = boto3.Session(profile_name='prd')
        self.prd_dynamodb = self.prd_session.resource('dynamodb', region_name='ap-northeast-1')
        
        # テーブル参照
        self.dev_whiskeys_table = self.dev_dynamodb.Table('Whiskeys-dev')
        self.dev_search_table = self.dev_dynamodb.Table('WhiskeySearch-dev')
        
        self.prd_whiskeys_table = self.prd_dynamodb.Table('Whiskeys-prd')
        self.prd_search_table = self.prd_dynamodb.Table('WhiskeySearch-prd')
        
        print("✅ 開発環境・本番環境のDynamoDBクライアント初期化完了")
    
    def get_dev_data_count(self) -> Dict[str, int]:
        """開発環境のデータ数を取得"""
        try:
            whiskeys_response = self.dev_whiskeys_table.scan(Select='COUNT')
            search_response = self.dev_search_table.scan(Select='COUNT')
            
            return {
                'whiskeys_count': whiskeys_response['Count'],
                'search_count': search_response['Count']
            }
        except Exception as e:
            print(f"❌ 開発環境データ数取得エラー: {e}")
            return {'whiskeys_count': 0, 'search_count': 0}
    
    def get_prd_data_count(self) -> Dict[str, int]:
        """本番環境のデータ数を取得"""
        try:
            whiskeys_response = self.prd_whiskeys_table.scan(Select='COUNT')
            search_response = self.prd_search_table.scan(Select='COUNT')
            
            return {
                'whiskeys_count': whiskeys_response['Count'],
                'search_count': search_response['Count']
            }
        except Exception as e:
            print(f"❌ 本番環境データ数取得エラー: {e}")
            return {'whiskeys_count': 0, 'search_count': 0}
    
    def export_dev_data(self) -> Dict[str, List[Dict]]:
        """開発環境のデータを全件取得"""
        try:
            print("📦 開発環境データをエクスポート中...")
            
            # Whiskeysテーブルのデータ取得
            whiskeys_response = self.dev_whiskeys_table.scan()
            whiskeys_items = whiskeys_response['Items']
            
            # WhiskeySearchテーブルのデータ取得
            search_response = self.dev_search_table.scan()
            search_items = search_response['Items']
            
            # Decimal型をfloat型に変換
            whiskeys_items = json.loads(json.dumps(whiskeys_items, default=decimal_default))
            search_items = json.loads(json.dumps(search_items, default=decimal_default))
            
            print(f"✅ データエクスポート完了: Whiskeys={len(whiskeys_items)}件, Search={len(search_items)}件")
            
            return {
                'whiskeys': whiskeys_items,
                'search': search_items
            }
        except Exception as e:
            print(f"❌ 開発環境データエクスポートエラー: {e}")
            return {'whiskeys': [], 'search': []}
    
    def convert_for_production(self, item: Dict) -> Dict:
        """データを本番環境用に変換（必要に応じて）"""
        # 本番環境用のタイムスタンプを更新
        now = datetime.now().isoformat()
        item['updated_at'] = now
        
        # 本番環境用にソースを更新
        if item.get('source') == 'migrated':
            item['source'] = 'dev_migration'
        
        return item
    
    def import_to_production(self, data: Dict[str, List[Dict]]) -> bool:
        """本番環境にデータを投入"""
        try:
            whiskeys_data = data['whiskeys']
            search_data = data['search']
            
            print(f"🚀 本番環境にデータ投入中...")
            print(f"   Whiskeys: {len(whiskeys_data)}件")
            print(f"   Search: {len(search_data)}件")
            
            # Whiskeysテーブルへの投入
            if whiskeys_data:
                with self.prd_whiskeys_table.batch_writer() as batch:
                    for item in whiskeys_data:
                        converted_item = self.convert_for_production(item.copy())
                        # float型をDecimal型に戻す（DynamoDB要件）
                        if 'confidence' in converted_item:
                            converted_item['confidence'] = Decimal(str(converted_item['confidence']))
                        batch.put_item(Item=converted_item)
                print(f"✅ Whiskeysテーブル投入完了: {len(whiskeys_data)}件")
            
            # WhiskeySearchテーブルへの投入
            if search_data:
                with self.prd_search_table.batch_writer() as batch:
                    for item in search_data:
                        converted_item = self.convert_for_production(item.copy())
                        # float型をDecimal型に戻す（DynamoDB要件）
                        if 'confidence' in converted_item:
                            converted_item['confidence'] = Decimal(str(converted_item['confidence']))
                        batch.put_item(Item=converted_item)
                print(f"✅ WhiskeySearchテーブル投入完了: {len(search_data)}件")
            
            return True
            
        except Exception as e:
            print(f"❌ 本番環境データ投入エラー: {e}")
            return False
    
    def migrate(self) -> bool:
        """完全なマイグレーション処理"""
        print("🔄 開発環境→本番環境データマイグレーション開始")
        print("=" * 60)
        
        # 現在のデータ数確認
        dev_counts = self.get_dev_data_count()
        prd_counts = self.get_prd_data_count()
        
        print(f"📊 マイグレーション前のデータ数:")
        print(f"   開発環境: Whiskeys={dev_counts['whiskeys_count']}, Search={dev_counts['search_count']}")
        print(f"   本番環境: Whiskeys={prd_counts['whiskeys_count']}, Search={prd_counts['search_count']}")
        print()
        
        if dev_counts['whiskeys_count'] == 0 and dev_counts['search_count'] == 0:
            print("⚠️  開発環境にデータがありません。マイグレーションを中止します。")
            return False
        
        # データエクスポート
        exported_data = self.export_dev_data()
        if not exported_data['whiskeys'] and not exported_data['search']:
            print("❌ データエクスポートに失敗しました。")
            return False
        
        # データ投入
        success = self.import_to_production(exported_data)
        if not success:
            print("❌ データ投入に失敗しました。")
            return False
        
        # 投入後のデータ数確認
        prd_counts_after = self.get_prd_data_count()
        print()
        print(f"📊 マイグレーション後のデータ数:")
        print(f"   本番環境: Whiskeys={prd_counts_after['whiskeys_count']}, Search={prd_counts_after['search_count']}")
        
        print()
        print("🎉 開発環境→本番環境データマイグレーション完了!")
        return True


def main():
    """メイン実行関数"""
    migrator = DevToProdMigrator()
    
    success = migrator.migrate()
    
    if success:
        print("\n✅ マイグレーション成功")
        return True
    else:
        print("\n❌ マイグレーション失敗")
        return False


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)