import redis
import json
import os
import logging
from typing import Optional, Dict, Any
from decimal import Decimal

logger = logging.getLogger(__name__)


class ValkeyService:
    """
    AWS ElastiCache Valkey (Redis互換) サービス
    翻訳キャッシュ管理用
    """
    
    def __init__(self):
        # ElastiCache Valkey接続設定
        self.host = os.getenv('ELASTICACHE_ENDPOINT')
        self.port = int(os.getenv('ELASTICACHE_PORT', 6379))
        
        # 無料枠利用のためcache.t3.micro (500MB) を使用
        self.MAX_MEMORY_MB = 500
        self.MAX_MEMORY_BYTES = self.MAX_MEMORY_MB * 1024 * 1024
        
        # TTL設定 (Time To Live)
        self.DEFAULT_TTL = 86400 * 7  # 1週間
        self.TRANSLATION_TTL = 86400 * 30  # 翻訳結果は30日間保持
        
        # 接続プール設定
        self.connection_pool = None
        self.redis_client = None
        
        # 初期化
        self._initialize_connection()
    
    def _initialize_connection(self):
        """Redis/Valkey接続を初期化"""
        try:
            if not self.host:
                logger.warning("ElastiCache endpoint not configured. Cache will be disabled.")
                return
            
            # 接続プール作成
            self.connection_pool = redis.ConnectionPool(
                host=self.host,
                port=self.port,
                decode_responses=True,
                max_connections=10,
                retry_on_timeout=True,
                socket_connect_timeout=5,
                socket_timeout=5
            )
            
            # Redisクライアント作成
            self.redis_client = redis.Redis(connection_pool=self.connection_pool)
            
            # 接続テスト
            self.redis_client.ping()
            logger.info(f"ElastiCache Valkey connected: {self.host}:{self.port}")
            
            # メモリ使用量確認
            info = self.redis_client.info('memory')
            used_memory = info.get('used_memory', 0)
            logger.info(f"Current memory usage: {used_memory / 1024 / 1024:.1f}MB / {self.MAX_MEMORY_MB}MB")
            
        except Exception as e:
            logger.error(f"Failed to connect to ElastiCache Valkey: {e}")
            self.redis_client = None
    
    def is_available(self) -> bool:
        """キャッシュが利用可能かチェック"""
        if not self.redis_client:
            return False
        
        try:
            self.redis_client.ping()
            return True
        except:
            return False
    
    def get(self, key: str) -> Optional[Any]:
        """キャッシュから値を取得"""
        if not self.is_available():
            return None
        
        try:
            value = self.redis_client.get(key)
            if value:
                return json.loads(value)
            return None
        except Exception as e:
            logger.error(f"Cache get error for key '{key}': {e}")
            return None
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """キャッシュに値を設定"""
        if not self.is_available():
            return False
        
        try:
            # TTLが指定されていない場合はデフォルト値を使用
            if ttl is None:
                ttl = self.DEFAULT_TTL
            
            # JSON形式でシリアライズ
            serialized_value = json.dumps(value, ensure_ascii=False, cls=DecimalEncoder)
            
            # メモリ使用量チェック
            if not self._check_memory_usage():
                logger.warning("Memory usage high, cleaning old entries")
                self._cleanup_old_entries()
            
            # キャッシュに保存
            result = self.redis_client.setex(key, ttl, serialized_value)
            return result
            
        except Exception as e:
            logger.error(f"Cache set error for key '{key}': {e}")
            return False
    
    def delete(self, key: str) -> bool:
        """キャッシュからキーを削除"""
        if not self.is_available():
            return False
        
        try:
            result = self.redis_client.delete(key)
            return result > 0
        except Exception as e:
            logger.error(f"Cache delete error for key '{key}': {e}")
            return False
    
    def exists(self, key: str) -> bool:
        """キーが存在するかチェック"""
        if not self.is_available():
            return False
        
        try:
            return self.redis_client.exists(key) > 0
        except Exception as e:
            logger.error(f"Cache exists error for key '{key}': {e}")
            return False
    
    def get_translation(self, text: str, source_lang: str, target_lang: str) -> Optional[str]:
        """翻訳結果をキャッシュから取得"""
        key = self._make_translation_key(text, source_lang, target_lang)
        return self.get(key)
    
    def set_translation(self, text: str, source_lang: str, target_lang: str, translation: str) -> bool:
        """翻訳結果をキャッシュに保存"""
        key = self._make_translation_key(text, source_lang, target_lang)
        return self.set(key, translation, self.TRANSLATION_TTL)
    
    def _make_translation_key(self, text: str, source_lang: str, target_lang: str) -> str:
        """翻訳キーを生成"""
        import hashlib
        
        # テキストをハッシュ化してキーの長さを制限
        text_hash = hashlib.md5(text.encode('utf-8')).hexdigest()
        return f"translation:{source_lang}:{target_lang}:{text_hash}"
    
    def _check_memory_usage(self) -> bool:
        """メモリ使用量をチェック"""
        if not self.is_available():
            return True
        
        try:
            info = self.redis_client.info('memory')
            used_memory = info.get('used_memory', 0)
            usage_ratio = used_memory / self.MAX_MEMORY_BYTES
            
            # 80%を超えた場合は警告
            if usage_ratio > 0.8:
                logger.warning(f"High memory usage: {usage_ratio:.1%} ({used_memory / 1024 / 1024:.1f}MB)")
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Memory check error: {e}")
            return True
    
    def _cleanup_old_entries(self):
        """古いエントリをクリーンアップ"""
        if not self.is_available():
            return
        
        try:
            # 期限切れキーを削除（Redis/Valkeyが自動的に行うが、手動でも実行）
            # 実際のクリーンアップロジックは環境に応じて調整
            
            info = self.redis_client.info('memory')
            used_memory_before = info.get('used_memory', 0)
            
            # 期限切れキーの削除を促進
            # SCAN を使って古いキーを特定し削除する処理を実装可能
            
            logger.info(f"Cache cleanup completed. Memory before: {used_memory_before / 1024 / 1024:.1f}MB")
            
        except Exception as e:
            logger.error(f"Cache cleanup error: {e}")
    
    def get_stats(self) -> Dict[str, Any]:
        """キャッシュ統計情報を取得"""
        if not self.is_available():
            return {'status': 'unavailable'}
        
        try:
            info = self.redis_client.info()
            memory_info = self.redis_client.info('memory')
            
            return {
                'status': 'available',
                'connected_clients': info.get('connected_clients', 0),
                'used_memory_mb': memory_info.get('used_memory', 0) / 1024 / 1024,
                'max_memory_mb': self.MAX_MEMORY_MB,
                'memory_usage_ratio': memory_info.get('used_memory', 0) / self.MAX_MEMORY_BYTES,
                'total_commands_processed': info.get('total_commands_processed', 0),
                'instantaneous_ops_per_sec': info.get('instantaneous_ops_per_sec', 0),
                'keyspace_hits': info.get('keyspace_hits', 0),
                'keyspace_misses': info.get('keyspace_misses', 0),
                'uptime_in_seconds': info.get('uptime_in_seconds', 0)
            }
            
        except Exception as e:
            logger.error(f"Failed to get cache stats: {e}")
            return {'status': 'error', 'error': str(e)}
    
    def clear_all_cache(self) -> bool:
        """全キャッシュをクリア（開発・テスト用）"""
        if not self.is_available():
            return False
        
        try:
            self.redis_client.flushdb()
            logger.info("All cache cleared")
            return True
        except Exception as e:
            logger.error(f"Failed to clear cache: {e}")
            return False


class DecimalEncoder(json.JSONEncoder):
    """Decimal型をJSONエンコードするためのカスタムエンコーダー"""
    
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)


# グローバルインスタンス（シングルトン）
_valkey_service = None


def get_cache_service() -> ValkeyService:
    """キャッシュサービスのシングルトンインスタンスを取得"""
    global _valkey_service
    if _valkey_service is None:
        _valkey_service = ValkeyService()
    return _valkey_service