import boto3
import os
import json
import time
from typing import Dict, Optional
from decimal import Decimal
import logging

from .cache_service import get_cache_service

logger = logging.getLogger(__name__)


class TranslationService:
    """
    翻訳サービス - 手動辞書とAWS Translateを組み合わせ
    ElastiCache Valkeyでキャッシュを管理
    """
    
    def __init__(self):
        self.region = os.getenv('AWS_REGION', 'ap-northeast-1')
        
        # AWS Translate クライアント
        self.translate_client = boto3.client('translate', region_name=self.region)
        
        # ElastiCache Valkey クライアント
        self.cache_service = get_cache_service()
        
        # 手動辞書 - ウイスキー関連用語の翻訳辞書
        self.manual_dictionary = {
            # 一般的なウイスキー用語
            'whisky': 'ウイスキー',
            'whiskey': 'ウイスキー', 
            'scotch': 'スコッチ',
            'bourbon': 'バーボン',
            'rye': 'ライ',
            'single malt': 'シングルモルト',
            'blended': 'ブレンデッド',
            'grain': 'グレーン',
            'pot still': 'ポットスチル',
            'column still': 'コラムスチル',
            'cask': 'カスク',
            'barrel': 'バレル',
            'sherry': 'シェリー',
            'port': 'ポート',
            'bourbon barrel': 'バーボンバレル',
            'hogshead': 'ホグスヘッド',
            'butt': 'バット',
            'puncheon': 'パンチョン',
            'quarter cask': 'クォーターカスク',
            'first fill': 'ファーストフィル',
            'refill': 'リフィル',
            'finish': 'フィニッシュ',
            'maturation': '熟成',
            'aging': '熟成',
            'age': '年数',
            'years old': '年物',
            'non-age-statement': 'ノンエイジ',
            'nas': 'ノンエイジ',
            'cask strength': 'カスクストレングス',
            'barrel proof': 'バレルプルーフ',
            'natural color': 'ナチュラルカラー',
            'non-chill filtered': 'ノンチルフィルタード',
            'peated': 'ピーテッド',
            'unpeated': 'アンピーテッド',
            'peat': 'ピート',
            'smoke': 'スモーク',
            'smoky': 'スモーキー',
            'maritime': 'マリタイム',
            'coastal': 'コースタル',
            'highland': 'ハイランド',
            'lowland': 'ローランド',
            'speyside': 'スペイサイド',
            'islay': 'アイラ',
            'campbeltown': 'キャンベルタウン',
            'islands': 'アイランズ',
            
            # 蒸留所名（一部）
            'macallan': 'マッカラン',
            'glenfiddich': 'グレンフィディック',
            'glenlivet': 'グレンリベット',
            'ardbeg': 'アードベッグ',
            'laphroaig': 'ラフロイグ',
            'lagavulin': 'ラガヴーリン',
            'bowmore': 'ボウモア',
            'bruichladdich': 'ブルックラディ',
            'bunnahabhain': 'ブナハーブン',
            'caol ila': 'カリラ',
            'kilchoman': 'キルホーマン',
            'springbank': 'スプリングバンク',
            'glendronach': 'グレンドロナック',
            'balvenie': 'バルヴェニー',
            'glenmorangie': 'グレンモーレンジィ',
            'oban': 'オーバン',
            'talisker': 'タリスカー',
            'highland park': 'ハイランドパーク',
            'dalmore': 'ダルモア',
            'glengoyne': 'グレングイン',
            'craigellachie': 'クライゲラヒー',
            'aberlour': 'アベラワー',
            'cardhu': 'カーデュ',
            'glen grant': 'グレングラント',
            'strathisla': 'ストラスアイラ',
            'benriach': 'ベンリアック',
            'glendullan': 'グレンデュラン',
            'mortlach': 'モートラック',
            'cragganmore': 'クラガンモア',
            'dalwhinnie': 'ダルウィニー',
            'royal lochnagar': 'ロイヤルロッホナガー',
            'aberfeldy': 'アバフェルディ',
            'edradour': 'エドラダワー',
            'blair athol': 'ブレアアソル',
            'deanston': 'ディーンストン',
            'glenturret': 'グレンタレット',
            'tomatin': 'トマーティン',
            'glen ord': 'グレンオード',
            'clynelish': 'クライヌリッシュ',
            'balblair': 'バルブレア',
            'glenmorangie': 'グレンモーレンジィ',
            'arran': 'アラン',
            'jura': 'ジュラ',
            'tobermory': 'トバモリー',
            'ledaig': 'レダイグ',
            
            # アメリカンウイスキー
            'kentucky': 'ケンタッキー',
            'tennessee': 'テネシー',
            'jack daniels': 'ジャックダニエル',
            'jim beam': 'ジムビーム',
            'makers mark': 'メーカーズマーク',
            'woodford reserve': 'ウッドフォードリザーブ',
            'buffalo trace': 'バッファロートレース',
            'wild turkey': 'ワイルドターキー',
            'four roses': 'フォアローゼス',
            'evan williams': 'エヴァンウィリアムス',
            'knob creek': 'ノブクリーク',
            'basil hayden': 'ベイゼルヘイデン',
            'bookers': 'ブッカーズ',
            'bakers': 'ベイカーズ',
            'old forester': 'オールドフォレスター',
            'elijah craig': 'イライジャクレイグ',
            'heaven hill': 'ヘブンヒル',
            'very old barton': 'ベリーオールドバートン',
            'old grand dad': 'オールドグランダッド',
            'old crow': 'オールドクロウ',
            
            # 日本のウイスキー
            'yamazaki': '山崎',
            'hakushu': '白州',
            'hibiki': '響',
            'taketsuru': '竹鶴',
            'yoichi': '余市',
            'miyagikyo': '宮城峡',
            'chichibu': '秩父',
            'mars': 'マルス',
            'komagatake': '駒ヶ岳',
            'fuji': '富士',
            'akashi': '明石',
            'eigashima': '江井ヶ嶋',
            'white oak': 'ホワイトオーク',
            'karuizawa': '軽井沢',
            'hanyu': '羽生',
            
            # テイスティングノート
            'vanilla': 'バニラ',
            'honey': 'ハチミツ',
            'caramel': 'カラメル',
            'toffee': 'トフィー',
            'chocolate': 'チョコレート',
            'coffee': 'コーヒー',
            'espresso': 'エスプレッソ',
            'orange': 'オレンジ',
            'lemon': 'レモン',
            'apple': 'リンゴ',
            'pear': '洋梨',
            'cherry': 'チェリー',
            'strawberry': 'ストロベリー',
            'blackberry': 'ブラックベリー',
            'raisin': 'レーズン',
            'fig': 'イチジク',
            'date': 'デーツ',
            'almond': 'アーモンド',
            'walnut': 'クルミ',
            'hazelnut': 'ヘーゼルナッツ',
            'cinnamon': 'シナモン',
            'nutmeg': 'ナツメグ',
            'clove': 'クローブ',
            'ginger': 'ジンジャー',
            'black pepper': 'ブラックペッパー',
            'oak': 'オーク',
            'cedar': 'シダー',
            'leather': 'レザー',
            'tobacco': 'タバコ',
            'iodine': 'ヨード',
            'seaweed': '海藻',
            'salt': '塩',
            'brine': 'ブライン',
            'medicinal': '薬品',
            'tar': 'タール',
            'rubber': 'ゴム',
            'earthy': 'アーシー',
            'mineral': 'ミネラル',
            'floral': 'フローラル',
            'rose': 'ローズ',
            'lavender': 'ラベンダー',
            'heather': 'ヘザー',
            'fresh': 'フレッシュ',
            'crisp': 'クリスプ',
            'smooth': 'スムース',
            'rich': 'リッチ',
            'full-bodied': 'フルボディ',
            'light': 'ライト',
            'delicate': 'デリケート',
            'complex': 'コンプレックス',
            'balanced': 'バランス',
            'elegant': 'エレガント',
            'robust': 'ロバスト',
            'mellow': 'メロウ',
            'warming': 'ウォーミング',
            'dry': 'ドライ',
            'sweet': 'スイート',
            'bitter': 'ビター',
            'spicy': 'スパイシー',
            'creamy': 'クリーミー',
            'oily': 'オイリー',
            'waxy': 'ワクシー',
            'silky': 'シルキー',
            'velvety': 'ベルベティ',
            'long': 'ロング',
            'short': 'ショート',
            'finish': 'フィニッシュ',
            'aftertaste': 'アフターテイスト',
            'lingering': 'リンガリング'
        }
        
        # 逆引き辞書（日本語→英語）
        self.reverse_dictionary = {v: k for k, v in self.manual_dictionary.items()}
    
    def translate_to_japanese(self, english_text: str, use_cache: bool = True) -> str:
        """英語テキストを日本語に翻訳"""
        if not english_text:
            return ''
        
        # まず手動辞書をチェック
        manual_translation = self._check_manual_dictionary(english_text.lower())
        if manual_translation:
            return manual_translation
        
        # キャッシュをチェック
        if use_cache:
            cached_result = self.cache_service.get_translation(english_text, 'en', 'ja')
            if cached_result:
                return cached_result
        
        # AWS Translateを使用
        try:
            response = self.translate_client.translate_text(
                Text=english_text,
                SourceLanguageCode='en',
                TargetLanguageCode='ja'
            )
            
            translated_text = response['TranslatedText']
            
            # キャッシュに保存
            if use_cache:
                self.cache_service.set_translation(english_text, 'en', 'ja', translated_text)
            
            return translated_text
            
        except Exception as e:
            logger.error(f"Translation error: {e}")
            return english_text  # 翻訳失敗時は元のテキストを返す
    
    def translate_to_english(self, japanese_text: str, use_cache: bool = True) -> str:
        """日本語テキストを英語に翻訳"""
        if not japanese_text:
            return ''
        
        # まず逆引き辞書をチェック
        manual_translation = self.reverse_dictionary.get(japanese_text)
        if manual_translation:
            return manual_translation
        
        # キャッシュをチェック
        if use_cache:
            cached_result = self.cache_service.get_translation(japanese_text, 'ja', 'en')
            if cached_result:
                return cached_result
        
        # AWS Translateを使用
        try:
            response = self.translate_client.translate_text(
                Text=japanese_text,
                SourceLanguageCode='ja',
                TargetLanguageCode='en'
            )
            
            translated_text = response['TranslatedText']
            
            # キャッシュに保存
            if use_cache:
                self.cache_service.set_translation(japanese_text, 'ja', 'en', translated_text)
            
            return translated_text
            
        except Exception as e:
            logger.error(f"Translation error: {e}")
            return japanese_text  # 翻訳失敗時は元のテキストを返す
    
    def _check_manual_dictionary(self, text: str) -> Optional[str]:
        """手動辞書から翻訳を検索"""
        # 完全一致
        if text in self.manual_dictionary:
            return self.manual_dictionary[text]
        
        # 部分一致（単語単位）
        words = text.replace('-', ' ').replace('_', ' ').split()
        translated_words = []
        
        for word in words:
            if word in self.manual_dictionary:
                translated_words.append(self.manual_dictionary[word])
            else:
                translated_words.append(word)
        
        # すべての単語が翻訳できた場合のみ結果を返す
        if any(word in self.manual_dictionary for word in words):
            return ' '.join(translated_words)
        
        return None
    
    
    def batch_translate_whiskey_data(self, whiskey_list: list, rate_limit_seconds: float = 0.5) -> list:
        """ウイスキーデータを一括翻訳（レート制限付き）"""
        translated_list = []
        
        for whiskey_data in whiskey_list:
            try:
                # 名前を翻訳
                name_ja = self.translate_to_japanese(whiskey_data.get('name', ''))
                
                # 蒸留所名を翻訳  
                distillery_ja = self.translate_to_japanese(whiskey_data.get('distillery', ''))
                
                # 説明を翻訳（長い場合は省略）
                description = whiskey_data.get('description', '')
                description_ja = ''
                if description and len(description) < 500:  # 長すぎる場合は翻訳しない
                    description_ja = self.translate_to_japanese(description)
                
                # 翻訳結果を追加
                translated_data = whiskey_data.copy()
                translated_data['name_ja'] = name_ja
                translated_data['distillery_ja'] = distillery_ja
                translated_data['description_ja'] = description_ja
                
                translated_list.append(translated_data)
                
                # レート制限
                if rate_limit_seconds > 0:
                    time.sleep(rate_limit_seconds)
                
            except Exception as e:
                logger.error(f"Error translating whiskey data: {e}")
                # エラーの場合も元データを保持
                translated_list.append(whiskey_data)
                continue
        
        return translated_list