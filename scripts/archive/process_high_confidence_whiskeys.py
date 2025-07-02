#!/usr/bin/env python3
"""
高信頼度ウイスキーデータの抽出・変換処理
Bedrock Nova Proの結果からconfidence ≥ 0.9のデータのみを抽出し、
DynamoDB投入用のフォーマットに変換する
"""

import json
import uuid
from datetime import datetime
from typing import Dict, List, Optional
import os

class HighConfidenceWhiskeyProcessor:
    def __init__(self):
        self.confidence_threshold = 0.9
        self.output_file = None
        
    def load_bedrock_results(self, file_path: str) -> List[Dict]:
        """Bedrock Nova Proの結果ファイルを読み込み"""
        print(f"Bedrock結果ファイル読み込み: {file_path}")
        
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        results = data.get('results', [])
        print(f"総結果数: {len(results)}件")
        return results
    
    def filter_high_confidence(self, results: List[Dict]) -> List[Dict]:
        """confidence ≥ 0.9のデータのみを抽出"""
        high_confidence = []
        
        for result in results:
            extracted_whiskeys = result.get('extracted_whiskeys', [])
            
            for whiskey in extracted_whiskeys:
                confidence = whiskey.get('confidence', 0.0)
                if confidence >= self.confidence_threshold:
                    # 元の商品名情報も保持
                    whiskey_data = whiskey.copy()
                    whiskey_data['rakuten_product_name'] = result.get('product_name', '')
                    high_confidence.append(whiskey_data)
        
        print(f"高信頼度データ (confidence ≥ {self.confidence_threshold}): {len(high_confidence)}件")
        return high_confidence
    
    def convert_to_dynamodb_format(self, whiskey_data: Dict) -> Dict:
        """DynamoDB投入用フォーマットに変換"""
        now = datetime.now().isoformat()
        entry_id = str(uuid.uuid4())
        
        # 必須フィールドのバリデーション
        name = whiskey_data.get('name', '').strip()
        distillery = whiskey_data.get('distillery', '').strip()
        
        if not name:
            raise ValueError(f"ウイスキー名が空です: {whiskey_data}")
        
        item = {
            'id': entry_id,
            'name': name,
            'distillery': distillery,
            'normalized_name': self._normalize_text(name),
            'normalized_distillery': self._normalize_text(distillery),
            'confidence': float(whiskey_data.get('confidence', 0.0)),
            'source': 'rakuten_bedrock',
            'extraction_method': 'nova_pro',
            'rakuten_product_name': whiskey_data.get('rakuten_product_name', ''),
            'type': whiskey_data.get('type', ''),
            'region': whiskey_data.get('region', ''),
            'created_at': now,
            'updated_at': now
        }
        
        return item
    
    def _normalize_text(self, text: str) -> str:
        """テキストを検索用に正規化（日本語専用）"""
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
    
    def remove_duplicates(self, whiskey_list: List[Dict]) -> List[Dict]:
        """重複除去（正規化された名前+蒸溜所でチェック）"""
        seen = set()
        unique_whiskeys = []
        
        for whiskey in whiskey_list:
            key = (whiskey['normalized_name'], whiskey['normalized_distillery'])
            if key not in seen:
                seen.add(key)
                unique_whiskeys.append(whiskey)
            else:
                print(f"重複除去: {whiskey['name']} - {whiskey['distillery']}")
        
        print(f"重複除去後: {len(unique_whiskeys)}件 (除去数: {len(whiskey_list) - len(unique_whiskeys)})")
        return unique_whiskeys
    
    def save_processed_data(self, processed_data: List[Dict], output_file: str = None) -> str:
        """処理済みデータを保存"""
        if not output_file:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = f"high_confidence_whiskeys_{timestamp}.json"
        
        output_data = {
            "metadata": {
                "processing_time": datetime.now().isoformat(),
                "total_records": len(processed_data),
                "confidence_threshold": self.confidence_threshold,
                "source": "rakuten_bedrock_nova_pro"
            },
            "whiskeys": processed_data
        }
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)
        
        print(f"処理済みデータを保存: {output_file}")
        return output_file
    
    def process_bedrock_results(self, bedrock_file: str, output_file: str = None) -> str:
        """メイン処理フロー"""
        print("=== 高信頼度ウイスキーデータ処理開始 ===")
        
        # 1. Bedrock結果読み込み
        results = self.load_bedrock_results(bedrock_file)
        
        # 2. 高信頼度データ抽出
        high_confidence_whiskeys = self.filter_high_confidence(results)
        
        if not high_confidence_whiskeys:
            print("ERROR: 高信頼度データが見つかりませんでした")
            return None
        
        # 3. DynamoDB形式に変換
        print("DynamoDB形式に変換中...")
        processed_whiskeys = []
        
        for whiskey_data in high_confidence_whiskeys:
            try:
                converted = self.convert_to_dynamodb_format(whiskey_data)
                processed_whiskeys.append(converted)
            except Exception as e:
                print(f"変換エラー: {e}")
                continue
        
        # 4. 重複除去
        unique_whiskeys = self.remove_duplicates(processed_whiskeys)
        
        # 5. 結果保存
        output_file = self.save_processed_data(unique_whiskeys, output_file)
        
        print("=== 処理完了 ===")
        print(f"最終データ数: {len(unique_whiskeys)}件")
        print(f"出力ファイル: {output_file}")
        
        return output_file

def main():
    """メイン実行関数"""
    import sys
    
    if len(sys.argv) < 2:
        print("使用方法: python process_high_confidence_whiskeys.py <bedrock_results_file> [output_file]")
        sys.exit(1)
    
    bedrock_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None
    
    if not os.path.exists(bedrock_file):
        print(f"ERROR: ファイルが見つかりません: {bedrock_file}")
        sys.exit(1)
    
    processor = HighConfidenceWhiskeyProcessor()
    result_file = processor.process_bedrock_results(bedrock_file, output_file)
    
    if result_file:
        print(f"SUCCESS: 高信頼度データ処理完了 - {result_file}")
    else:
        print("ERROR: 処理に失敗しました")
        sys.exit(1)

if __name__ == "__main__":
    main()