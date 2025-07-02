#!/usr/bin/env python3
"""
Bedrock Titan モデルを使用してウイスキー名抽出スクリプト
楽天市場商品名からTitanモデルでウイスキー名と蒸留所を抽出
"""

import os
import sys
import json
import boto3
import logging
from datetime import datetime
from typing import List, Dict, Optional
import time

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bedrock_whiskey_extract.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class BedrockWhiskeyExtractor:
    """
    Bedrock Titanモデルを使用してウイスキー名と蒸留所を抽出するクラス
    """
    
    def __init__(self):
        # AWS設定
        self.region = os.getenv('AWS_REGION', 'ap-northeast-1')
        
        # Bedrockクライアント初期化
        self.bedrock_runtime = boto3.client('bedrock-runtime', region_name=self.region)
        
        # Nova Proモデル設定（inference profile使用）
        self.model_id = "apac.amazon.nova-pro-v1:0"  # Nova Pro
        
        # 処理設定
        self.batch_size = 10  # 一度に処理する商品名数（Nova Pro用に増加）
        self.api_rate_limit = 2.0  # APIコール間隔（秒）
        self.max_retries = 3
        self.retry_delay = 5
        
        logger.info(f"Bedrock初期化完了 - Region: {self.region}, Model: {self.model_id}")
    
    def _create_extraction_prompt(self, product_names: List[str]) -> str:
        """ウイスキー名抽出用のプロンプトを作成（改良版）"""
        names_text = '\n'.join([f"{i+1}. {name}" for i, name in enumerate(product_names)])
        
        prompt = f"""あなたはウイスキー専門家です。以下の楽天市場商品名からウイスキー情報を抽出してください。

商品名リスト:
{names_text}

## 蒸留所マッピング（重要）:
- サントリー/suntory → Suntory
- ニッカ/nikka → Nikka  
- ジムビーム/jim beam → Jim Beam
- マッカラン/macallan → The Macallan
- グレンフィディック/glenfiddich → Glenfiddich
- アマハガン → Nagahama Distillery
- 長濱蒸溜所 → Nagahama Distillery
- 秩父 → Venture Whisky
- 駒ヶ岳/Mars → Mars

## 出力形式（必須）:
{{
  "results": [
    {{
      "original_name": "元の商品名",
      "whiskey_name": "抽出されたウイスキー名",
      "distillery": "蒸留所名（上記マッピング使用）",
      "is_whiskey": true,
      "confidence": 0.95,
      "is_multiple": false,
      "whiskey_list": []
    }}
  ]
}}

## 複数ウイスキー対応:
セット商品や飲み比べセットの場合:
{{
  "original_name": "商品名",
  "whiskey_name": "メインウイスキー名 / サブウイスキー名",
  "distillery": "メイン蒸留所名",
  "is_whiskey": true,
  "confidence": 0.90,
  "is_multiple": true,
  "whiskey_list": [
    {{"name": "ウイスキー1", "distillery": "蒸留所1"}},
    {{"name": "ウイスキー2", "distillery": "蒸留所2"}}
  ]
}}

## 重要な指示:
1. 必ず有効なJSONフォーマットで出力
2. 商品名は必ずウイスキー関連なので is_whiskey: true
3. 蒸留所は上記マッピングを厳密に使用
4. 複数ウイスキーがある場合は is_multiple: true
5. JSON以外の説明文は一切不要
6. バックスラッシュやエスケープ文字は使用しない

JSONのみで回答してください:"""
        
        return prompt
    
    def _call_bedrock_titan(self, prompt: str) -> Optional[Dict]:
        """Bedrock Titanモデルを呼び出し"""
        for attempt in range(self.max_retries):
            try:
                logger.debug(f"Bedrock呼び出し (試行 {attempt + 1}/{self.max_retries})")
                
                # リクエストボディ作成（Nova形式）
                request_body = {
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "text": prompt
                                }
                            ]
                        }
                    ],
                    "inferenceConfig": {
                        "max_new_tokens": 4096,
                        "temperature": 0.1,  # 一貫性のため低温度
                        "top_p": 0.9
                    }
                }
                
                # Bedrock API呼び出し
                response = self.bedrock_runtime.invoke_model(
                    modelId=self.model_id,
                    body=json.dumps(request_body),
                    contentType="application/json",
                    accept="application/json"
                )
                
                # レスポンス解析（Nova形式）
                response_body = json.loads(response['body'].read())
                output_text = response_body.get('output', {}).get('message', {}).get('content', [{}])[0].get('text', '')
                
                # JSON部分を抽出（堅牢化）
                json_text = output_text.strip()
                
                # デバッグ用ログ
                logger.debug(f"生レスポンス（最初の200文字）: {output_text[:200]}")
                
                # ```json ``` で囲まれている場合
                if '```json' in json_text:
                    json_start = json_text.find('```json') + 7
                    json_end = json_text.find('```', json_start)
                    if json_end > json_start:
                        json_text = json_text[json_start:json_end].strip()
                elif '```' in json_text:
                    # ``` のみで囲まれている場合
                    json_start = json_text.find('```') + 3
                    json_end = json_text.find('```', json_start)
                    if json_end > json_start:
                        json_text = json_text[json_start:json_end].strip()
                
                # 最初と最後の{}を探す
                if not json_text.startswith('{'):
                    json_start = json_text.find('{')
                    json_end = json_text.rfind('}') + 1
                    if json_start >= 0 and json_end > json_start:
                        json_text = json_text[json_start:json_end]
                
                # 堅牢なJSON処理
                if json_text:
                    try:
                        # 無効な制御文字とエスケープ文字を除去
                        import re
                        
                        # 制御文字を除去
                        json_text = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', json_text)
                        
                        # 無効なUnicodeエスケープを修正または除去
                        # \\u#### 形式が不完全な場合の修正
                        json_text = re.sub(r'\\u([0-9A-Fa-f]{1,3})(?![0-9A-Fa-f])', r'', json_text)
                        
                        # 特殊なエスケープ文字を除去
                        json_text = re.sub(r'\\[^"\\/bfnrtu]', '', json_text)
                        
                        # 文字列内の問題のある引用符を修正
                        json_text = re.sub(r'(?<!\\)"([^"]*?)\\(?!["\\/bfnrtu])([^"]*?)"', r'"\1\2"', json_text)
                        
                        # 重複した引用符を修正
                        json_text = re.sub(r'""([^"]*?)""', r'"\1"', json_text)
                        
                        # JSON開始と終了を確実にする
                        if not json_text.startswith('{'):
                            json_text = '{' + json_text
                        if not json_text.endswith('}'):
                            json_text = json_text + '}'
                        
                        result = json.loads(json_text)
                        
                        # レート制限対応
                        time.sleep(self.api_rate_limit)
                        
                        return result
                        
                    except json.JSONDecodeError as e:
                        logger.error(f"JSON解析失敗（詳細）: {e}")
                        logger.debug(f"問題のあるJSON: {json_text[:500]}")
                        
                        # フォールバック: より積極的な文字列クリーニング
                        try:
                            # 最小限のJSONに修正してリトライ
                            simplified_json = self._create_simple_json(output_text)
                            if simplified_json:
                                return json.loads(simplified_json)
                        except:
                            pass
                        
                        # 最終フォールバック: 手動パーシング
                        return self._fallback_parsing(output_text)
                else:
                    logger.warning(f"JSONが見つかりません: {output_text[:200]}...")
                    return None
                
            except json.JSONDecodeError as e:
                logger.error(f"JSON解析エラー: {e}")
                if attempt < self.max_retries - 1:
                    logger.info(f"{self.retry_delay}秒後にリトライ...")
                    time.sleep(self.retry_delay)
                    continue
                return None
                
            except Exception as e:
                logger.error(f"Bedrock呼び出しエラー: {e}")
                if attempt < self.max_retries - 1:
                    logger.info(f"{self.retry_delay}秒後にリトライ...")
                    time.sleep(self.retry_delay)
                    continue
                return None
        
        logger.error("Bedrock呼び出し失敗")
        return None
    
    def _create_simple_json(self, output_text: str) -> Optional[str]:
        """最小限のJSONを作成"""
        try:
            import re
            
            # 基本的な情報を抽出してシンプルなJSONを作成
            original_name = ""
            whiskey_name = ""
            distillery = "Unknown"
            is_whiskey = False
            confidence = 0.5
            
            # パターンマッチで基本情報を抽出
            name_match = re.search(r'"original_name":\s*"([^"]*)"', output_text)
            if name_match:
                original_name = name_match.group(1)
            
            whiskey_match = re.search(r'"whiskey_name":\s*"([^"]*)"', output_text)
            if whiskey_match:
                whiskey_name = whiskey_match.group(1)
                is_whiskey = bool(whiskey_name.strip())
            
            distillery_match = re.search(r'"distillery":\s*"([^"]*)"', output_text)
            if distillery_match:
                distillery = distillery_match.group(1)
            
            # シンプルなJSONを作成
            simple_json = {
                "original_name": original_name,
                "whiskey_name": whiskey_name,
                "distillery": distillery,
                "is_whiskey": is_whiskey,
                "confidence": confidence
            }
            
            return json.dumps(simple_json, ensure_ascii=False)
            
        except Exception as e:
            logger.debug(f"シンプルJSON作成失敗: {e}")
            return None
    
    def _fallback_parsing(self, output_text: str) -> Optional[Dict]:
        """フォールバック用の簡略化パーシング"""
        try:
            # デフォルト値を設定
            result = {
                'original_name': '',
                'whiskey_name': '',
                'distillery': 'Unknown',
                'is_whiskey': False,
                'confidence': 0.0,
                'error': 'Bedrock processing failed'
            }
            
            # テキストからウイスキー関連キーワードを検索
            whiskey_keywords = ['ウイスキー', 'ウィスキー', 'whisky', 'whiskey', 'スコッチ', 'バーボン']
            if any(keyword in output_text.lower() for keyword in whiskey_keywords):
                result['is_whiskey'] = True
                result['confidence'] = 0.3
            
            return result
            
        except Exception as e:
            logger.error(f"フォールバック解析失敗: {e}")
            return {
                'original_name': '',
                'whiskey_name': '',
                'distillery': 'Unknown',
                'is_whiskey': False,
                'confidence': 0.0,
                'error': 'Bedrock processing failed'
            }
    
    def extract_whiskey_names(self, product_names: List[str]) -> List[Dict]:
        """商品名リストからウイスキー名を抽出"""
        logger.info(f"ウイスキー名抽出開始: {len(product_names)}件")
        
        all_results = []
        processed_count = 0
        
        # バッチ処理
        for i in range(0, len(product_names), self.batch_size):
            batch = product_names[i:i + self.batch_size]
            batch_num = i // self.batch_size + 1
            total_batches = (len(product_names) + self.batch_size - 1) // self.batch_size
            
            logger.info(f"バッチ {batch_num}/{total_batches} 処理中: {len(batch)}件")
            
            # プロンプト作成
            prompt = self._create_extraction_prompt(batch)
            
            # Bedrock呼び出し
            result = self._call_bedrock_titan(prompt)
            
            if result and 'results' in result:
                batch_results = result['results']
                all_results.extend(batch_results)
                processed_count += len(batch_results)
                
                # ウイスキー判定結果をログ出力
                whiskey_count = sum(1 for r in batch_results if r.get('is_whiskey', False))
                logger.info(f"バッチ結果: {len(batch_results)}件中 {whiskey_count}件がウイスキー")
            else:
                logger.error(f"バッチ {batch_num} の処理に失敗")
                # 失敗した場合もエントリを作成（エラー情報付き）
                for name in batch:
                    all_results.append({
                        'original_name': name,
                        'whiskey_name': '',
                        'distillery': 'Unknown',
                        'is_whiskey': False,
                        'confidence': 0.0,
                        'error': 'Bedrock processing failed'
                    })
                processed_count += len(batch)
        
        logger.info(f"ウイスキー名抽出完了: {processed_count}件処理")
        return all_results
    
    def process_file(self, input_file: str) -> Dict:
        """ファイルからデータを読み込んで処理"""
        logger.info(f"ファイル処理開始: {input_file}")
        
        if not os.path.exists(input_file):
            raise FileNotFoundError(f"ファイルが見つかりません: {input_file}")
        
        # 入力ファイル読み込み
        with open(input_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        product_names = data.get('product_names', [])
        metadata = data.get('metadata', {})
        
        logger.info(f"読み込み完了: {len(product_names)}件の商品名")
        
        # ウイスキー名抽出
        start_time = datetime.now()
        extraction_results = self.extract_whiskey_names(product_names)
        end_time = datetime.now()
        
        # 結果統計
        total_processed = len(extraction_results)
        whiskey_count = sum(1 for r in extraction_results if r.get('is_whiskey', False))
        high_confidence_count = sum(1 for r in extraction_results if r.get('confidence', 0) > 0.8)
        
        # 結果データ作成
        result_data = {
            'metadata': {
                'processing_time': start_time.isoformat(),
                'processing_duration': str(end_time - start_time),
                'input_file': input_file,
                'source_metadata': metadata,
                'total_processed': total_processed,
                'whiskey_identified': whiskey_count,
                'high_confidence_count': high_confidence_count,
                'model_used': self.model_id,
                'data_type': 'whiskey_extraction_results'
            },
            'extraction_results': extraction_results
        }
        
        # 結果ファイル保存
        timestamp = start_time.strftime('%Y%m%d_%H%M%S')
        output_file = f"whiskey_extraction_results_{timestamp}.json"
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(result_data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"=== 処理完了 ===")
        logger.info(f"実行時間: {end_time - start_time}")
        logger.info(f"処理件数: {total_processed}件")
        logger.info(f"ウイスキー認識: {whiskey_count}件 ({whiskey_count/total_processed*100:.1f}%)")
        logger.info(f"高信頼度: {high_confidence_count}件 ({high_confidence_count/total_processed*100:.1f}%)")
        logger.info(f"結果ファイル: {output_file}")
        
        return {
            'output_file': output_file,
            'total_processed': total_processed,
            'whiskey_identified': whiskey_count,
            'high_confidence_count': high_confidence_count,
            'processing_duration': str(end_time - start_time),
            'processing_time': start_time.isoformat()
        }


def main():
    """メイン関数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Bedrock Titanモデル ウイスキー名抽出スクリプト')
    parser.add_argument('--input-file', type=str, required=True, help='処理する楽天商品名ファイル')
    parser.add_argument('--dry-run', action='store_true', help='実際のBedrockコールを行わずテスト実行')
    
    args = parser.parse_args()
    
    if args.dry_run:
        logger.info("=== DRY RUN モード ===")
        logger.info(f"処理ファイル: {args.input_file}")
        logger.info("実際のBedrock処理は行いません")
        return
    
    try:
        extractor = BedrockWhiskeyExtractor()
        result = extractor.process_file(args.input_file)
        
        # 結果サマリー保存
        summary_file = f"bedrock_extraction_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(summary_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        
        logger.info(f"処理サマリーを {summary_file} に保存しました")
        
    except Exception as e:
        logger.error(f"処理中にエラー発生: {e}")
        raise


if __name__ == '__main__':
    main()