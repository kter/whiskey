#!/usr/bin/env python3
"""
高信頼度ウイスキーデータをDynamoDBに投入
- confidence ≥ 0.9のみ
- 重複排除機能
- 日本語専用スキーマ対応
"""

import json
import sys
import os
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Set, Optional

# プロジェクトルートをパスに追加
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'lambda', 'whiskeys-search', 'python'))

from whiskey_search_service import WhiskeySearchService


class WhiskeyDatabaseInserter:
    def __init__(self):
        # 環境変数とAWSプロファイルの検証
        environment = os.getenv('ENVIRONMENT')
        aws_profile = os.getenv('AWS_PROFILE')
        
        if not environment:
            raise ValueError("ENVIRONMENT環境変数が設定されていません。ENVIRONMENT=dev または ENVIRONMENT=prd を設定してください。")
        
        # 環境に応じたプロファイルを自動設定
        if not aws_profile:
            if environment == 'prd':
                os.environ['AWS_PROFILE'] = 'prd'
                print(f"AWS_PROFILE を自動設定: prd")
            elif environment == 'dev':
                os.environ['AWS_PROFILE'] = 'dev'
                print(f"AWS_PROFILE を自動設定: dev")
            else:
                raise ValueError(f"不明な環境: {environment}")
        
        # プロファイルが設定されたセッションを作成
        try:
            import boto3
            session = boto3.Session(profile_name=os.environ['AWS_PROFILE'])
            # 認証情報の確認
            sts = session.client('sts')
            identity = sts.get_caller_identity()
            print(f"AWS アカウント: {identity['Account']}")
            print(f"AWS ARN: {identity['Arn']}")
        except Exception as e:
            raise ValueError(f"AWS認証エラー: {e}")
        
        self.db_service = WhiskeySearchService()
        self.processed_count = 0
        self.inserted_count = 0
        self.duplicate_count = 0
        
    def normalize_text(self, text: str) -> str:
        """テキストを検索用に正規化（DynamoDBサービスと同一）"""
        if not text:
            return ''
        
        # 小文字に変換、スペースを除去
        normalized = text.lower().replace(' ', '').replace('　', '')
        
        # カタカナをひらがなに変換
        katakana_to_hiragana = str.maketrans(
            'アイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホマミムメモヤユヨラリルレロワヲン',
            'あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろわをん'
        )
        normalized = normalized.translate(katakana_to_hiragana)
        
        return normalized

    def load_extraction_results(self, file_path: str) -> List[Dict]:
        """Bedrock抽出結果を読み込み"""
        print(f"抽出結果ファイル読み込み: {file_path}")
        
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # ファイル形式を判定
        if 'results' in data:
            # Nova Pro/Claude Sonnet形式
            results = []
            for item in data['results']:
                extracted_whiskeys = item.get('extracted_whiskeys', [])
                for whiskey in extracted_whiskeys:
                    # whiskeyオブジェクトのコピーを作成して、rakuten_product_nameを追加
                    whiskey_data = {
                        'name': whiskey.get('name', ''),
                        'distillery': whiskey.get('distillery', ''),
                        'confidence': whiskey.get('confidence', 0.0),
                        'rakuten_product_name': item.get('product_name', ''),
                        'type': whiskey.get('type', ''),
                        'region': whiskey.get('region', '')
                    }
                    results.append(whiskey_data)
            return results
        elif 'extraction_results' in data:
            # 旧形式
            results = []
            for item in data['extraction_results']:
                if item.get('is_whiskey', False):
                    result = {
                        'name': item.get('whiskey_name', ''),
                        'distillery': item.get('distillery', ''),
                        'confidence': item.get('confidence', 0.0),
                        'rakuten_product_name': item.get('original_name', ''),
                        'type': '',
                        'region': ''
                    }
                    results.append(result)
            return results
        else:
            raise ValueError(f"不明なファイル形式: {file_path}")

    def extract_all_whiskeys(self, results: List[Dict]) -> List[Dict]:
        """抽出結果からすべてのウイスキーを展開"""
        all_whiskeys = []
        
        for result in results:
            extracted_whiskeys = result.get('extracted_whiskeys', [])
            for whiskey in extracted_whiskeys:
                whiskey['rakuten_product_name'] = result.get('product_name', '')
                all_whiskeys.append(whiskey)
        
        print(f"抽出済みウイスキー総数: {len(all_whiskeys)}件")
        return all_whiskeys

    def remove_duplicates(self, whiskey_list: List[Dict]) -> List[Dict]:
        """重複除去（完全一致のみ除去、年数等のバリエーションは残す）"""
        seen_keys: Set[str] = set()
        unique_whiskeys = []
        
        for whiskey in whiskey_list:
            # None値のチェックを追加
            name = whiskey.get('name', '')
            if name is None:
                name = ''
            name = name.strip()
            
            distillery = whiskey.get('distillery', '')
            if distillery is None:
                distillery = ''
            distillery = distillery.strip()
            
            if not name:
                print(f"空のウイスキー名をスキップ: {whiskey}")
                continue
            
            # 重複チェック用キー（完全一致のみ）
            # 正規化はせず、元の名前をそのまま使用（大文字小文字のみ統一）
            duplicate_key = f"{name.lower()}#{distillery.lower()}"
            
            if duplicate_key not in seen_keys:
                seen_keys.add(duplicate_key)
                unique_whiskeys.append(whiskey)
            else:
                self.duplicate_count += 1
                print(f"重複除去: {name} - {distillery}")
        
        print(f"重複除去後: {len(unique_whiskeys)}件 (除去数: {self.duplicate_count})")
        return unique_whiskeys

    def validate_and_clean_data(self, whiskey_list: List[Dict]) -> List[Dict]:
        """データ検証と前処理クリーニング"""
        clean_whiskeys = []
        
        for i, whiskey in enumerate(whiskey_list):
            try:
                # None値のチェックを追加
                name = whiskey.get('name', '')
                if name is None:
                    name = ''
                name = name.strip()
                
                distillery = whiskey.get('distillery', '')
                if distillery is None:
                    distillery = ''
                distillery = distillery.strip()
                
                confidence = Decimal(str(whiskey.get('confidence', 0.0)))
                
                # 基本バリデーション
                if not name:
                    print(f"空のウイスキー名をスキップ: {whiskey}")
                    continue
                    
                # データクリーニング（DynamoDB GSI制約対応）
                # 空の蒸溜所名は"Unknown"に変換（GSIのキー制約により空文字列は不可）
                if not distillery:
                    distillery = "Unknown"
                    
                cleaned_whiskey = {
                    'name': name,
                    'distillery': distillery,
                    'confidence': confidence,
                    'rakuten_product_name': whiskey.get('rakuten_product_name', ''),
                    'type': whiskey.get('type', ''),
                    'region': whiskey.get('region', '')
                }
                
                clean_whiskeys.append(cleaned_whiskey)
                
            except Exception as e:
                print(f"データクリーニングエラー (インデックス {i}): {e}")
                print(f"問題のあるデータ: {whiskey}")
                continue
        
        print(f"データクリーニング後: {len(clean_whiskeys)}件")
        return clean_whiskeys

    def convert_to_db_format(self, whiskey_data: Dict) -> Dict:
        """DynamoDB投入用フォーマットに変換"""
        import uuid
        
        entry_id = str(uuid.uuid4())
        now = datetime.now().isoformat()
        
        # None値のチェックを追加
        name = whiskey_data.get('name', '')
        if name is None:
            name = ''
        name = name.strip()
        
        distillery = whiskey_data.get('distillery', '')
        if distillery is None:
            distillery = ''
        distillery = distillery.strip()
        
        item = {
            'id': entry_id,
            'name': name,
            'distillery': distillery,
            'normalized_name': self.normalize_text(name),
            'normalized_distillery': self.normalize_text(distillery),
            'confidence': Decimal(str(whiskey_data.get('confidence', 0.0))),
            'source': 'rakuten_bedrock',
            'extraction_method': 'claude_sonnet_4',
            'rakuten_product_name': whiskey_data.get('rakuten_product_name', ''),
            'type': whiskey_data.get('type', ''),
            'region': whiskey_data.get('region', ''),
            'created_at': now,
            'updated_at': now
        }
        
        return item

    def insert_to_dynamodb(self, whiskey_list: List[Dict]) -> bool:
        """DynamoDBへの一括投入"""
        if not whiskey_list:
            print("投入するデータがありません")
            return True
        
        # フォーマット変換
        db_items = []
        for whiskey in whiskey_list:
            try:
                db_item = self.convert_to_db_format(whiskey)
                db_items.append(db_item)
            except Exception as e:
                print(f"フォーマット変換エラー: {e}")
                continue
        
        # DynamoDB投入
        print(f"DynamoDB投入開始: {len(db_items)}件")
        success_count = self.db_service.bulk_insert_whiskeys(db_items)
        
        self.inserted_count = success_count
        print(f"DynamoDB投入完了: {success_count}/{len(db_items)}件")
        
        return success_count == len(db_items)

    def process_file(self, input_file: str) -> Dict:
        """メイン処理フロー（重複排除をDB投入前に実行）"""
        print("=== ウイスキーデータDynamoDB投入開始 ===")
        print(f"設定: 前処理重複排除")  # confidence関連の記述を削除
        
        try:
            # 1. 抽出結果読み込み（すでに展開済み）
            all_whiskeys = self.load_extraction_results(input_file)
            print(f"読み込み完了: {len(all_whiskeys)}件のウイスキー")
            self.processed_count = len(all_whiskeys)
            
            # 3. データ検証とクリーニング
            clean_whiskeys = self.validate_and_clean_data(all_whiskeys)
            # self.low_confidence_count の計算を削除または修正
            # self.low_confidence_count = len(all_whiskeys) - len(clean_whiskeys)
            
            # 4. 重複除去（DB投入前）
            unique_whiskeys = self.remove_duplicates(clean_whiskeys)
            
            # 5. DynamoDB投入
            success = self.insert_to_dynamodb(unique_whiskeys)
            
            # 6. 統計情報
            stats = {
                'success': success,
                'processed_count': self.processed_count,
                'clean_count': len(clean_whiskeys),  # high_confidence_countをclean_countに変更
                'duplicates_removed': self.duplicate_count,
                'inserted_count': self.inserted_count,
                # 'confidence_threshold': self.confidence_threshold  # この行を削除
            }
            
            print("=== 処理完了 ===")
            print(f"総ウイスキー数: {stats['processed_count']}件")
            print(f"クリーニング後: {stats['clean_count']}件")  # 表示を変更
            print(f"重複除去: {stats['duplicates_removed']}件")
            print(f"DB投入: {stats['inserted_count']}件")
            print(f"最終成功率: {stats['inserted_count']}/{stats['clean_count']}")
            
            return stats
            
        except Exception as e:
            print(f"エラー: {e}")
            return {
                'success': False,
                'error': str(e),
                'processed_count': self.processed_count,
                'inserted_count': self.inserted_count
            }

    def get_database_statistics(self) -> Dict:
        """DynamoDB統計情報取得"""
        try:
            stats = self.db_service.get_whiskey_statistics()
            print("=== DynamoDB統計 ===")
            print(f"総データ数: {stats.get('total_count', 0)}")
            print(f"高信頼度数: {stats.get('high_confidence_count', 0)}")
            print("信頼度分布:", stats.get('confidence_distribution', {}))
            print("ソース分布:", stats.get('source_distribution', {}))
            return stats
        except Exception as e:
            print(f"統計取得エラー: {e}")
            return {}


def main():
    """メイン実行関数"""
    if len(sys.argv) < 2:
        print("使用方法: python insert_whiskeys_to_dynamodb.py <extraction_results_file>")
        print("オプション:")
        print("  --stats : DynamoDB統計情報のみ表示")
        print("  --clear : 全データ削除（注意）")
        sys.exit(1)
    
    inserter = WhiskeyDatabaseInserter()
    
    # オプション処理
    if "--stats" in sys.argv:
        inserter.get_database_statistics()
        return
    
    if "--clear" in sys.argv:
        print("WARNING: 全ウイスキーデータを削除します")
        success = inserter.db_service.delete_all_whiskeys()
        print(f"削除結果: {'成功' if success else '失敗'}")
        return
    
    input_file = sys.argv[1]
    
    if not os.path.exists(input_file):
        print(f"ERROR: ファイルが見つかりません: {input_file}")
        sys.exit(1)
    
    # メイン処理実行
    result = inserter.process_file(input_file)
    
    if result['success']:
        print("SUCCESS: DynamoDB投入が正常に完了しました")
        # 最終統計表示
        inserter.get_database_statistics()
    else:
        print("ERROR: 処理に失敗しました")
        sys.exit(1)


if __name__ == "__main__":
    main()