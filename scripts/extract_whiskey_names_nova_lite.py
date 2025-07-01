#!/usr/bin/env python3
"""
Nova Liteを使用したウイスキー名抽出（超コスト重視）
- 最低コストでの大量処理
- エラー許容度高め
- 品質は後処理で補完
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

class NovaLiteWhiskeyExtractor:
    def __init__(self):
        """Nova Lite初期化（コスト最適化）"""
        self.region = 'ap-northeast-1'
        self.model_id = "amazon.nova-lite-v1:0"
        
        # Nova Lite最適化設定（スピード重視）
        self.batch_size = 20  # 大きなバッチサイズ
        self.api_rate_limit = 1.0  # 高速処理
        self.max_retries = 2  # リトライ回数削減
        
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
        log_file = "nova_lite_whiskey_extract.log"
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
        """Nova Lite用シンプルプロンプト"""
        products_text = "\n".join([f"{i+1}. {name}" for i, name in enumerate(product_names)])
        
        # Nova Lite用に非常にシンプルなプロンプト
        prompt = f"""Extract whiskey information from the following Japanese product names:

{products_text}

Return JSON only:
{{
  "results": [
    {{
      "product_name": "actual product name",
      "extracted_whiskeys": [
        {{
          "name": "whiskey name",
          "distillery": "distillery name",
          "confidence": 0.9
        }}
      ]
    }}
  ]
}}

Only extract actual whiskey products."""

        return prompt

    def call_bedrock_api(self, prompt: str) -> Optional[str]:
        """Nova Lite API呼び出し（正しいフォーマット）"""
        request_body = {
            "messages": [
                {
                    "role": "user", 
                    "content": [{"text": prompt}]
                }
            ],
            "inferenceConfig": {
                "max_new_tokens": 3000,
                "temperature": 0.2
            }
        }

        try:
            response = self.bedrock.invoke_model(
                modelId=self.model_id,
                body=json.dumps(request_body)
            )
            
            response_body = json.loads(response['body'].read())
            response_text = response_body['output']['message']['content'][0]['text']
            
            # デバッグ用: レスポンス内容をログ出力
            self.logger.info(f"Nova Lite レスポンス (最初の1000文字): {response_text[:1000]}")
            
            # 完全なレスポンスをファイルに保存（デバッグ用）
            with open(f"debug_response_{datetime.now().strftime('%H%M%S')}.txt", 'w', encoding='utf-8') as f:
                f.write(response_text)
            
            return response_text
            
        except Exception as e:
            self.logger.error(f"Bedrock呼び出しエラー: {e}")
            return None

    def extract_json_from_response(self, response_text: str) -> Optional[Dict]:
        """JSON抽出（Nova Lite対応・エラー許容）"""
        if not response_text:
            return None

        # Nova Liteは```json```でマークダウン形式で返す
        # 複数のJSON抽出パターン（順序重要：具体的なものから試す）
        json_patterns = [
            r'```json\s*\n([\s\S]*?)\n```',  # マークダウンのjsonブロック
            r'```\s*\n([\s\S]*?)\n```',      # 一般的なマークダウンブロック
            r'\{[\s\S]*\}',                   # 最後の手段：全体のJSON
        ]

        for pattern in json_patterns:
            matches = re.findall(pattern, response_text, re.DOTALL)
            for match in matches:
                try:
                    if isinstance(match, tuple):
                        json_text = match[0] if match else response_text
                    else:
                        json_text = match
                    
                    # 前後の空白を除去
                    json_text = json_text.strip()
                    
                    # 不完全なJSONの修復（Nova Liteはトークン制限で切れることがある）
                    if not json_text.endswith('}'):
                        # 最後の完整な要素まで戻る
                        last_complete = json_text.rfind('}')
                        if last_complete > 0:
                            # 最後の完整な要素の直後までで切る
                            json_text = json_text[:last_complete + 1]
                            # resultsの配列とオブジェクト全体を閉じる
                            if not json_text.endswith(']}'):
                                json_text += ']}'
                    
                    # デバッグ用: 修復したJSON（最初の300文字）をログ出力
                    self.logger.info(f"修復済みJSON (最初の300文字): {json_text[:300]}")
                    
                    # JSONパース試行
                    parsed = json.loads(json_text)
                    
                    # Unicode文字列をデコード（Nova Liteはエスケープシーケンスで返すことがある）
                    if isinstance(parsed, dict) and 'results' in parsed:
                        for result in parsed['results']:
                            if 'product_name' in result and isinstance(result['product_name'], str):
                                try:
                                    # Unicode エスケープシーケンスをデコード
                                    result['product_name'] = result['product_name'].encode('utf-8').decode('unicode_escape')
                                except:
                                    pass  # デコードに失敗しても元の文字列を保持
                            
                            if 'extracted_whiskeys' in result:
                                for whiskey in result['extracted_whiskeys']:
                                    for key in ['name', 'distillery']:
                                        if key in whiskey and isinstance(whiskey[key], str):
                                            try:
                                                whiskey[key] = whiskey[key].encode('utf-8').decode('unicode_escape')
                                            except:
                                                pass
                        
                        self.logger.info(f"JSON解析成功: {len(parsed['results'])}件の結果")
                        return parsed
                    else:
                        self.logger.warning("JSONフォーマット不正（resultsキーなし）")
                        continue
                        
                except json.JSONDecodeError as e:
                    self.logger.warning(f"JSON解析エラー: {e}")
                    continue

        # 緊急時：最低限のダミーデータ作成
        self.logger.warning("JSON解析完全失敗 - ダミーデータ生成")
        return {"results": []}

    def process_batch(self, product_names: List[str]) -> List[Dict]:
        """バッチ処理（Nova Lite高速版）"""
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
                    time.sleep(self.api_rate_limit)

        # Nova Liteはエラーを許容し、空の結果を返す
        self.logger.warning("バッチ処理失敗 - 空結果で継続")
        return []

    def process_file(self, input_file: str, dry_run: bool = False) -> str:
        """ファイル処理（Nova Lite高速版）"""
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

        # バッチ処理実行（高速）
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
            
            # 最小限のレート制限
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
                "extraction_method": "nova_lite"
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
        output_file = f"nova_lite_extraction_results_{timestamp}.json"
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)

        self.logger.info("=== 処理完了 ===")
        self.logger.info(f"実行時間: {processing_duration}")
        self.logger.info(f"処理件数: {len(product_names)}件")
        self.logger.info(f"ウイスキー認識: {total_whiskeys}件")
        self.logger.info(f"高信頼度 (≥0.9): {high_confidence}件")
        self.logger.info(f"成功率: {len([r for r in all_results if r])}/{len(all_results)*20:.0f} バッチ")
        self.logger.info(f"結果ファイル: {output_file}")

        return output_file


def main():
    """メイン実行関数"""
    parser = argparse.ArgumentParser(description='Nova Liteによるウイスキー名抽出（超コスト重視）')
    parser.add_argument('--input-file', required=True, help='楽天商品名JSONファイル')
    parser.add_argument('--dry-run', action='store_true', help='ドライラン（実際の処理なし）')
    
    args = parser.parse_args()
    
    if not os.path.exists(args.input_file):
        print(f"ERROR: ファイルが見つかりません: {args.input_file}")
        return 1
    
    try:
        extractor = NovaLiteWhiskeyExtractor()
        result_file = extractor.process_file(args.input_file, args.dry_run)
        
        if result_file:
            print(f"SUCCESS: Nova Lite抽出完了 - {result_file}")
        else:
            print("INFO: Dry run completed")
        
        return 0
        
    except Exception as e:
        print(f"ERROR: 処理エラー: {e}")
        return 1


if __name__ == "__main__":
    exit(main())