"""
Structured Logging Utility for Lambda Functions
Lambda関数用構造化ログユーティリティ
"""
import json
import logging
import os
import sys
from datetime import datetime
from typing import Any, Dict, Optional, Union
from enum import Enum


class LogLevel(Enum):
    """ログレベル定義"""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class LambdaLogger:
    """
    Lambda関数用構造化ログクラス
    CloudWatchログとの互換性を考慮した設計
    """
    
    def __init__(self, 
                 function_name: Optional[str] = None,
                 log_level: Union[str, LogLevel] = LogLevel.INFO,
                 correlation_id: Optional[str] = None):
        """
        ロガーを初期化
        
        Args:
            function_name: Lambda関数名
            log_level: ログレベル
            correlation_id: 相関ID（リクエスト追跡用）
        """
        self.function_name = function_name or os.environ.get('AWS_LAMBDA_FUNCTION_NAME', 'unknown')
        self.environment = os.environ.get('ENVIRONMENT', 'dev')
        self.correlation_id = correlation_id
        
        # ログレベル設定
        if isinstance(log_level, str):
            log_level = LogLevel(log_level.upper())
        self.log_level = log_level
        
        # 標準ログ設定
        self.logger = logging.getLogger(self.function_name)
        self.logger.setLevel(getattr(logging, log_level.value))
        
        # ハンドラー設定（CloudWatch用）
        if not self.logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            handler.setFormatter(logging.Formatter('%(message)s'))
            self.logger.addHandler(handler)
    
    def _create_log_entry(self, 
                         level: LogLevel, 
                         message: str, 
                         **kwargs: Any) -> Dict[str, Any]:
        """
        構造化ログエントリを作成
        
        Args:
            level: ログレベル
            message: ログメッセージ
            **kwargs: 追加のログ情報
            
        Returns:
            構造化ログエントリ
        """
        log_entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": level.value,
            "function": self.function_name,
            "environment": self.environment,
            "message": message
        }
        
        # 相関IDを追加
        if self.correlation_id:
            log_entry["correlation_id"] = self.correlation_id
        
        # 追加情報を追加
        if kwargs:
            log_entry["details"] = kwargs
        
        return log_entry
    
    def _log(self, level: LogLevel, message: str, **kwargs: Any) -> None:
        """
        ログを出力
        
        Args:
            level: ログレベル
            message: ログメッセージ
            **kwargs: 追加のログ情報
        """
        # レベルフィルタリング
        level_priorities = {
            LogLevel.DEBUG: 10,
            LogLevel.INFO: 20,
            LogLevel.WARNING: 30,
            LogLevel.ERROR: 40,
            LogLevel.CRITICAL: 50
        }
        
        if level_priorities[level] < level_priorities[self.log_level]:
            return
        
        log_entry = self._create_log_entry(level, message, **kwargs)
        
        # JSON形式で出力（CloudWatch Logs用）
        self.logger.log(
            getattr(logging, level.value),
            json.dumps(log_entry, ensure_ascii=False, default=str)
        )
    
    def debug(self, message: str, **kwargs: Any) -> None:
        """デバッグログ"""
        self._log(LogLevel.DEBUG, message, **kwargs)
    
    def info(self, message: str, **kwargs: Any) -> None:
        """情報ログ"""
        self._log(LogLevel.INFO, message, **kwargs)
    
    def warning(self, message: str, **kwargs: Any) -> None:
        """警告ログ"""
        self._log(LogLevel.WARNING, message, **kwargs)
    
    def error(self, message: str, **kwargs: Any) -> None:
        """エラーログ"""
        self._log(LogLevel.ERROR, message, **kwargs)
    
    def critical(self, message: str, **kwargs: Any) -> None:
        """重大エラーログ"""
        self._log(LogLevel.CRITICAL, message, **kwargs)
    
    def log_api_request(self, 
                       method: str, 
                       path: str, 
                       query_params: Optional[Dict] = None,
                       user_id: Optional[str] = None) -> None:
        """
        APIリクエストログ
        
        Args:
            method: HTTPメソッド
            path: パス
            query_params: クエリパラメータ
            user_id: ユーザーID
        """
        self.info("API request received", 
                 method=method, 
                 path=path, 
                 query_params=query_params,
                 user_id=user_id)
    
    def log_api_response(self, 
                        status_code: int, 
                        response_size: Optional[int] = None,
                        duration_ms: Optional[float] = None) -> None:
        """
        APIレスポンスログ
        
        Args:
            status_code: HTTPステータスコード
            response_size: レスポンスサイズ
            duration_ms: 処理時間（ミリ秒）
        """
        level = LogLevel.INFO if status_code < 400 else LogLevel.ERROR
        self._log(level, f"API response sent", 
                 status_code=status_code,
                 response_size=response_size,
                 duration_ms=duration_ms)
    
    def log_database_operation(self, 
                              operation: str, 
                              table_name: str,
                              item_count: Optional[int] = None,
                              duration_ms: Optional[float] = None,
                              error: Optional[str] = None) -> None:
        """
        データベース操作ログ
        
        Args:
            operation: 操作種類（scan, query, put_item, etc.）
            table_name: テーブル名
            item_count: アイテム数
            duration_ms: 処理時間（ミリ秒）
            error: エラーメッセージ
        """
        level = LogLevel.ERROR if error else LogLevel.INFO
        self._log(level, f"Database {operation}",
                 table_name=table_name,
                 item_count=item_count,
                 duration_ms=duration_ms,
                 error=error)
    
    def log_search_operation(self, 
                           query: str,
                           result_count: int,
                           duration_ms: Optional[float] = None,
                           search_type: str = "standard") -> None:
        """
        検索操作ログ
        
        Args:
            query: 検索クエリ
            result_count: 結果件数
            duration_ms: 処理時間（ミリ秒）
            search_type: 検索タイプ
        """
        self.info("Search operation completed",
                 query=query[:50] + "..." if len(query) > 50 else query,  # クエリを切り詰め
                 result_count=result_count,
                 duration_ms=duration_ms,
                 search_type=search_type)
    
    def log_jwt_operation(self, 
                         operation: str,
                         user_id: Optional[str] = None,
                         success: bool = True,
                         error: Optional[str] = None) -> None:
        """
        JWT操作ログ
        
        Args:
            operation: 操作種類（validate, decode, etc.）
            user_id: ユーザーID
            success: 成功フラグ
            error: エラーメッセージ
        """
        level = LogLevel.INFO if success else LogLevel.WARNING
        self._log(level, f"JWT {operation}",
                 user_id=user_id,
                 success=success,
                 error=error)
    
    def set_correlation_id(self, correlation_id: str) -> None:
        """相関IDを設定"""
        self.correlation_id = correlation_id
    
    def create_child_logger(self, component: str) -> 'LambdaLogger':
        """
        子ロガーを作成（コンポーネント別ログ用）
        
        Args:
            component: コンポーネント名
            
        Returns:
            子ロガー
        """
        child_function_name = f"{self.function_name}.{component}"
        return LambdaLogger(
            function_name=child_function_name,
            log_level=self.log_level,
            correlation_id=self.correlation_id
        )


def get_logger(function_name: Optional[str] = None,
               log_level: Optional[str] = None,
               correlation_id: Optional[str] = None) -> LambdaLogger:
    """
    ロガーインスタンスを取得
    
    Args:
        function_name: Lambda関数名
        log_level: ログレベル（環境変数LOG_LEVELから自動取得）
        correlation_id: 相関ID
        
    Returns:
        ロガーインスタンス
    """
    if log_level is None:
        log_level = os.environ.get('LOG_LEVEL', 'INFO')
    
    return LambdaLogger(
        function_name=function_name,
        log_level=log_level,
        correlation_id=correlation_id
    )


def extract_correlation_id(event: Dict[str, Any]) -> Optional[str]:
    """
    Lambda eventから相関IDを抽出
    
    Args:
        event: Lambda event
        
    Returns:
        相関ID
    """
    # API Gateway の場合
    request_context = event.get('requestContext', {})
    request_id = request_context.get('requestId')
    
    if request_id:
        return request_id
    
    # その他のケース
    return event.get('correlation_id')