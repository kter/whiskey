#!/usr/bin/env python3
"""
本番環境DynamoDBにテストデータを投入するスクリプト

使用方法:
python scripts/insert_test_data_to_prod.py --count 100
"""

import boto3
import json
import uuid
import argparse
import os
from datetime import datetime
from decimal import Decimal
from typing import List, Dict


class ProductionDataInserter:
    def __init__(self, profile: str = 'prd'):
        """
        本番環境のDynamoDBクライアントを初期化
        
        Args:
            profile: AWSプロファイル名 (default: prd)
        """
        self.session = boto3.Session(profile_name=profile)
        self.dynamodb = self.session.resource('dynamodb', region_name='ap-northeast-1')
        
        # 本番環境のテーブル名
        self.whiskeys_table = self.dynamodb.Table('Whiskeys-prd')
        self.whiskey_search_table = self.dynamodb.Table('WhiskeySearch-prd')
        
        print(f"✅ AWS profile '{profile}' で本番環境DynamoDBに接続")
    
    def generate_test_whiskey_data(self, count: int) -> List[Dict]:
        """
        テスト用のウイスキーデータを生成
        
        Args:
            count: 生成するデータ数
            
        Returns:
            ウイスキーデータのリスト
        """
        print(f"📝 {count}件のテストデータを生成中...")
        
        # 有名なウイスキーの基本データ
        base_whiskeys = [
            {'name': '山崎', 'name_en': 'Yamazaki', 'distillery': 'サントリー', 'distillery_en': 'Suntory', 'region': '日本', 'type': 'Single Malt'},
            {'name': '白州', 'name_en': 'Hakushu', 'distillery': 'サントリー', 'distillery_en': 'Suntory', 'region': '日本', 'type': 'Single Malt'},
            {'name': '響', 'name_en': 'Hibiki', 'distillery': 'サントリー', 'distillery_en': 'Suntory', 'region': '日本', 'type': 'Blended'},
            {'name': 'ジョニーウォーカー ブラックラベル', 'name_en': 'Johnnie Walker Black Label', 'distillery': 'ジョニーウォーカー', 'distillery_en': 'Johnnie Walker', 'region': 'スコットランド', 'type': 'Blended'},
            {'name': 'マッカラン 12年', 'name_en': 'Macallan 12 Year Old', 'distillery': 'マッカラン', 'distillery_en': 'Macallan', 'region': 'スコットランド', 'type': 'Single Malt'},
            {'name': 'グレンフィディック 12年', 'name_en': 'Glenfiddich 12 Year Old', 'distillery': 'グレンフィディック', 'distillery_en': 'Glenfiddich', 'region': 'スコットランド', 'type': 'Single Malt'},
            {'name': 'ラフロイグ 10年', 'name_en': 'Laphroaig 10 Year Old', 'distillery': 'ラフロイグ', 'distillery_en': 'Laphroaig', 'region': 'スコットランド', 'type': 'Single Malt'},
            {'name': 'ジェムソン', 'name_en': 'Jameson', 'distillery': 'ジェムソン', 'distillery_en': 'Jameson', 'region': 'アイルランド', 'type': 'Blended'},
            {'name': 'ジャックダニエル', 'name_en': 'Jack Daniel\'s', 'distillery': 'ジャックダニエル', 'distillery_en': 'Jack Daniel\'s', 'region': 'アメリカ', 'type': 'Tennessee Whiskey'},
            {'name': 'バーボン ウッドフォードリザーブ', 'name_en': 'Woodford Reserve', 'distillery': 'ウッドフォードリザーブ', 'distillery_en': 'Woodford Reserve', 'region': 'アメリカ', 'type': 'Bourbon'},
        ]
        
        variations = ['', '12年', '15年', '18年', '21年', 'ノンヴィンテージ', 'スペシャルエディション', 'リミテッドエディション', 'ディスティラーズエディション']
        
        whiskey_data = []
        now = datetime.now().isoformat()
        
        for i in range(count):
            base = base_whiskeys[i % len(base_whiskeys)]
            variation = variations[i % len(variations)] if i >= len(base_whiskeys) else ''
            
            name = f"{base['name']}{(' ' + variation) if variation else ''}"
            name_en = f"{base['name_en']}{(' ' + variation) if variation else ''}"
            
            whiskey_id = str(uuid.uuid4())
            
            # 基本テーブル用データ
            whiskey_item = {
                'id': whiskey_id,
                'name': name,
                'distillery': base['distillery'],
                'region': base['region'],
                'type': base['type'],
                'description': f"テスト用データ: {name}",
                'confidence': Decimal('0.95'),
                'source': 'test_data',
                'created_at': now,
                'updated_at': now
            }
            
            # 検索テーブル用データ（本番環境のテーブル構造に合わせる）
            search_item = {
                'id': whiskey_id,
                'name': name,  # 日本語名をメインに
                'distillery': base['distillery'],  # 日本語蒸留所名をメイン
                'normalized_name': name.lower().replace(' ', '').replace('　', ''),
                'normalized_distillery': base['distillery'].lower().replace(' ', '').replace('　', ''),
                'region': base['region'],
                'type': base['type'],
                'description': f"テスト用データ: {name}",
                'created_at': now,
                'updated_at': now
            }
            
            whiskey_data.append({
                'whiskey_item': whiskey_item,
                'search_item': search_item
            })
        
        print(f"✅ {len(whiskey_data)}件のテストデータを生成完了")
        return whiskey_data
    
    def insert_data_batch(self, data_list: List[Dict]) -> bool:
        """
        バッチでデータを投入
        
        Args:
            data_list: 投入するデータのリスト
            
        Returns:
            成功したかどうか
        """
        try:
            print(f"🚀 {len(data_list)}件のデータをバッチ投入中...")
            
            # バッチライト用にアイテムを準備
            with self.whiskeys_table.batch_writer() as batch:
                for data in data_list:
                    batch.put_item(Item=data['whiskey_item'])
            
            with self.whiskey_search_table.batch_writer() as batch:
                for data in data_list:
                    batch.put_item(Item=data['search_item'])
            
            print("✅ バッチ投入が正常に完了しました")
            return True
            
        except Exception as e:
            print(f"❌ バッチ投入中にエラーが発生: {e}")
            return False
    
    def verify_data_insertion(self, expected_count: int) -> bool:
        """
        データ投入の検証
        
        Args:
            expected_count: 期待されるデータ数
            
        Returns:
            検証が成功したかどうか
        """
        try:
            print("🔍 データ投入の検証中...")
            
            # 基本テーブルのアイテム数確認
            whiskeys_response = self.whiskeys_table.scan(Select='COUNT')
            whiskeys_count = whiskeys_response['Count']
            
            # 検索テーブルのアイテム数確認
            search_response = self.whiskey_search_table.scan(Select='COUNT')
            search_count = search_response['Count']
            
            print(f"📊 データ投入結果:")
            print(f"   Whiskeys-prd: {whiskeys_count}件")
            print(f"   WhiskeySearch-prd: {search_count}件")
            print(f"   期待値: {expected_count}件")
            
            if whiskeys_count >= expected_count and search_count >= expected_count:
                print("✅ データ投入の検証が成功しました")
                return True
            else:
                print("❌ 期待されるデータ数に達していません")
                return False
                
        except Exception as e:
            print(f"❌ 検証中にエラーが発生: {e}")
            return False
    
    def get_current_data_count(self) -> Dict[str, int]:
        """現在のデータ数を取得"""
        try:
            whiskeys_response = self.whiskeys_table.scan(Select='COUNT')
            search_response = self.whiskey_search_table.scan(Select='COUNT')
            
            return {
                'whiskeys_table': whiskeys_response['Count'],
                'search_table': search_response['Count']
            }
        except Exception as e:
            print(f"❌ データ数取得中にエラー: {e}")
            return {'whiskeys_table': 0, 'search_table': 0}
    
    def clear_all_data(self) -> bool:
        """
        ⚠️ 危険: 全データを削除
        
        Returns:
            削除が成功したかどうか
        """
        try:
            print("⚠️  全データを削除中...")
            
            # 全アイテムをスキャンして削除
            response = self.whiskeys_table.scan()
            with self.whiskeys_table.batch_writer() as batch:
                for item in response['Items']:
                    batch.delete_item(Key={'id': item['id']})
            
            response = self.whiskey_search_table.scan()
            with self.whiskey_search_table.batch_writer() as batch:
                for item in response['Items']:
                    batch.delete_item(Key={'id': item['id']})
            
            print("✅ 全データの削除が完了しました")
            return True
            
        except Exception as e:
            print(f"❌ データ削除中にエラー: {e}")
            return False


def main():
    """メイン関数"""
    parser = argparse.ArgumentParser(description='本番環境DynamoDBテストデータ投入')
    parser.add_argument('--count', type=int, default=100, help='投入するデータ数 (default: 100)')
    parser.add_argument('--profile', type=str, default='prd', help='AWSプロファイル名 (default: prd)')
    parser.add_argument('--clear', action='store_true', help='既存データを全削除')
    parser.add_argument('--verify-only', action='store_true', help='データ数の確認のみ')
    
    args = parser.parse_args()
    
    print("🔥 本番環境DynamoDBテストデータ投入スクリプト")
    print("=" * 50)
    
    # データ投入クラス初期化
    try:
        inserter = ProductionDataInserter(profile=args.profile)
    except Exception as e:
        print(f"❌ 初期化エラー: {e}")
        return False
    
    # 現在のデータ数確認
    current_counts = inserter.get_current_data_count()
    print(f"📊 現在のデータ数:")
    print(f"   Whiskeys-prd: {current_counts['whiskeys_table']}件")
    print(f"   WhiskeySearch-prd: {current_counts['search_table']}件")
    
    if args.verify_only:
        return True
    
    if args.clear:
        print("\n⚠️  全データ削除を実行しますか? (yes/no): ", end="")
        confirmation = input()
        if confirmation.lower() == 'yes':
            success = inserter.clear_all_data()
            if success:
                print("✅ データクリアが完了しました")
            return success
        else:
            print("❌ 削除をキャンセルしました")
            return False
    
    # テストデータ生成
    test_data = inserter.generate_test_whiskey_data(args.count)
    
    # データ投入
    success = inserter.insert_data_batch(test_data)
    
    if success:
        # 検証
        verification_success = inserter.verify_data_insertion(args.count)
        if verification_success:
            print("\n🎉 本番環境テストデータ投入が正常に完了しました!")
            return True
        else:
            print("\n❌ データ投入の検証に失敗しました")
            return False
    else:
        print("\n❌ データ投入に失敗しました")
        return False


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)