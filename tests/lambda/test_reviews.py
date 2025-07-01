"""
Tests for Reviews Lambda Function
レビューLambda関数のテスト
"""
import pytest
import json
import jwt
import base64
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta
from decimal import Decimal

# テスト対象のimport
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..', 'lambda', 'reviews'))

from index import lambda_handler, get_user_id_from_token, decimal_default


class TestJWTSecurity:
    """JWT認証のセキュリティテスト"""
    
    def test_jwt_security_fix_rejects_forged_tokens(self):
        """セキュリティ修正により偽造トークンが拒否されることをテスト"""
        # 偽造されたJWTトークン（署名なし）
        fake_payload = {
            "sub": "fake-user-123",
            "email": "fake@example.com",
            "exp": int((datetime.utcnow() + timedelta(hours=1)).timestamp())
        }
        
        # Base64エンコードで偽造トークンを作成
        fake_header = base64.b64encode(json.dumps({"alg": "none", "typ": "JWT"}).encode()).decode().rstrip('=')
        fake_payload_encoded = base64.b64encode(json.dumps(fake_payload).encode()).decode().rstrip('=')
        fake_signature = ""
        
        fake_token = f"{fake_header}.{fake_payload_encoded}.{fake_signature}"
        
        # テストイベント作成
        event = {
            'headers': {
                'Authorization': f'Bearer {fake_token}'
            },
            'requestContext': {}
        }
        
        # セキュリティ修正により偽造トークンは拒否される
        user_id = get_user_id_from_token(event)
        
        # 偽造トークンは適切に拒否されてNoneが返されるべき
        assert user_id is None  # セキュリティ修正の確認
    
    def test_malformed_jwt_handling(self):
        """不正な形式のJWTの処理をテスト"""
        test_cases = [
            "",  # 空文字
            "invalid.token",  # 不正な形式
            "header.payload",  # 署名部分なし
            "a.b.c.d",  # 部分が多すぎる
        ]
        
        for invalid_token in test_cases:
            event = {
                'headers': {
                    'Authorization': f'Bearer {invalid_token}'
                },
                'requestContext': {}
            }
            
            user_id = get_user_id_from_token(event)
            assert user_id is None
    
    def test_missing_authorization_header(self):
        """認証ヘッダーがない場合のテスト"""
        event = {
            'headers': {},
            'requestContext': {}
        }
        
        user_id = get_user_id_from_token(event)
        assert user_id is None


class TestUtilityFunctions:
    """ユーティリティ関数のテスト"""
    
    def test_decimal_default_converter(self):
        """Decimal型変換のテスト"""
        test_cases = [
            (Decimal('10.5'), 10.5),
            (Decimal('100'), 100.0),
            (datetime(2023, 1, 1, 12, 0, 0), '2023-01-01T12:00:00'),
        ]
        
        for input_val, expected in test_cases:
            result = decimal_default(input_val)
            assert result == expected
    
    def test_decimal_default_invalid_type(self):
        """無効な型でのDecimal変換エラーテスト"""
        with pytest.raises(TypeError):
            decimal_default("invalid_type")


class TestLambdaHandler:
    """Lambda handler統合テスト"""
    
    @patch('boto3.resource')
    def test_cors_headers(self, mock_boto3):
        """CORS ヘッダーの設定テスト"""
        # DynamoDBモックセットアップ
        mock_dynamodb = Mock()
        mock_boto3.return_value = mock_dynamodb
        
        event = {
            'httpMethod': 'GET',
            'path': '/api/reviews',
            'headers': {
                'origin': 'https://dev.whiskeybar.site'
            },
            'queryStringParameters': {'public': 'true'},
            'requestContext': {}
        }
        
        # テーブルモックを設定
        mock_table = Mock()
        mock_table.scan.return_value = {'Items': []}
        mock_dynamodb.Table.return_value = mock_table
        
        with patch.dict(os.environ, {
            'REVIEWS_TABLE': 'Reviews-test',
            'WHISKEYS_TABLE': 'Whiskeys-test'
        }):
            response = lambda_handler(event, {})
        
        # CORS ヘッダーの確認
        assert 'Access-Control-Allow-Origin' in response['headers']
        assert response['headers']['Access-Control-Allow-Origin'] == 'https://dev.whiskeybar.site'
        assert response['headers']['Access-Control-Allow-Methods'] == 'GET, POST, PUT, DELETE, OPTIONS'
    
    @patch('boto3.resource')
    def test_unauthorized_access(self, mock_boto3):
        """認証なしでのアクセステスト"""
        event = {
            'httpMethod': 'POST',
            'path': '/api/reviews',
            'headers': {},
            'body': json.dumps({
                'whiskey_name': 'Test Whiskey',
                'rating': 5,
                'notes': 'Great whiskey'
            }),
            'requestContext': {}
        }
        
        with patch.dict(os.environ, {
            'REVIEWS_TABLE': 'Reviews-test',
            'WHISKEYS_TABLE': 'Whiskeys-test'
        }):
            response = lambda_handler(event, {})
        
        # 認証が必要なアクションは401エラーを返すべき
        assert response['statusCode'] == 401
        assert 'Authentication required' in json.loads(response['body'])['error']


def create_valid_cognito_jwt(user_id: str, secret: str = "test-secret") -> str:
    """テスト用の有効なCognito JWTトークンを作成"""
    payload = {
        "sub": user_id,
        "email": f"{user_id}@example.com",
        "cognito:username": user_id,
        "token_use": "access",
        "scope": "aws.cognito.signin.user.admin",
        "auth_time": int(datetime.utcnow().timestamp()),
        "iss": "https://cognito-idp.ap-northeast-1.amazonaws.com/ap-northeast-1_test",
        "exp": int((datetime.utcnow() + timedelta(hours=1)).timestamp()),
        "iat": int(datetime.utcnow().timestamp()),
        "client_id": "test-client-id"
    }
    
    return jwt.encode(payload, secret, algorithm="HS256")


class TestSecureJWTValidation:
    """安全なJWT検証の実装テスト（修正後の実装）"""
    
    @patch.dict(os.environ, {
        'COGNITO_USER_POOL_ID': 'ap-northeast-1_testpool',
        'AWS_REGION': 'ap-northeast-1'
    })
    @patch('sys.path')
    def test_secure_jwt_implementation_used(self, mock_path):
        """新しい安全なJWT実装が使用されることをテスト"""
        # jwt_utilsのパスを追加
        jwt_utils_path = os.path.join(os.path.dirname(__file__), '..', '..', 'lambda', 'reviews')
        mock_path.append.return_value = None
        sys.path.append(jwt_utils_path)
        
        # モックした安全な検証関数
        with patch('jwt_utils.extract_user_id_from_token') as mock_extract:
            mock_extract.return_value = "secure-user-123"
            
            event = {
                'headers': {'Authorization': 'Bearer valid.jwt.token'},
                'requestContext': {}
            }
            
            user_id = get_user_id_from_token(event)
            
            # 安全な関数が呼ばれることを確認
            mock_extract.assert_called_once_with(event)
            assert user_id == "secure-user-123"
    
    def test_legacy_implementation_fallback(self):
        """jwt_utilsが利用できない場合のフォールバック動作をテスト"""
        # jwt_utilsをimportできない状況をシミュレート
        with patch('builtins.__import__', side_effect=ImportError("No module named 'jwt_utils'")):
            event = {
                'headers': {'Authorization': 'Bearer fake.jwt.token'},
                'requestContext': {}
            }
            
            # フォールバック実装が動作することを確認
            # （元の脆弱な実装が呼ばれる）
            user_id = get_user_id_from_token(event)
            # フォールバック時は None が返される（不正なトークンのため）
            assert user_id is None
    
    @patch.dict(os.environ, {
        'COGNITO_USER_POOL_ID': 'ap-northeast-1_testpool',
        'AWS_REGION': 'ap-northeast-1'
    })
    def test_invalid_signature_rejection_with_mock(self):
        """無効な署名のJWTが拒否されることを確認（モック使用）"""
        with patch('jwt_utils.verify_cognito_jwt') as mock_verify:
            # 無効な署名の場合はNoneを返す
            mock_verify.return_value = None
            
            with patch('jwt_utils.extract_user_id_from_token') as mock_extract:
                mock_extract.return_value = None
                
                event = {
                    'headers': {'Authorization': 'Bearer invalid.signature.token'},
                    'requestContext': {}
                }
                
                user_id = get_user_id_from_token(event)
                assert user_id is None


if __name__ == "__main__":
    pytest.main([__file__])