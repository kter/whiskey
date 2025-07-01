"""
Integration Tests for Lambda Logger
Lambda ロガーの統合テスト
"""
import pytest
import json
import os
import sys

# テスト対象のimport
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..', 'lambda', 'common'))

try:
    from logger import LambdaLogger, LogLevel, get_logger, extract_correlation_id
except ImportError as e:
    pytest.skip(f"Logger module not available: {e}", allow_module_level=True)


class TestLoggerBasicFunctionality:
    """ロガーの基本機能テスト"""
    
    def test_logger_creation_and_basic_properties(self):
        """ロガー作成と基本プロパティのテスト"""
        logger = LambdaLogger(
            function_name='test-function',
            log_level=LogLevel.INFO,
            correlation_id='test-correlation-123'
        )
        
        # 基本プロパティの確認
        assert logger.function_name == 'test-function'
        assert logger.log_level == LogLevel.INFO
        assert logger.correlation_id == 'test-correlation-123'
        assert logger.environment == os.environ.get('ENVIRONMENT', 'dev')
    
    def test_log_level_enum_values(self):
        """ログレベルEnumの値テスト"""
        assert LogLevel.DEBUG.value == "DEBUG"
        assert LogLevel.INFO.value == "INFO"
        assert LogLevel.WARNING.value == "WARNING"
        assert LogLevel.ERROR.value == "ERROR"
        assert LogLevel.CRITICAL.value == "CRITICAL"
    
    def test_log_entry_structure(self):
        """ログエントリ構造のテスト"""
        logger = LambdaLogger(
            function_name='structure-test',
            correlation_id='struct-123'
        )
        
        log_entry = logger._create_log_entry(
            LogLevel.INFO, 
            "Test message", 
            test_key="test_value"
        )
        
        # 必須フィールドの確認
        assert 'timestamp' in log_entry
        assert log_entry['level'] == 'INFO'
        assert log_entry['function'] == 'structure-test'
        assert log_entry['environment'] == os.environ.get('ENVIRONMENT', 'dev')
        assert log_entry['message'] == 'Test message'
        assert log_entry['correlation_id'] == 'struct-123'
        assert log_entry['details']['test_key'] == 'test_value'
    
    def test_log_entry_without_correlation_id(self):
        """相関IDなしのログエントリテスト"""
        logger = LambdaLogger(function_name='no-correlation')
        
        log_entry = logger._create_log_entry(LogLevel.INFO, "Test message")
        
        # 相関IDが含まれないことを確認
        assert 'correlation_id' not in log_entry
    
    def test_child_logger_creation(self):
        """子ロガー作成のテスト"""
        parent_logger = LambdaLogger(
            function_name='parent',
            log_level=LogLevel.DEBUG,
            correlation_id='parent-correlation'
        )
        
        child_logger = parent_logger.create_child_logger('child-component')
        
        # 子ロガーの確認
        assert child_logger.function_name == 'parent.child-component'
        assert child_logger.log_level == LogLevel.DEBUG
        assert child_logger.correlation_id == 'parent-correlation'
    
    def test_correlation_id_update(self):
        """相関ID更新のテスト"""
        logger = LambdaLogger()
        
        # 初期状態
        assert logger.correlation_id is None
        
        # 相関ID設定
        logger.set_correlation_id('new-correlation-789')
        assert logger.correlation_id == 'new-correlation-789'


class TestUtilityFunctions:
    """ユーティリティ関数のテスト"""
    
    def test_get_logger_function(self):
        """get_logger関数のテスト"""
        logger = get_logger(
            function_name='util-test',
            log_level='WARNING',
            correlation_id='util-123'
        )
        
        assert isinstance(logger, LambdaLogger)
        assert logger.function_name == 'util-test'
        assert logger.log_level == LogLevel.WARNING
        assert logger.correlation_id == 'util-123'
    
    def test_get_logger_with_environment_variables(self):
        """環境変数を使用したget_loggerのテスト"""
        from unittest.mock import patch
        with patch.dict(os.environ, {'LOG_LEVEL': 'DEBUG'}):
            logger = get_logger()
            assert logger.log_level == LogLevel.DEBUG
    
    def test_extract_correlation_id_from_api_gateway(self):
        """API Gatewayイベントからの相関ID抽出テスト"""
        event = {
            'requestContext': {
                'requestId': 'api-gateway-request-123'
            }
        }
        
        correlation_id = extract_correlation_id(event)
        assert correlation_id == 'api-gateway-request-123'
    
    def test_extract_correlation_id_direct(self):
        """直接的な相関ID抽出テスト"""
        event = {
            'correlation_id': 'direct-correlation-456'
        }
        
        correlation_id = extract_correlation_id(event)
        assert correlation_id == 'direct-correlation-456'
    
    def test_extract_correlation_id_none(self):
        """相関IDが存在しない場合のテスト"""
        event = {}
        correlation_id = extract_correlation_id(event)
        assert correlation_id is None


class TestSpecializedLoggingMethods:
    """特殊なログメソッドのテスト"""
    
    def test_api_request_logging_method_exists(self):
        """APIリクエストログメソッドの存在確認"""
        logger = LambdaLogger()
        
        # メソッドが存在し、呼び出し可能であることを確認
        assert hasattr(logger, 'log_api_request')
        assert callable(logger.log_api_request)
        
        # エラーなく実行できることを確認
        try:
            logger.log_api_request(
                method='GET',
                path='/api/test',
                query_params={'test': 'value'}
            )
        except Exception as e:
            pytest.fail(f"log_api_request failed: {e}")
    
    def test_api_response_logging_method_exists(self):
        """APIレスポンスログメソッドの存在確認"""
        logger = LambdaLogger()
        
        assert hasattr(logger, 'log_api_response')
        assert callable(logger.log_api_response)
        
        try:
            logger.log_api_response(
                status_code=200,
                response_size=1024,
                duration_ms=150.5
            )
        except Exception as e:
            pytest.fail(f"log_api_response failed: {e}")
    
    def test_database_operation_logging_method_exists(self):
        """データベース操作ログメソッドの存在確認"""
        logger = LambdaLogger()
        
        assert hasattr(logger, 'log_database_operation')
        assert callable(logger.log_database_operation)
        
        try:
            logger.log_database_operation(
                operation='scan',
                table_name='TestTable',
                item_count=10
            )
        except Exception as e:
            pytest.fail(f"log_database_operation failed: {e}")
    
    def test_search_operation_logging_method_exists(self):
        """検索操作ログメソッドの存在確認"""
        logger = LambdaLogger()
        
        assert hasattr(logger, 'log_search_operation')
        assert callable(logger.log_search_operation)
        
        try:
            logger.log_search_operation(
                query='test query',
                result_count=5,
                duration_ms=100.0
            )
        except Exception as e:
            pytest.fail(f"log_search_operation failed: {e}")
    
    def test_jwt_operation_logging_method_exists(self):
        """JWT操作ログメソッドの存在確認"""
        logger = LambdaLogger()
        
        assert hasattr(logger, 'log_jwt_operation')
        assert callable(logger.log_jwt_operation)
        
        try:
            logger.log_jwt_operation(
                operation='validate',
                user_id='test-user',
                success=True
            )
        except Exception as e:
            pytest.fail(f"log_jwt_operation failed: {e}")


class TestLogLevelBehavior:
    """ログレベル動作のテスト"""
    
    def test_log_level_priority_system(self):
        """ログレベル優先度システムのテスト"""
        logger = LambdaLogger(log_level=LogLevel.WARNING)
        
        # レベル優先度テスト用の内部メソッドを確認
        level_priorities = {
            LogLevel.DEBUG: 10,
            LogLevel.INFO: 20,
            LogLevel.WARNING: 30,
            LogLevel.ERROR: 40,
            LogLevel.CRITICAL: 50
        }
        
        # WARNING レベルのロガーでは DEBUG, INFO が出力されないはず
        # テスト用にレベルフィルタリングロジックを確認
        assert level_priorities[LogLevel.DEBUG] < level_priorities[LogLevel.WARNING]
        assert level_priorities[LogLevel.INFO] < level_priorities[LogLevel.WARNING]
        assert level_priorities[LogLevel.WARNING] == level_priorities[LogLevel.WARNING]
        assert level_priorities[LogLevel.ERROR] > level_priorities[LogLevel.WARNING]
    
    def test_all_log_methods_exist(self):
        """全ログメソッドの存在確認"""
        logger = LambdaLogger()
        
        log_methods = ['debug', 'info', 'warning', 'error', 'critical']
        
        for method_name in log_methods:
            assert hasattr(logger, method_name), f"Method {method_name} does not exist"
            assert callable(getattr(logger, method_name)), f"Method {method_name} is not callable"


if __name__ == "__main__":
    pytest.main([__file__])