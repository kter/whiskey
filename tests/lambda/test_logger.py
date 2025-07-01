"""
Tests for Lambda Logger Utility
Lambda ロガーユーティリティのテスト
"""
import pytest
import json
import os
import sys
from unittest.mock import Mock, patch
from io import StringIO
from datetime import datetime

# テスト対象のimport
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..', 'lambda', 'common'))

try:
    from logger import LambdaLogger, LogLevel, get_logger, extract_correlation_id
except ImportError as e:
    pytest.skip(f"Logger module not available: {e}", allow_module_level=True)


class TestLambdaLogger:
    """Lambda ロガーの基本機能テスト"""
    
    def test_logger_initialization(self):
        """ロガーの初期化テスト"""
        logger = LambdaLogger(
            function_name='test-function',
            log_level=LogLevel.INFO,
            correlation_id='test-correlation-123'
        )
        
        assert logger.function_name == 'test-function'
        assert logger.log_level == LogLevel.INFO
        assert logger.correlation_id == 'test-correlation-123'
        assert logger.environment == os.environ.get('ENVIRONMENT', 'dev')
    
    def test_logger_initialization_from_string(self):
        """文字列からのログレベル初期化テスト"""
        logger = LambdaLogger(log_level='DEBUG')
        assert logger.log_level == LogLevel.DEBUG
    
    def test_logger_initialization_from_env(self):
        """環境変数からの初期化テスト"""
        with patch.dict(os.environ, {
            'AWS_LAMBDA_FUNCTION_NAME': 'env-function',
            'ENVIRONMENT': 'test'
        }):
            logger = LambdaLogger()
            assert logger.function_name == 'env-function'
            assert logger.environment == 'test'
    
    @patch('sys.stdout', new_callable=StringIO)
    def test_basic_logging(self, mock_stdout):
        """基本的なログ出力テスト"""
        logger = LambdaLogger(
            function_name='test-function',
            log_level=LogLevel.DEBUG
        )
        
        logger.info("Test message", test_key="test_value")
        
        output = mock_stdout.getvalue()
        assert output
        
        # JSON形式であることを確認
        log_data = json.loads(output.strip())
        assert log_data['level'] == 'INFO'
        assert log_data['function'] == 'test-function'
        assert log_data['message'] == 'Test message'
        assert log_data['details']['test_key'] == 'test_value'
        assert 'timestamp' in log_data
    
    @patch('sys.stdout', new_callable=StringIO)
    def test_log_level_filtering(self, mock_stdout):
        """ログレベルフィルタリングテスト"""
        logger = LambdaLogger(log_level=LogLevel.WARNING)
        
        # DEBUGレベルのログは出力されない
        logger.debug("Debug message")
        assert mock_stdout.getvalue() == ""
        
        # WARNINGレベルのログは出力される
        logger.warning("Warning message")
        output = mock_stdout.getvalue()
        assert "Warning message" in output
    
    @patch('sys.stdout', new_callable=StringIO)
    def test_correlation_id_inclusion(self, mock_stdout):
        """相関ID含有テスト"""
        logger = LambdaLogger(correlation_id='test-correlation-456')
        
        logger.info("Test message")
        
        output = mock_stdout.getvalue()
        log_data = json.loads(output.strip())
        assert log_data['correlation_id'] == 'test-correlation-456'
    
    @patch('sys.stdout', new_callable=StringIO)
    def test_child_logger_creation(self, mock_stdout):
        """子ロガー作成テスト"""
        parent_logger = LambdaLogger(
            function_name='parent',
            correlation_id='test-correlation'
        )
        
        child_logger = parent_logger.create_child_logger('child-component')
        child_logger.info("Child message")
        
        output = mock_stdout.getvalue()
        log_data = json.loads(output.strip())
        assert log_data['function'] == 'parent.child-component'
        assert log_data['correlation_id'] == 'test-correlation'
    
    def test_correlation_id_update(self):
        """相関ID更新テスト"""
        logger = LambdaLogger()
        
        logger.set_correlation_id('new-correlation-789')
        assert logger.correlation_id == 'new-correlation-789'


class TestSpecializedLoggingMethods:
    """特殊なログメソッドのテスト"""
    
    @patch('sys.stdout', new_callable=StringIO)
    def test_api_request_logging(self, mock_stdout):
        """APIリクエストログテスト"""
        logger = LambdaLogger()
        
        logger.log_api_request(
            method='POST',
            path='/api/reviews',
            query_params={'public': 'true'},
            user_id='user-123'
        )
        
        output = mock_stdout.getvalue()
        log_data = json.loads(output.strip())
        assert log_data['message'] == 'API request received'
        assert log_data['details']['method'] == 'POST'
        assert log_data['details']['path'] == '/api/reviews'
        assert log_data['details']['user_id'] == 'user-123'
    
    @patch('sys.stdout', new_callable=StringIO)
    def test_api_response_logging(self, mock_stdout):
        """APIレスポンスログテスト"""
        logger = LambdaLogger()
        
        # 成功レスポンス
        logger.log_api_response(
            status_code=200,
            response_size=1024,
            duration_ms=150.5
        )
        
        output = mock_stdout.getvalue()
        log_data = json.loads(output.strip())
        assert log_data['level'] == 'INFO'
        assert log_data['details']['status_code'] == 200
        assert log_data['details']['duration_ms'] == 150.5
    
    @patch('sys.stdout', new_callable=StringIO)
    def test_api_error_response_logging(self, mock_stdout):
        """APIエラーレスポンスログテスト"""
        logger = LambdaLogger()
        
        # エラーレスポンス
        logger.log_api_response(
            status_code=500,
            duration_ms=75.2
        )
        
        output = mock_stdout.getvalue()
        log_data = json.loads(output.strip())
        assert log_data['level'] == 'ERROR'
        assert log_data['details']['status_code'] == 500
    
    @patch('sys.stdout', new_callable=StringIO)
    def test_database_operation_logging(self, mock_stdout):
        """データベース操作ログテスト"""
        logger = LambdaLogger()
        
        logger.log_database_operation(
            operation='scan',
            table_name='Reviews-dev',
            item_count=25,
            duration_ms=120.0
        )
        
        output = mock_stdout.getvalue()
        log_data = json.loads(output.strip())
        assert log_data['message'] == 'Database scan'
        assert log_data['details']['table_name'] == 'Reviews-dev'
        assert log_data['details']['item_count'] == 25
    
    @patch('sys.stdout', new_callable=StringIO)
    def test_database_error_logging(self, mock_stdout):
        """データベースエラーログテスト"""
        logger = LambdaLogger()
        
        logger.log_database_operation(
            operation='put_item',
            table_name='Reviews-dev',
            error='Table does not exist'
        )
        
        output = mock_stdout.getvalue()
        log_data = json.loads(output.strip())
        assert log_data['level'] == 'ERROR'
        assert log_data['details']['error'] == 'Table does not exist'
    
    @patch('sys.stdout', new_callable=StringIO)
    def test_search_operation_logging(self, mock_stdout):
        """検索操作ログテスト"""
        logger = LambdaLogger()
        
        logger.log_search_operation(
            query='響',
            result_count=5,
            duration_ms=89.3,
            search_type='whiskey_search'
        )
        
        output = mock_stdout.getvalue()
        log_data = json.loads(output.strip())
        assert log_data['message'] == 'Search operation completed'
        assert log_data['details']['query'] == '響'
        assert log_data['details']['result_count'] == 5
        assert log_data['details']['search_type'] == 'whiskey_search'
    
    @patch('sys.stdout', new_callable=StringIO)
    def test_long_query_truncation(self, mock_stdout):
        """長いクエリの切り詰めテスト"""
        logger = LambdaLogger()
        
        long_query = 'a' * 60  # 60文字のクエリ
        logger.log_search_operation(
            query=long_query,
            result_count=0
        )
        
        output = mock_stdout.getvalue()
        log_data = json.loads(output.strip())
        # 50文字で切り詰められて "..." が追加される
        assert log_data['details']['query'] == 'a' * 50 + '...'
    
    @patch('sys.stdout', new_callable=StringIO)
    def test_jwt_operation_logging(self, mock_stdout):
        """JWT操作ログテスト"""
        logger = LambdaLogger()
        
        # 成功ケース
        logger.log_jwt_operation(
            operation='validate',
            user_id='user-456',
            success=True
        )
        
        output = mock_stdout.getvalue()
        log_data = json.loads(output.strip())
        assert log_data['level'] == 'INFO'
        assert log_data['message'] == 'JWT validate'
        assert log_data['details']['success'] is True
    
    @patch('sys.stdout', new_callable=StringIO)
    def test_jwt_error_logging(self, mock_stdout):
        """JWTエラーログテスト"""
        logger = LambdaLogger()
        
        # 失敗ケース
        logger.log_jwt_operation(
            operation='decode',
            success=False,
            error='Invalid signature'
        )
        
        output = mock_stdout.getvalue()
        log_data = json.loads(output.strip())
        assert log_data['level'] == 'WARNING'
        assert log_data['details']['success'] is False
        assert log_data['details']['error'] == 'Invalid signature'


class TestUtilityFunctions:
    """ユーティリティ関数のテスト"""
    
    def test_get_logger_function(self):
        """get_logger関数のテスト"""
        logger = get_logger(
            function_name='test-func',
            log_level='DEBUG',
            correlation_id='test-123'
        )
        
        assert isinstance(logger, LambdaLogger)
        assert logger.function_name == 'test-func'
        assert logger.correlation_id == 'test-123'
    
    def test_get_logger_with_env_log_level(self):
        """環境変数からのログレベル取得テスト"""
        with patch.dict(os.environ, {'LOG_LEVEL': 'ERROR'}):
            logger = get_logger()
            assert logger.log_level == LogLevel.ERROR
    
    def test_extract_correlation_id_from_api_gateway(self):
        """API Gatewayイベントからの相関ID抽出テスト"""
        event = {
            'requestContext': {
                'requestId': 'api-gateway-request-123'
            }
        }
        
        correlation_id = extract_correlation_id(event)
        assert correlation_id == 'api-gateway-request-123'
    
    def test_extract_correlation_id_fallback(self):
        """相関ID抽出のフォールバックテスト"""
        event = {
            'correlation_id': 'custom-correlation-456'
        }
        
        correlation_id = extract_correlation_id(event)
        assert correlation_id == 'custom-correlation-456'
    
    def test_extract_correlation_id_none(self):
        """相関IDが存在しない場合のテスト"""
        event = {}
        
        correlation_id = extract_correlation_id(event)
        assert correlation_id is None


class TestLogDataSerialization:
    """ログデータシリアライゼーションのテスト"""
    
    @patch('sys.stdout', new_callable=StringIO)
    def test_datetime_serialization(self, mock_stdout):
        """datetime オブジェクトのシリアライゼーションテスト"""
        logger = LambdaLogger()
        
        test_datetime = datetime(2025, 1, 1, 12, 0, 0)
        logger.info("Test with datetime", timestamp=test_datetime)
        
        output = mock_stdout.getvalue()
        # JSON として正常にパースできることを確認
        log_data = json.loads(output.strip())
        assert 'timestamp' in log_data['details']
    
    @patch('sys.stdout', new_callable=StringIO)
    def test_complex_object_serialization(self, mock_stdout):
        """複雑なオブジェクトのシリアライゼーションテスト"""
        logger = LambdaLogger()
        
        complex_data = {
            'nested': {'key': 'value'},
            'list': [1, 2, 3],
            'none_value': None
        }
        
        logger.info("Test with complex data", data=complex_data)
        
        output = mock_stdout.getvalue()
        log_data = json.loads(output.strip())
        assert log_data['details']['data']['nested']['key'] == 'value'
        assert log_data['details']['data']['list'] == [1, 2, 3]


if __name__ == "__main__":
    pytest.main([__file__])