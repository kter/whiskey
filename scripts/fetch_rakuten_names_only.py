#!/usr/bin/env python3
"""
楽天市場API ウイスキー商品名のみ取得スクリプト
楽天市場APIからウイスキー関連商品の名前のみを取得し、ファイルに保存
"""

import os
import sys
import time
import json
import requests
import logging
from datetime import datetime
from typing import List, Dict, Optional

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('rakuten_names_fetch.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class RakutenNamesFetcher:
    """
    楽天市場APIからウイスキー関連商品名のみを取得するクラス
    """
    
    def __init__(self):
        # 楽天API設定
        self.rakuten_app_id = os.getenv('RAKUTEN_APP_ID')
        if not self.rakuten_app_id:
            raise ValueError("RAKUTEN_APP_ID環境変数が設定されていません")
        
        self.base_url = "https://app.rakuten.co.jp/services/api/IchibaItem/Search/20220601"
        
        # ウイスキー関連キーワード（楽天検索用）
        self.whiskey_keywords = [
            'ウイスキー',
            'スコッチ',
            'バーボン',
            'アイリッシュウイスキー', 
            'ジャパニーズウイスキー',
            'カナディアンウイスキー',
            'シングルモルト',
            'ブレンデッドウイスキー',
            'whisky',
            'whiskey'
        ]
        
        # ブランド名（より具体的な検索用）
        self.brand_keywords = [
            'マッカラン',
            'グレンフィディック',
            'グレンリベット',
            'ボウモア',
            'アードベッグ',
            'ラガヴーリン',
            'タリスカー',
            'ジャックダニエル',
            'ジムビーム',
            'ニッカ',
            '山崎',
            '白州',
            '響',
            'バランタイン',
            'シーバスリーガル',
            'ジョニーウォーカー',
            'サントリー',
            'アマハガン',
            '角瓶',
            '知多'
        ]
        
        # レート制限設定
        self.api_rate_limit = 1.0  # APIコール間隔（秒）
        self.max_retries = 3
        self.retry_delay = 10
        
        # リクエストセッション設定
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'WhiskeyLog/1.0 (Educational Purpose)'
        })
        
        logger.info(f"楽天API初期化完了 - App ID: {self.rakuten_app_id[:8]}***")
        logger.info(f"検索キーワード数: {len(self.whiskey_keywords + self.brand_keywords)}")
    
    def search_product_names(self, keyword: str, page: int = 1, hits: int = 30) -> List[str]:
        """楽天市場APIで商品名のみを検索"""
        try:
            params = {
                'applicationId': self.rakuten_app_id,
                'keyword': keyword,
                'page': page,
                'hits': hits,
                'sort': 'standard',  # 標準順
                'format': 'json'
            }
            
            logger.debug(f"楽天API検索: キーワード='{keyword}', ページ={page}")
            
            response = self._make_api_request(self.base_url, params)
            if not response:
                return []
            
            items = response.get('Items', [])
            product_names = []
            
            for item_data in items:
                item = item_data.get('Item', {})
                item_name = item.get('itemName', '').strip()
                
                if item_name and self._contains_whiskey_keywords(item_name):
                    product_names.append(item_name)
            
            logger.info(f"検索結果: {len(items)}件中 {len(product_names)}件がウイスキー関連商品名")
            return product_names
            
        except Exception as e:
            logger.error(f"楽天API検索エラー: {e}")
            return []
    
    def _contains_whiskey_keywords(self, name: str) -> bool:
        """商品名にウイスキー関連キーワードが含まれているかチェック（簡易版）"""
        name_lower = name.lower()
        
        # ウイスキー関連キーワード
        whiskey_terms = [
            'ウイスキー', 'ウィスキー', 'whisky', 'whiskey', 'スコッチ', 'scotch',
            'バーボン', 'bourbon', 'シングルモルト', 'single malt',
            'ブレンデッド', 'blended', 'アイリッシュ', 'irish',
            'ジャパニーズ', 'japanese', 'カナディアン', 'canadian',
            '角瓶', '山崎', '白州', '響', 'マッカラン', 'グレンフィディック',
            'アマハガン', 'ニッカ', 'サントリー', 'suntory', '知多'
        ]
        
        # 明らかに除外すべきキーワード
        exclude_terms = [
            'グラス', 'ボトル', 'タンブラー', 'カクテル', 'デキャンタ', 
            'ストーン', 'チョコ', '菓子', 'ケーキ', 'スイーツ',
            '化粧箱のみ', '空箱', '空瓶', 'コースター', 'おつまみ',
            'Tシャツ', 'シャツ', '帽子', 'キャップ', '洗剤', '靴'
        ]
        
        has_whiskey_term = any(term in name or term in name_lower for term in whiskey_terms)
        has_exclude_term = any(term in name for term in exclude_terms)
        
        return has_whiskey_term and not has_exclude_term
    
    def _make_api_request(self, url: str, params: Dict) -> Optional[Dict]:
        """APIリクエストを実行（リトライ機能付き）"""
        for attempt in range(self.max_retries):
            try:
                logger.debug(f"API Request (試行 {attempt + 1}/{self.max_retries}): {url}")
                
                response = self.session.get(url, params=params, timeout=30)
                response.raise_for_status()
                
                # レート制限対応
                time.sleep(self.api_rate_limit)
                
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
    
    def fetch_all_product_names(self, max_items: int = 1000) -> List[str]:
        """全ウイスキー商品名を取得"""
        logger.info(f"楽天ウイスキー商品名取得開始 (最大{max_items}件)")
        
        all_names = []
        seen_names = set()  # 重複除去用
        
        # 各キーワードで検索
        all_keywords = self.whiskey_keywords + self.brand_keywords
        
        for keyword in all_keywords:
            if len(all_names) >= max_items:
                break
            
            logger.info(f"キーワード検索: '{keyword}'")
            
            # 複数ページを取得
            page = 1
            max_pages = 5  # キーワードあたり最大5ページ
            
            while page <= max_pages and len(all_names) < max_items:
                product_names = self.search_product_names(keyword, page=page, hits=30)
                
                if not product_names:
                    break  # データがない場合は次のキーワードへ
                
                # 重複除去
                new_names = 0
                for name in product_names:
                    if name not in seen_names:
                        seen_names.add(name)
                        all_names.append(name)
                        new_names += 1
                
                logger.info(f"ページ{page}: {len(product_names)}件取得, {new_names}件が新規")
                
                if new_names == 0:
                    break  # 新規商品がない場合は次のキーワードへ
                
                page += 1
                
                # レート制限
                time.sleep(self.api_rate_limit)
        
        logger.info(f"楽天ウイスキー商品名取得完了: {len(all_names)}件")
        return all_names[:max_items]
    
    def fetch_and_save_names(self, max_items: int = 1000):
        """楽天API商品名を取得してファイルに保存"""
        start_time = datetime.now()
        timestamp = start_time.strftime('%Y%m%d_%H%M%S')
        
        logger.info(f"=== 楽天API商品名取得開始 ({start_time}) ===")
        
        try:
            # 商品名を取得
            product_names = self.fetch_all_product_names(max_items=max_items)
            
            # データをファイルに保存
            data = {
                'metadata': {
                    'fetch_time': start_time.isoformat(),
                    'product_count': len(product_names),
                    'api_source': 'rakuten_ichiba',
                    'max_items': max_items,
                    'data_type': 'product_names_only'
                },
                'product_names': product_names
            }
            
            filename = f"rakuten_product_names_{timestamp}.json"
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            end_time = datetime.now()
            duration = end_time - start_time
            
            logger.info(f"=== 楽天API商品名取得完了 ({end_time}) ===")
            logger.info(f"実行時間: {duration}")
            logger.info(f"取得結果: 商品名 {len(product_names)}件")
            logger.info(f"データファイル: {filename}")
            
            return {
                'filename': filename,
                'product_count': len(product_names),
                'duration': str(duration),
                'fetch_time': start_time.isoformat()
            }
            
        except Exception as e:
            logger.error(f"楽天API取得処理中にエラー発生: {e}")
            raise


def main():
    """メイン関数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='楽天市場API ウイスキー商品名取得スクリプト')
    parser.add_argument('--max-items', type=int, default=1000, help='取得する最大商品名数 (デフォルト: 1000)')
    parser.add_argument('--dry-run', action='store_true', help='実際のAPIコールを行わずテスト実行')
    
    args = parser.parse_args()
    
    if args.dry_run:
        logger.info("=== DRY RUN モード ===")
        logger.info(f"商品名取得予定数: {args.max_items}")
        logger.info("実際の処理は行いません")
        return
    
    fetcher = RakutenNamesFetcher()
    result = fetcher.fetch_and_save_names(args.max_items)
    
    # 結果をJSONファイルに保存
    result_file = f"rakuten_names_fetch_result_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(result_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    logger.info(f"API取得結果を {result_file} に保存しました")
    logger.info(f"次のステップ: Bedrockでウイスキー名抽出処理を実行")


if __name__ == '__main__':
    main()