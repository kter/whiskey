#!/usr/bin/env python3
"""
ウイスキーデータ取得スクリプト
thewhiskeyedition.com APIからデータを取得し、翻訳してDynamoDBに保存
"""

import os
import sys
import time
import json
import requests
import logging
from datetime import datetime
from typing import List, Dict, Optional

# AWS SDK と翻訳サービスの直接インポート
import boto3

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('whiskey_data_fetch.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class WhiskeyDataFetcher:
    """
    TheWhiskeyEdition APIからデータを取得し、翻訳・保存するクラス
    """
    
    def __init__(self):
        self.base_url = "https://thewhiskyedition.com/api"
        
        # AWS設定
        self.region = os.getenv('AWS_REGION', 'ap-northeast-1')
        self.environment = os.getenv('ENVIRONMENT', 'dev')
        
        # DynamoDB直接接続
        self.dynamodb = boto3.resource('dynamodb', region_name=self.region)
        self.whiskey_search_table_name = f'WhiskeySearch-{self.environment}'
        
        # AWS Translate直接接続
        self.translate_client = boto3.client('translate', region_name=self.region)
        
        # 簡易翻訳辞書
        self.translation_dict = {
            'whisky': 'ウイスキー',
            'whiskey': 'ウイスキー', 
            'scotch': 'スコッチ',
            'bourbon': 'バーボン',
            'single malt': 'シングルモルト',
            'blended': 'ブレンデッド',
            'distillery': '蒸留所',
            'macallan': 'マッカラン',
            'glenfiddich': 'グレンフィディック',
            'highland': 'ハイランド',
            'speyside': 'スペイサイド',
            'islay': 'アイラ',
            'years old': '年物',
            'cask': 'カスク',
            'barrel': 'バレル',
            'sherry': 'シェリー'
        }
        
        # 非常に保守的なレート制限設定
        self.api_rate_limit = 8.0  # APIコール間隔（秒）
        self.translation_rate_limit = 0.5  # 翻訳間隔（秒）
        self.max_retries = 3
        self.retry_delay = 30  # リトライ間隔（秒）
        
        # リクエストセッション設定
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'WhiskeyLog/1.0 (Educational Purpose)',
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        })
        
        logger.info(f"API Rate Limit: {self.api_rate_limit}秒間隔")
        logger.info(f"Translation Rate Limit: {self.translation_rate_limit}秒間隔")
    
    def fetch_whiskeys(self, limit: int = 100, offset: int = 0) -> List[Dict]:
        """ウイスキーデータを取得"""
        whiskeys = []
        current_offset = offset
        
        logger.info(f"ウイスキーデータ取得開始: limit={limit}, offset={offset}")
        
        try:
            while len(whiskeys) < limit:
                # 正しいAPIエンドポイント
                url = f"{self.base_url}/whisky/get"
                params = {
                    'limit': min(50, limit - len(whiskeys)),  # 一度に最大50件
                    'offset': current_offset
                }
                
                logger.info(f"APIコール: {url} (offset={current_offset})")
                
                # APIコール実行
                response = self._make_api_request(url, params)
                if not response:
                    logger.error("APIレスポンスが空です")
                    break
                
                # APIは配列を直接返す
                if isinstance(response, list):
                    batch_whiskeys = response
                else:
                    batch_whiskeys = response.get('results', response.get('data', []))
                if not batch_whiskeys:
                    logger.info("これ以上データがありません")
                    break
                
                whiskeys.extend(batch_whiskeys)
                current_offset += len(batch_whiskeys)
                
                logger.info(f"取得済み: {len(whiskeys)} / {limit}")
                
                # 非常に保守的な待機
                logger.info(f"{self.api_rate_limit}秒待機中...")
                time.sleep(self.api_rate_limit)
                
            logger.info(f"ウイスキーデータ取得完了: {len(whiskeys)}件")
            return whiskeys[:limit]
            
        except Exception as e:
            logger.error(f"ウイスキーデータ取得エラー: {e}")
            return whiskeys
    
    def fetch_distilleries(self, limit: int = 50) -> List[Dict]:
        """蒸留所データを取得（TheWhiskyEdition APIには蒸留所専用エンドポイントがないため空を返す）"""
        logger.info(f"蒸留所データ取得スキップ: TheWhiskyEdition APIには蒸留所専用エンドポイントがありません")
        return []
    
    def _make_api_request(self, url: str, params: Dict = None) -> Optional[Dict]:
        """APIリクエストを実行（リトライ機能付き）"""
        for attempt in range(self.max_retries):
            try:
                logger.info(f"API Request (試行 {attempt + 1}/{self.max_retries}): {url}")
                
                response = self.session.get(url, params=params, timeout=30)
                response.raise_for_status()
                
                return response.json()
                
            except requests.exceptions.HTTPError as e:
                if response.status_code == 429:  # Rate limit exceeded
                    wait_time = self.retry_delay * (attempt + 1)
                    logger.warning(f"レート制限に達しました。{wait_time}秒待機...")
                    time.sleep(wait_time)
                    continue
                else:
                    logger.error(f"HTTPエラー: {e}")
                    return None
                    
            except requests.exceptions.RequestException as e:
                logger.error(f"リクエストエラー: {e}")
                if attempt < self.max_retries - 1:
                    logger.info(f"{self.retry_delay}秒後にリトライ...")
                    time.sleep(self.retry_delay)
                    continue
                return None
            
            except Exception as e:
                logger.error(f"予期しないエラー: {e}")
                return None
        
        logger.error(f"APIリクエスト失敗: {url}")
        return None
    
    def translate_and_save_data(self, whiskey_data: List[Dict]) -> int:
        """データを翻訳してDynamoDBに保存"""
        logger.info(f"データ翻訳・保存開始: {len(whiskey_data)}件")
        
        success_count = 0
        
        for i, whiskey in enumerate(whiskey_data):
            try:
                logger.info(f"処理中 ({i+1}/{len(whiskey_data)}): {whiskey.get('name', 'Unknown')}")
                
                # データを正規化
                normalized_data = self._normalize_whiskey_data(whiskey)
                
                # 翻訳
                translated_data = self._translate_whiskey_data(normalized_data)
                
                # DynamoDBに直接保存
                self._save_to_dynamodb(translated_data)
                success_count += 1
                
                logger.info(f"保存完了: {translated_data.get('name_ja', translated_data.get('name', 'Unknown'))}")
                
                # 翻訳レート制限
                time.sleep(self.translation_rate_limit)
                
            except Exception as e:
                logger.error(f"データ処理エラー: {e}")
                continue
        
        logger.info(f"データ翻訳・保存完了: {success_count}/{len(whiskey_data)}件成功")
        return success_count
    
    def _normalize_whiskey_data(self, raw_data: Dict) -> Dict:
        """APIレスポンスデータを正規化"""
        # TheWhiskyEdition APIのレスポンス形式に合わせて正規化
        metadata = raw_data.get('metadata', {})
        
        return {
            'name': raw_data.get('name', ''),
            'distillery': metadata.get('distillery', ''),
            'description': raw_data.get('description', ''),
            'region': metadata.get('region', ''),
            'type': metadata.get('type', ''),
            'age': metadata.get('age'),
            'abv': metadata.get('abv'),
            'bottler': metadata.get('bottler', ''),
            'country': metadata.get('country', ''),
            'price': metadata.get('price'),
            'url': raw_data.get('url', ''),
            'image_url': raw_data.get('image_url', ''),
            'author': raw_data.get('author', ''),
            'published': raw_data.get('published', ''),
            'original_data': raw_data  # 元データも保持
        }
    
    def _translate_text(self, text: str) -> str:
        """テキストを翻訳（辞書 -> AWS Translate）"""
        if not text:
            return ''
        
        # まず辞書をチェック
        text_lower = text.lower()
        if text_lower in self.translation_dict:
            return self.translation_dict[text_lower]
        
        # 部分一致もチェック
        for en_term, ja_term in self.translation_dict.items():
            if en_term in text_lower:
                return text.replace(en_term.title(), ja_term).replace(en_term, ja_term)
        
        # AWS Translateを使用
        try:
            response = self.translate_client.translate_text(
                Text=text,
                SourceLanguageCode='en',
                TargetLanguageCode='ja'
            )
            return response['TranslatedText']
        except Exception as e:
            logger.warning(f"Translation failed for '{text}': {e}")
            return text  # 翻訳失敗時は元のテキストを返す
    
    def _normalize_text(self, text: str) -> str:
        """テキストを検索用に正規化"""
        if not text:
            return ''
        return text.lower().replace(' ', '').replace('　', '')
    
    def _translate_whiskey_data(self, whiskey_data: Dict) -> Dict:
        """ウイスキーデータを翻訳"""
        result = whiskey_data.copy()
        
        # 名前を翻訳
        if whiskey_data.get('name'):
            result['name_ja'] = self._translate_text(whiskey_data['name'])
        
        # 蒸留所名を翻訳
        if whiskey_data.get('distillery'):
            result['distillery_ja'] = self._translate_text(whiskey_data['distillery'])
        
        # 説明を翻訳（500文字以内の場合のみ）
        description = whiskey_data.get('description', '')
        if description and len(description) <= 500:
            result['description_ja'] = self._translate_text(description)
        
        # 地域を翻訳
        if whiskey_data.get('region'):
            result['region_ja'] = self._translate_text(whiskey_data['region'])
        
        # タイプを翻訳
        if whiskey_data.get('type'):
            result['type_ja'] = self._translate_text(whiskey_data['type'])
        
        return result
    
    def _save_to_dynamodb(self, whiskey_data: Dict):
        """WhiskeySearchテーブルに保存"""
        import uuid
        from datetime import datetime
        from decimal import Decimal
        
        table = self.dynamodb.Table(self.whiskey_search_table_name)
        
        entry_id = str(uuid.uuid4())
        now = datetime.now().isoformat()
        
        # Float値をDecimalに変換
        def convert_float_to_decimal(value):
            if isinstance(value, float):
                return Decimal(str(value))
            return value
        
        # 蒸留所名のデフォルト値設定（空文字列の場合）
        distillery_en = whiskey_data.get('distillery', '').strip()
        distillery_ja = whiskey_data.get('distillery_ja', '').strip()
        
        if not distillery_en:
            distillery_en = 'No distillery provided'
        if not distillery_ja:
            distillery_ja = '蒸留所情報なし'
        
        item = {
            'id': entry_id,
            'name_en': whiskey_data.get('name', ''),
            'name_ja': whiskey_data.get('name_ja', ''),
            'distillery_en': distillery_en,
            'distillery_ja': distillery_ja,
            'normalized_name_en': self._normalize_text(whiskey_data.get('name', '')),
            'normalized_name_ja': self._normalize_text(whiskey_data.get('name_ja', '')),
            'normalized_distillery_en': self._normalize_text(distillery_en),
            'normalized_distillery_ja': self._normalize_text(distillery_ja),
            'description': whiskey_data.get('description', ''),
            'region': whiskey_data.get('region', ''),
            'type': whiskey_data.get('type', ''),
            'created_at': now,
            'updated_at': now
        }
        
        # 数値フィールドをDecimalに変換
        if whiskey_data.get('age') is not None:
            item['age'] = convert_float_to_decimal(whiskey_data.get('age'))
        if whiskey_data.get('abv') is not None:
            item['abv'] = convert_float_to_decimal(whiskey_data.get('abv'))
        if whiskey_data.get('price') is not None:
            item['price'] = convert_float_to_decimal(whiskey_data.get('price'))
        
        logger.info(f"DynamoDB保存中: {item['name_en']} -> {item['name_ja']} (蒸留所: {distillery_en})")
        table.put_item(Item=item)
    
    def fetch_and_save_to_file(self, whiskey_limit: int = 100, distillery_limit: int = 50):
        """APIデータを取得してファイルに保存（翻訳・DB保存は行わない）"""
        start_time = datetime.now()
        timestamp = start_time.strftime('%Y%m%d_%H%M%S')
        
        logger.info(f"=== APIデータ取得開始 ({start_time}) ===")
        
        try:
            # ウイスキーデータを取得
            logger.info("ウイスキーデータ取得中...")
            whiskeys = self.fetch_whiskeys(limit=whiskey_limit)
            
            # 少し休憩
            if whiskeys and distillery_limit > 0:
                logger.info("蒸留所データ取得前に60秒休憩...")
                time.sleep(60)
            
            # 蒸留所データを取得
            distilleries = []
            if distillery_limit > 0:
                logger.info("蒸留所データ取得中...")
                distilleries = self.fetch_distilleries(limit=distillery_limit)
            
            # データをファイルに保存
            data = {
                'metadata': {
                    'fetch_time': start_time.isoformat(),
                    'whiskey_count': len(whiskeys),
                    'distillery_count': len(distilleries),
                    'api_base_url': self.base_url
                },
                'whiskeys': whiskeys,
                'distilleries': distilleries
            }
            
            filename = f"raw_whiskey_data_{timestamp}.json"
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            end_time = datetime.now()
            duration = end_time - start_time
            
            logger.info(f"=== APIデータ取得完了 ({end_time}) ===")
            logger.info(f"実行時間: {duration}")
            logger.info(f"取得結果: ウイスキー {len(whiskeys)}件, 蒸留所 {len(distilleries)}件")
            logger.info(f"データファイル: {filename}")
            
            return {
                'filename': filename,
                'whiskey_count': len(whiskeys),
                'distillery_count': len(distilleries),
                'duration': str(duration),
                'fetch_time': start_time.isoformat()
            }
            
        except Exception as e:
            logger.error(f"API取得処理中にエラー発生: {e}")
            raise
    
    def process_from_file(self, filename: str):
        """ファイルからデータを読み込んで翻訳・DB保存を実行"""
        start_time = datetime.now()
        logger.info(f"=== ファイル処理開始 ({start_time}): {filename} ===")
        
        try:
            # ファイルからデータを読み込み
            logger.info(f"ファイル読み込み中: {filename}")
            with open(filename, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            whiskeys = data.get('whiskeys', [])
            metadata = data.get('metadata', {})
            
            logger.info(f"読み込み完了: ウイスキー {len(whiskeys)}件")
            logger.info(f"元データ取得日時: {metadata.get('fetch_time', 'Unknown')}")
            
            # 翻訳・保存処理
            if whiskeys:
                total_processed = self.translate_and_save_data(whiskeys)
            else:
                total_processed = 0
                logger.warning("処理するウイスキーデータがありません")
            
            end_time = datetime.now()
            duration = end_time - start_time
            
            logger.info(f"=== ファイル処理完了 ({end_time}) ===")
            logger.info(f"実行時間: {duration}")
            logger.info(f"処理結果: {total_processed}件成功")
            
            return {
                'source_file': filename,
                'whiskeys_processed': total_processed,
                'duration': str(duration),
                'start_time': start_time.isoformat(),
                'end_time': end_time.isoformat()
            }
            
        except Exception as e:
            logger.error(f"ファイル処理中にエラー発生: {e}")
            raise


def main():
    """メイン関数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='ウイスキーデータ取得・更新スクリプト')
    parser.add_argument('--mode', choices=['fetch', 'process'], required=True, 
                       help='実行モード: fetch=API取得してファイル保存, process=ファイルから読み込んで翻訳・DB保存')
    parser.add_argument('--whiskeys', type=int, default=100, help='取得するウイスキー数 (デフォルト: 100)')
    parser.add_argument('--distilleries', type=int, default=50, help='取得する蒸留所数 (デフォルト: 50)')
    parser.add_argument('--file', type=str, help='処理するファイル名 (processモード時に必須)')
    parser.add_argument('--dry-run', action='store_true', help='実際のAPIコールを行わずテスト実行')
    
    args = parser.parse_args()
    
    if args.dry_run:
        logger.info("=== DRY RUN モード ===")
        logger.info(f"実行モード: {args.mode}")
        if args.mode == 'fetch':
            logger.info(f"ウイスキー取得予定数: {args.whiskeys}")
            logger.info(f"蒸留所取得予定数: {args.distilleries}")
        elif args.mode == 'process':
            logger.info(f"処理ファイル: {args.file}")
        logger.info("実際の処理は行いません")
        return
    
    fetcher = WhiskeyDataFetcher()
    
    if args.mode == 'fetch':
        # API取得モード
        logger.info("=== API取得モード ===")
        result = fetcher.fetch_and_save_to_file(args.whiskeys, args.distilleries)
        
        # 結果をJSONファイルに保存
        result_file = f"fetch_result_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(result_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        
        logger.info(f"API取得結果を {result_file} に保存しました")
        logger.info(f"次のステップ: python {__file__} --mode process --file {result['filename']}")
        
    elif args.mode == 'process':
        # ファイル処理モード
        if not args.file:
            logger.error("processモードでは --file オプションが必須です")
            return
        
        if not os.path.exists(args.file):
            logger.error(f"指定されたファイルが見つかりません: {args.file}")
            return
        
        logger.info("=== ファイル処理モード ===")
        result = fetcher.process_from_file(args.file)
        
        # 結果をJSONファイルに保存
        result_file = f"process_result_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(result_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        
        logger.info(f"処理結果を {result_file} に保存しました")


if __name__ == '__main__':
    main()