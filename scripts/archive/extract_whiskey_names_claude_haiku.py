#!/usr/bin/env python3
"""
Claude 3.5 Haikuを使用したウイスキー名抽出
Nova Proとのコスト・品質比較用
"""

import json
import boto3
import time
import logging
import argparse
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import re
import os

class ClaudeHaikuWhiskeyExtractor:
    def __init__(self):
        """Claude 3.5 Haiku初期化"""
        self.region = 'ap-northeast-1'
        self.model_id = "anthropic.claude-3-haiku-20240307-v1:0"
        
        # Claude Haiku最適化設定
        self.batch_size = 15  # Haikuは高速なので増量
        self.api_rate_limit = 1.5  # レート制限緩和
        self.max_retries = 3
        
        # ログ設定
        self.setup_logging()
        
        try:
            self.bedrock = boto3.client('bedrock-runtime', region_name=self.region)
            self.logger.info(f"Bedrock初期化完了 - Region: {self.region}, Model: {self.model_id}")
        except Exception as e:
            self.logger.error(f"Bedrock初期化エラー: {e}")
            raise

    def setup_logging(self):
        """ログ設定"""
        log_file = "claude_haiku_whiskey_extract.log"
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file, encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)

    def create_extraction_prompt(self, product_names: List[str]) -> str:
        """Claude Haiku用プロンプト作成"""
        products_text = "\n".join([f"{i+1}. {name}" for i, name in enumerate(product_names)])
        
        prompt = f"""楽天市場の商品名からウイスキー情報を抽出してください。

商品名リスト:
{products_text}

以下のJSON形式で結果を返してください：

{{
  "results": [
    {{
      "product_name": "元の商品名",
      "extracted_whiskeys": [
        {{
          "name": "抽出されたウイスキー名",
          "distillery": "蒸溜所名（英語）",
          "confidence": 0.95,
          "type": "Single Malt/Blended/Bourbon等",
          "region": "Scotland/Japan/Ireland等"
        }}
      ]
    }}
  ]
}}

抽出ルール:
1. ウイスキー製品のみを対象とする
2. 複数のウイスキーが含まれる場合はすべて抽出
3. confidenceは抽出精度(0.0-1.0)
4. 蒸溜所名は可能な限り英語表記
5. 不明な項目は空文字列

有効なJSON形式で返してください。"""

        return prompt

    def call_bedrock_api(self, prompt: str) -> Optional[str]:
        """Claude Haiku API呼び出し"""
        request_body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 4000,
            "temperature": 0.1,
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        }

        try:
            response = self.bedrock.invoke_model(
                modelId=self.model_id,
                body=json.dumps(request_body)
            )
            
            response_body = json.loads(response['body'].read())
            return response_body['content'][0]['text']
            
        except Exception as e:
            self.logger.error(f"Bedrock呼び出しエラー: {e}")
            return None

    def extract_json_from_response(self, response_text: str) -> Optional[Dict]:
        """レスポンスからJSON抽出（Claude Haiku最適化）"""
        if not response_text:
            return None

        # Claude系は通常クリーンなJSONを返すが、念のため複数パターンで試行
        json_patterns = [
            r'\{[\s\S]*\}',  # 基本的なJSON
            r'```json\n([\s\S]*?)\n```',  # コードブロック形式
            r'```\n([\s\S]*?)\n```'  # 一般的なコードブロック
        ]

        for pattern in json_patterns:
            matches = re.findall(pattern, response_text)
            for match in matches:
                try:
                    if isinstance(match, tuple):
                        json_text = match[0] if match else response_text
                    else:
                        json_text = match
                    
                    # Unicodeエラー処理
                    json_text = json_text.encode('utf-8', errors='ignore').decode('utf-8')
                    
                    return json.loads(json_text)
                except json.JSONDecodeError:
                    continue

        # 直接パース試行
        try:
            return json.loads(response_text)
        except json.JSONDecodeError as e:
            self.logger.warning(f"JSON解析失敗: {e}")
            return None

    def process_batch(self, product_names: List[str]) -> List[Dict]:
        """バッチ処理（Claude Haiku最適化）"""
        prompt = self.create_extraction_prompt(product_names)
        
        for attempt in range(self.max_retries):
            response_text = self.call_bedrock_api(prompt)
            
            if response_text:
                parsed_result = self.extract_json_from_response(response_text)
                
                if parsed_result and 'results' in parsed_result:
                    results = parsed_result['results']
                    whiskey_count = sum(len(r.get('extracted_whiskeys', [])) for r in results)
                    self.logger.info(f"バッチ結果: {len(product_names)}件中 {whiskey_count}件がウイスキー")
                    return results
                else:
                    self.logger.warning(f"JSON解析失敗（試行 {attempt + 1}）")
                    if attempt < self.max_retries - 1:
                        time.sleep(self.api_rate_limit)
            else:
                self.logger.warning(f"API呼び出し失敗（試行 {attempt + 1}）")
                if attempt < self.max_retries - 1:
                    time.sleep(self.api_rate_limit * 2)

        self.logger.error("バッチ処理完全失敗")
        return []

    def process_file(self, input_file: str, dry_run: bool = False) -> str:
        """ファイル処理メイン"""
        self.logger.info(f"ファイル処理開始: {input_file}")
        
        # 入力ファイル読み込み
        with open(input_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        product_names = data.get('product_names', [])
        source_metadata = data.get('metadata', {})
        
        self.logger.info(f"読み込み完了: {len(product_names)}件の商品名")
        
        if dry_run:
            self.logger.info("DRY RUN: 実際の処理は行いません")
            return ""

        # バッチ処理実行
        start_time = datetime.now()
        self.logger.info(f"ウイスキー名抽出開始: {len(product_names)}件")
        
        all_results = []
        total_batches = (len(product_names) + self.batch_size - 1) // self.batch_size
        
        for i in range(0, len(product_names), self.batch_size):
            batch_num = i // self.batch_size + 1
            batch = product_names[i:i + self.batch_size]
            
            self.logger.info(f"バッチ {batch_num}/{total_batches} 処理中: {len(batch)}件")
            
            batch_results = self.process_batch(batch)
            all_results.extend(batch_results)
            
            # レート制限
            if batch_num < total_batches:
                time.sleep(self.api_rate_limit)

        # 結果保存
        end_time = datetime.now()
        processing_duration = end_time - start_time
        
        output_data = {
            "metadata": {
                "processing_time": end_time.isoformat(),
                "processing_duration": str(processing_duration),
                "input_file": input_file,
                "source_metadata": source_metadata,
                "total_processed": len(product_names),
                "total_results": len(all_results),
                "model_used": self.model_id,
                "data_type": "whiskey_extraction_results",
                "extraction_method": "claude_haiku"
            },
            "results": all_results
        }

        # 統計計算
        total_whiskeys = sum(len(r.get('extracted_whiskeys', [])) for r in all_results)
        high_confidence = sum(
            len([w for w in r.get('extracted_whiskeys', []) if w.get('confidence', 0) >= 0.9])
            for r in all_results
        )

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = f"claude_haiku_extraction_results_{timestamp}.json"
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)

        self.logger.info("=== 処理完了 ===")
        self.logger.info(f"実行時間: {processing_duration}")
        self.logger.info(f"処理件数: {len(product_names)}件")
        self.logger.info(f"ウイスキー認識: {total_whiskeys}件")
        self.logger.info(f"高信頼度 (≥0.9): {high_confidence}件")
        self.logger.info(f"結果ファイル: {output_file}")

        return output_file


def main():
    """メイン実行関数"""
    parser = argparse.ArgumentParser(description='Claude 3.5 Haikuによるウイスキー名抽出')
    parser.add_argument('--input-file', required=True, help='楽天商品名JSONファイル')
    parser.add_argument('--dry-run', action='store_true', help='ドライラン（実際の処理なし）')
    
    args = parser.parse_args()
    
    if not os.path.exists(args.input_file):
        print(f"ERROR: ファイルが見つかりません: {args.input_file}")
        return 1
    
    try:
        extractor = ClaudeHaikuWhiskeyExtractor()
        result_file = extractor.process_file(args.input_file, args.dry_run)
        
        if result_file:
            print(f"SUCCESS: Claude Haiku抽出完了 - {result_file}")
        else:
            print("INFO: Dry run completed")
        
        return 0
        
    except Exception as e:
        print(f"ERROR: 処理エラー: {e}")
        return 1


if __name__ == "__main__":
    exit(main())