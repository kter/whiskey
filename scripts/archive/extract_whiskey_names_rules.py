#!/usr/bin/env python3
"""
ルールベースウイスキー名抽出スクリプト
楽天市場商品名からルールベースでウイスキー名と蒸留所を抽出
"""

import os
import sys
import json
import re
import logging
from datetime import datetime
from typing import List, Dict, Optional, Tuple

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('rule_whiskey_extract.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class RuleBasedWhiskeyExtractor:
    """
    ルールベースでウイスキー名と蒸留所を抽出するクラス
    """
    
    def __init__(self):
        # 蒸留所・ブランドマッピング（日本語→英語）
        self.distillery_mapping = {
            'サントリー': 'Suntory',
            'suntory': 'Suntory',
            'ニッカ': 'Nikka',
            'nikka': 'Nikka',
            'マッカラン': 'The Macallan',
            'macallan': 'The Macallan',
            'グレンフィディック': 'Glenfiddich',
            'glenfiddich': 'Glenfiddich',
            'グレンリベット': 'The Glenlivet',
            'glenlivet': 'The Glenlivet',
            'ボウモア': 'Bowmore',
            'bowmore': 'Bowmore',
            'アードベッグ': 'Ardbeg',
            'ardbeg': 'Ardbeg',
            'ラガヴーリン': 'Lagavulin',
            'lagavulin': 'Lagavulin',
            'タリスカー': 'Talisker',
            'talisker': 'Talisker',
            'ジャックダニエル': "Jack Daniel's",
            'jack daniel': "Jack Daniel's",
            'ジムビーム': 'Jim Beam',
            'jim beam': 'Jim Beam',
            'バランタイン': "Ballantine's",
            'ballantine': "Ballantine's",
            'シーバスリーガル': 'Chivas Regal',
            'chivas regal': 'Chivas Regal',
            'ジョニーウォーカー': 'Johnnie Walker',
            'johnnie walker': 'Johnnie Walker',
            'イチローズモルト': "Ichiro's Malt",
            'ichiro': "Ichiro's Malt",
            'ベンチャーウイスキー': 'Venture Whisky',
            'venture': 'Venture Whisky',
            '長濱蒸溜所': 'Nagahama Distillery',
            '駒ヶ岳': 'Komagatake',
            'マルス': 'Mars',
            'mars': 'Mars',
            '倉吉': 'Kurayoshi',
            'サントリー白州': 'Suntory Hakushu',
            'カナディアンクラブ': 'Canadian Club',
            'カナディアン　クラブ': 'Canadian Club',
            'カナディアン クラブ': 'Canadian Club',
            'canadian club': 'Canadian Club',
            'カナディアンミスト': 'Canadian Mist',
            'カナディアン　ミスト': 'Canadian Mist',
            'canadian mist': 'Canadian Mist'
        }
        
        # ウイスキー名抽出パターン
        self.whiskey_patterns = [
            # 山崎、白州、響など
            (r'(山崎)\s*(\d+年|\d+\s*年|NV|ノンヴィンテージ|ノンエイジ)?', 'Suntory'),
            (r'(白州)\s*(\d+年|\d+\s*年|NV|ノンヴィンテージ|ノンエイジ)?', 'Suntory'),
            (r'(響)\s*(\d+年|\d+\s*年|NV|ノンヴィンテージ|ノンエイジ)?', 'Suntory'),
            (r'(知多)', 'Suntory'),
            (r'(角瓶)', 'Suntory'),
            (r'(トリス)\s*(クラシック)?', 'Suntory'),
            (r'(スペシャルリザーブ)', 'Suntory'),
            (r'(オールド)', 'Suntory'),
            
            # ニッカ製品
            (r'(ブラックニッカ)\s*(クリア|リッチブレンド|スペシャル)?', 'Nikka'),
            (r'(余市)\s*(\d+年|\d+\s*年|NV)?', 'Nikka'),
            (r'(宮城峡)\s*(\d+年|\d+\s*年|NV)?', 'Nikka'),
            (r'(フロム・ザ・バレル)', 'Nikka'),
            (r'(カフェグレーン)', 'Nikka'),
            
            # スコッチウイスキー
            (r'(マッカラン)\s*(\d+年|\d+\s*年)', 'The Macallan'),
            (r'(グレンフィディック)\s*(\d+年|\d+\s*年)', 'Glenfiddich'),
            (r'(グレンリベット)\s*(\d+年|\d+\s*年)', 'The Glenlivet'),
            (r'(ボウモア)\s*(\d+年|\d+\s*年)', 'Bowmore'),
            (r'(アードベッグ)\s*(\d+年|\d+\s*年|TEN|ウーガダール|コリーヴレッカン)?', 'Ardbeg'),
            (r'(ラガヴーリン)\s*(\d+年|\d+\s*年)', 'Lagavulin'),
            (r'(タリスカー)\s*(\d+年|\d+\s*年)', 'Talisker'),
            (r'(バランタイン)\s*(ファイネスト|\d+年|\d+\s*年)?', "Ballantine's"),
            (r'(シーバスリーガル)\s*(\d+年|\d+\s*年)', 'Chivas Regal'),
            (r'(ジョニーウォーカー)\s*(レッド|ブラック|ブルー|ゴールド)', 'Johnnie Walker'),
            
            # アメリカンウイスキー
            (r'(ジャックダニエル)\s*(No\.7|オールド|ブラック)?', "Jack Daniel's"),
            (r'(ジムビーム)\s*(ホワイト|ブラック|デビルズカット)?', 'Jim Beam'),
            
            # カナディアンウイスキー
            (r'(カナディアンクラブ)\s*(クラシック|\d+年)?', 'Canadian Club'),
            (r'(カナディアン　クラブ)\s*(クラシック|\d+年)?', 'Canadian Club'),
            (r'(カナディアン クラブ)\s*(クラシック|\d+年)?', 'Canadian Club'),
            (r'(カナディアンミスト)', 'Canadian Mist'),
            (r'(カナディアン　ミスト)', 'Canadian Mist'),
            
            # 日本のクラフト蒸留所
            (r'(イチローズモルト)\s*(ホワイトラベル|リーフ|モルト&グレーン)?', "Ichiro's Malt"),
            (r'(アマハガン)\s*(WorldMalt|ワールドモルト)?', 'Nagahama Distillery'),
            (r'(駒ヶ岳)\s*(Starry night|\d+年)?', 'Mars'),
            (r'(倉吉)\s*(\d+年)?', 'Kurayoshi'),
            (r'(秩父)', 'Venture Whisky'),
        ]
        
        # 除外パターン（セット商品関連を除去）
        self.exclude_patterns = [
            r'グラス',
            r'ボトル',
            r'タンブラー',
            r'カクテル',
            r'デキャンタ',
            r'ストーン',
            r'チョコ',
            r'菓子',
            r'ケーキ',
            r'スイーツ',
            r'化粧箱のみ',
            r'空箱',
            r'空瓶',
            r'コースター',
            r'おつまみ',
            r'Tシャツ',
            r'シャツ',
            r'帽子',
            r'キャップ',
            r'洗剤',
            r'靴'
        ]
        
        logger.info(f"ルールベース抽出器初期化完了 - パターン数: {len(self.whiskey_patterns)}")
    
    def _is_whiskey_product(self, name: str) -> bool:
        """商品がウイスキー関連かどうかを判定"""
        # 除外パターンチェック（ただし、セット商品は除外しない）
        is_set = any(re.search(p, name, re.IGNORECASE) for p in [r'\d+本.*セット', r'飲み比べ', r'詰め合わせ'])
        if not is_set:
            for pattern in self.exclude_patterns:
                if re.search(pattern, name, re.IGNORECASE):
                    return False
        
        # ウイスキー関連キーワードチェック
        whiskey_keywords = [
            'ウイスキー', 'ウィスキー', 'whisky', 'whiskey',
            'スコッチ', 'scotch', 'バーボン', 'bourbon',
            'シングルモルト', 'single malt', 'ブレンデッド', 'blended'
        ]
        
        name_lower = name.lower()
        
        # 基本的なウイスキーキーワードチェック
        if any(keyword in name_lower for keyword in whiskey_keywords):
            return True
        
        # 特定のウイスキーブランド名チェック（セット商品でも単体でも対応）
        whiskey_brand_keywords = [
            '山崎', '白州', '響', '知多', '角瓶', 'トリス', 'スペシャルリザーブ', 'オールド',
            'ブラックニッカ', '余市', '宮城峡', 'フロム・ザ・バレル',
            'ジムビーム', 'ジャックダニエル', 'マッカラン', 'グレンフィディック',
            'イチローズモルト', 'アマハガン', '駒ヶ岳', '倉吉',
            'カナディアンクラブ', 'カナディアンミスト', 'カナディアン　クラブ', 'カナディアン　ミスト', 'カナディアン クラブ'
        ]
        
        if any(brand in name for brand in whiskey_brand_keywords):
            return True
        
        return False
    
    def _extract_whiskey_info(self, name: str) -> Tuple[str, str, float]:
        """商品名からウイスキー名と蒸留所を抽出（複数対応）"""
        name_clean = name.strip()
        
        # 複数ウイスキー検出
        multiple_whiskeys = self._extract_multiple_whiskeys(name_clean)
        if multiple_whiskeys:
            # 複数の場合は最初のもので代表するか、全てを結合
            if len(multiple_whiskeys) > 1:
                whiskey_names = [w['name'] for w in multiple_whiskeys]
                main_distillery = multiple_whiskeys[0]['distillery']
                combined_name = ' / '.join(whiskey_names)
                return combined_name, main_distillery, 0.85
            else:
                whiskey = multiple_whiskeys[0]
                return whiskey['name'], whiskey['distillery'], whiskey['confidence']
        
        # 単一ウイスキーパターンマッチング
        for pattern, distillery in self.whiskey_patterns:
            match = re.search(pattern, name_clean, re.IGNORECASE)
            if match:
                whiskey_name = match.group(0)
                # 不要な文字を削除
                whiskey_name = re.sub(r'【.*?】', '', whiskey_name)
                whiskey_name = re.sub(r'（.*?）', '', whiskey_name)
                whiskey_name = re.sub(r'\(.*?\)', '', whiskey_name)
                whiskey_name = whiskey_name.strip()
                
                return whiskey_name, distillery, 0.9
        
        # 蒸留所名マッピングから検索
        name_lower = name_clean.lower()
        for jp_name, en_name in self.distillery_mapping.items():
            if jp_name in name_clean or jp_name.lower() in name_lower:
                # 商品名を簡略化
                whiskey_name = re.sub(r'【.*?】', '', name_clean)
                whiskey_name = re.sub(r'（.*?）', '', whiskey_name)
                whiskey_name = re.sub(r'\(.*?\)', '', whiskey_name)
                whiskey_name = re.sub(r'ふるさと納税.*', '', whiskey_name)
                whiskey_name = re.sub(r'送料無料.*', '', whiskey_name)
                whiskey_name = re.sub(r'\d+本.*セット.*', '', whiskey_name)
                whiskey_name = whiskey_name.strip()[:100]  # 100文字まで
                
                return whiskey_name, en_name, 0.7
        
        # マッチしない場合
        return '', 'Unknown', 0.0
    
    def _extract_multiple_whiskeys(self, name: str) -> List[Dict]:
        """複数ウイスキーの抽出"""
        whiskeys = []
        
        # セット商品パターンの検出
        set_patterns = [
            r'(\d+種.*?セット)',
            r'(\d+本.*?セット)', 
            r'飲み比べ.*?セット',
            r'詰め合わせ'
        ]
        
        is_set = any(re.search(pattern, name, re.IGNORECASE) for pattern in set_patterns)
        
        if is_set:
            # 括弧内の複数ウイスキー名を抽出
            bracket_patterns = [r'[（(](.*?)[）)]', r'【(.*?)】']
            
            for pattern in bracket_patterns:
                bracket_match = re.search(pattern, name)
                if bracket_match:
                    content = bracket_match.group(1)
                    # 複数の区切り文字で分割
                    whiskey_names = re.split(r'[/・｜,，\s]+', content)
                    
                    for whiskey_name in whiskey_names:
                        whiskey_name = whiskey_name.strip()
                        if whiskey_name and len(whiskey_name) > 1:  # 最小長チェック
                            # 各ウイスキーの蒸留所を推定
                            distillery = self._identify_distillery(whiskey_name, name)
                            whiskeys.append({
                                'name': whiskey_name,
                                'distillery': distillery,
                                'confidence': 0.8
                            })
                    
                    if whiskeys:  # 1つのパターンで見つかったら終了
                        break
            
            # その他の複数パターン検出
            if not whiskeys:
                # 特定のキーワードを含む場合
                multi_keywords = ['角瓶', 'オールド', 'スペシャルリザーブ', 'ジムビーム', '山崎', '白州', '響']
                found_whiskeys = []
                for keyword in multi_keywords:
                    if keyword in name:
                        distillery = self._identify_distillery(keyword, name)
                        found_whiskeys.append({
                            'name': keyword,
                            'distillery': distillery,
                            'confidence': 0.75
                        })
                
                if len(found_whiskeys) > 1:
                    whiskeys = found_whiskeys
        
        return whiskeys
    
    def _identify_distillery(self, whiskey_name: str, full_name: str) -> str:
        """ウイスキー名と商品名から蒸留所を特定"""
        # ウイスキー名ベースの蒸留所マッピング
        whiskey_distillery_map = {
            '角瓶': 'Suntory',
            'オールド': 'Suntory', 
            'スペシャルリザーブ': 'Suntory',
            'トリス': 'Suntory',
            '山崎': 'Suntory',
            '白州': 'Suntory',
            '響': 'Suntory',
            '知多': 'Suntory',
            'ブラックニッカ': 'Nikka',
            '余市': 'Nikka',
            '宮城峡': 'Nikka',
            'フロム・ザ・バレル': 'Nikka',
            'ジムビーム': 'Jim Beam',
            'ジャックダニエル': "Jack Daniel's",
            'マッカラン': 'The Macallan',
            'グレンフィディック': 'Glenfiddich',
            'カナディアンクラブ': 'Canadian Club',
            'カナディアン　クラブ': 'Canadian Club',
            'カナディアン クラブ': 'Canadian Club',
            'カナディアンミスト': 'Canadian Mist',
            'カナディアン　ミスト': 'Canadian Mist'
        }
        
        # 直接マッピング
        if whiskey_name in whiskey_distillery_map:
            return whiskey_distillery_map[whiskey_name]
        
        # 商品名から蒸留所情報を抽出
        for jp_name, en_name in self.distillery_mapping.items():
            if jp_name in full_name.lower() or jp_name in full_name:
                return en_name
        
        return 'Unknown'
    
    def extract_whiskey_names(self, product_names: List[str]) -> List[Dict]:
        """商品名リストからウイスキー名を抽出"""
        logger.info(f"ウイスキー名抽出開始: {len(product_names)}件")
        
        results = []
        whiskey_count = 0
        
        for i, name in enumerate(product_names):
            logger.debug(f"処理中 ({i+1}/{len(product_names)}): {name[:50]}...")
            
            # ウイスキー商品判定
            is_whiskey = self._is_whiskey_product(name)
            
            if is_whiskey:
                # ウイスキー情報抽出
                whiskey_name, distillery, confidence = self._extract_whiskey_info(name)
                whiskey_count += 1
            else:
                whiskey_name, distillery, confidence = '', 'Unknown', 0.0
            
            result = {
                'original_name': name,
                'whiskey_name': whiskey_name,
                'distillery': distillery,
                'is_whiskey': is_whiskey,
                'confidence': confidence
            }
            
            results.append(result)
            
            if is_whiskey:
                logger.debug(f"ウイスキー認識: {whiskey_name} ({distillery})")
        
        logger.info(f"ウイスキー名抽出完了: {len(results)}件処理, {whiskey_count}件がウイスキー")
        return results
    
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
                'method': 'rule_based_extraction',
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
    
    parser = argparse.ArgumentParser(description='ルールベース ウイスキー名抽出スクリプト')
    parser.add_argument('--input-file', type=str, required=True, help='処理する楽天商品名ファイル')
    parser.add_argument('--dry-run', action='store_true', help='実際の処理を行わずテスト実行')
    
    args = parser.parse_args()
    
    if args.dry_run:
        logger.info("=== DRY RUN モード ===")
        logger.info(f"処理ファイル: {args.input_file}")
        logger.info("実際の処理は行いません")
        return
    
    try:
        extractor = RuleBasedWhiskeyExtractor()
        result = extractor.process_file(args.input_file)
        
        # 結果サマリー保存
        summary_file = f"rule_extraction_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(summary_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        
        logger.info(f"処理サマリーを {summary_file} に保存しました")
        
    except Exception as e:
        logger.error(f"処理中にエラー発生: {e}")
        raise


if __name__ == '__main__':
    main()