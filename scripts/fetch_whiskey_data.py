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

# Django設定を読み込み
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')

import django
django.setup()

from backend.api.dynamodb_service import DynamoDBService
from backend.api.translation_service import TranslationService

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
        self.base_url = "https://api.thewhiskyedition.com"
        self.db_service = DynamoDBService()
        self.translation_service = TranslationService()
        
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
                # APIエンドポイント（仮想的な例 - 実際のAPIドキュメントに合わせて調整）
                url = f"{self.base_url}/whiskeys"
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
                
                batch_whiskeys = response.get('results', [])
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
        """蒸留所データを取得"""
        logger.info(f"蒸留所データ取得開始: limit={limit}")
        
        try:
            url = f"{self.base_url}/distilleries"
            params = {'limit': limit}
            
            response = self._make_api_request(url, params)
            if not response:
                return []
            
            distilleries = response.get('results', [])
            logger.info(f"蒸留所データ取得完了: {len(distilleries)}件")
            
            return distilleries
            
        except Exception as e:
            logger.error(f"蒸留所データ取得エラー: {e}")
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
                
                # DynamoDBに保存
                self.db_service.create_whiskey_search_entry(translated_data)
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
        # APIの実際のレスポンス形式に合わせて調整
        return {
            'name': raw_data.get('name', ''),
            'distillery': raw_data.get('distillery', {}).get('name', '') if isinstance(raw_data.get('distillery'), dict) else raw_data.get('distillery', ''),
            'description': raw_data.get('description', ''),
            'region': raw_data.get('region', ''),
            'type': raw_data.get('type', ''),
            'age': raw_data.get('age'),
            'abv': raw_data.get('abv'),
            'cask_type': raw_data.get('cask_type', ''),
            'bottler': raw_data.get('bottler', ''),
            'category': raw_data.get('category', ''),
            'country': raw_data.get('country', ''),
            'original_data': raw_data  # 元データも保持
        }
    
    def _translate_whiskey_data(self, whiskey_data: Dict) -> Dict:
        """ウイスキーデータを翻訳"""
        result = whiskey_data.copy()
        
        # 名前を翻訳
        if whiskey_data.get('name'):
            result['name_ja'] = self.translation_service.translate_to_japanese(whiskey_data['name'])
        
        # 蒸留所名を翻訳
        if whiskey_data.get('distillery'):
            result['distillery_ja'] = self.translation_service.translate_to_japanese(whiskey_data['distillery'])
        
        # 説明を翻訳（500文字以内の場合のみ）
        description = whiskey_data.get('description', '')
        if description and len(description) <= 500:
            result['description_ja'] = self.translation_service.translate_to_japanese(description)
        
        # 地域を翻訳
        if whiskey_data.get('region'):
            result['region_ja'] = self.translation_service.translate_to_japanese(whiskey_data['region'])
        
        # タイプを翻訳
        if whiskey_data.get('type'):
            result['type_ja'] = self.translation_service.translate_to_japanese(whiskey_data['type'])
        
        return result
    
    def run_full_update(self, whiskey_limit: int = 1000, distillery_limit: int = 100):
        """完全なデータ更新を実行"""
        start_time = datetime.now()
        logger.info(f"=== ウイスキーデータ更新開始 ({start_time}) ===")
        
        total_whiskeys = 0
        total_distilleries = 0
        
        try:
            # ウイスキーデータを取得
            logger.info("ウイスキーデータ取得中...")
            whiskeys = self.fetch_whiskeys(limit=whiskey_limit)
            if whiskeys:
                total_whiskeys = self.translate_and_save_data(whiskeys)
            
            # 少し休憩
            logger.info("蒸留所データ取得前に60秒休憩...")
            time.sleep(60)
            
            # 蒸留所データを取得
            logger.info("蒸留所データ取得中...")
            distilleries = self.fetch_distilleries(limit=distillery_limit)
            if distilleries:
                # 蒸留所データも同様に処理（必要に応じて）
                total_distilleries = len(distilleries)
                logger.info(f"蒸留所データ取得完了: {total_distilleries}件")
            
        except Exception as e:
            logger.error(f"更新処理中にエラー発生: {e}")
        
        end_time = datetime.now()
        duration = end_time - start_time
        
        logger.info(f"=== ウイスキーデータ更新完了 ({end_time}) ===")
        logger.info(f"実行時間: {duration}")
        logger.info(f"処理結果: ウイスキー {total_whiskeys}件, 蒸留所 {total_distilleries}件")
        
        return {
            'whiskeys_processed': total_whiskeys,
            'distilleries_processed': total_distilleries,
            'duration': str(duration),
            'start_time': start_time.isoformat(),
            'end_time': end_time.isoformat()
        }


def main():
    """メイン関数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='ウイスキーデータ取得・更新スクリプト')
    parser.add_argument('--whiskeys', type=int, default=100, help='取得するウイスキー数 (デフォルト: 100)')
    parser.add_argument('--distilleries', type=int, default=50, help='取得する蒸留所数 (デフォルト: 50)')
    parser.add_argument('--dry-run', action='store_true', help='実際のAPIコールを行わずテスト実行')
    
    args = parser.parse_args()
    
    if args.dry_run:
        logger.info("=== DRY RUN モード ===")
        logger.info(f"ウイスキー取得予定数: {args.whiskeys}")
        logger.info(f"蒸留所取得予定数: {args.distilleries}")
        logger.info("実際のAPIコールは行いません")
        return
    
    fetcher = WhiskeyDataFetcher()
    result = fetcher.run_full_update(args.whiskeys, args.distilleries)
    
    # 結果をJSONファイルに保存
    result_file = f"fetch_result_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(result_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    logger.info(f"実行結果を {result_file} に保存しました")


if __name__ == '__main__':
    main()