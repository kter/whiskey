"""
Tests for JWT Utilities
JWT ユーティリティのテスト
"""
import pytest
import json
import jwt
import os
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta

# テスト対象のimport
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..', 'lambda', 'reviews'))

# JWT utilsをimportするためのテスト
class TestJWTUtilsImport:
    """JWT ユーティリティのインポートとセットアップテスト"""
    
    def test_jwt_utils_import(self):
        """jwt_utils.pyが正常にインポートできることをテスト"""
        try:
            import jwt_utils
            assert hasattr(jwt_utils, 'verify_cognito_jwt')
            assert hasattr(jwt_utils, 'extract_user_id_from_token')
        except ImportError as e:
            pytest.fail(f"jwt_utils import failed: {e}")


@patch.dict(os.environ, {
    'COGNITO_USER_POOL_ID': 'ap-northeast-1_testpool',
    'AWS_REGION': 'ap-northeast-1'
})
class TestJWTUtilities:
    """JWT ユーティリティ関数のテスト"""
    
    @patch('requests.get')
    def test_get_cognito_jwks_success(self, mock_get):
        """JWKS取得の成功ケースをテスト"""
        import jwt_utils
        
        # モックレスポンスの設定
        mock_response = Mock()
        mock_response.json.return_value = {
            "keys": [
                {
                    "kid": "test-key-id",
                    "kty": "RSA",
                    "use": "sig",
                    "n": "test-n-value",
                    "e": "AQAB"
                }
            ]
        }
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response
        
        # キャッシュをクリア
        jwt_utils.get_cognito_jwks.cache_clear()
        
        # JWKS取得テスト
        jwks = jwt_utils.get_cognito_jwks()
        
        assert "keys" in jwks
        assert len(jwks["keys"]) == 1
        assert jwks["keys"][0]["kid"] == "test-key-id"
        
        # 正しいURLが呼ばれることを確認
        expected_url = "https://cognito-idp.ap-northeast-1.amazonaws.com/ap-northeast-1_testpool/.well-known/jwks.json"
        mock_get.assert_called_once_with(expected_url, timeout=10)
    
    @patch('requests.get')
    def test_get_cognito_jwks_failure(self, mock_get):
        """JWKS取得の失敗ケースをテスト"""
        import jwt_utils
        
        # リクエスト失敗をシミュレート
        mock_get.side_effect = Exception("Network error")
        
        # キャッシュをクリア
        jwt_utils.get_cognito_jwks.cache_clear()
        
        # 例外が発生することを確認
        with pytest.raises(Exception):
            jwt_utils.get_cognito_jwks()
    
    def test_verify_cognito_jwt_missing_environment(self):
        """環境変数が不足している場合のテスト"""
        import jwt_utils
        
        with patch.dict(os.environ, {}, clear=True):
            # キャッシュをクリア
            jwt_utils.get_cognito_jwks.cache_clear()
            
            # 環境変数が不足している場合はNoneが返されることを確認
            # （例外は内部でキャッチされる）
            result = jwt_utils.verify_cognito_jwt("dummy.token.here")
            assert result is None
    
    @patch('jwt_utils.get_signing_key')
    @patch('jwt.decode')
    def test_verify_cognito_jwt_valid_token(self, mock_jwt_decode, mock_get_key):
        """有効なトークンの検証テスト"""
        import jwt_utils
        
        # モックの設定
        mock_get_key.return_value = "mock-public-key"
        mock_jwt_decode.return_value = {
            "sub": "test-user-123",
            "token_use": "access",
            "iss": "https://cognito-idp.ap-northeast-1.amazonaws.com/ap-northeast-1_testpool",
            "exp": int((datetime.utcnow() + timedelta(hours=1)).timestamp())
        }
        
        # 有効なトークンの検証
        payload = jwt_utils.verify_cognito_jwt("valid.jwt.token")
        
        assert payload is not None
        assert payload["sub"] == "test-user-123"
        assert payload["token_use"] == "access"
        
        # 適切な引数でjwt.decodeが呼ばれることを確認
        mock_jwt_decode.assert_called_once_with(
            "valid.jwt.token",
            "mock-public-key",
            algorithms=['RS256'],
            options={
                'verify_signature': True,
                'verify_exp': True,
                'verify_iat': True,
                'verify_aud': False,
            }
        )
    
    @patch('jwt_utils.get_signing_key')
    @patch('jwt.decode')
    def test_verify_cognito_jwt_expired_token(self, mock_jwt_decode, mock_get_key):
        """期限切れトークンの検証テスト"""
        import jwt_utils
        
        # 期限切れ例外をシミュレート
        mock_jwt_decode.side_effect = jwt.ExpiredSignatureError("Token has expired")
        mock_get_key.return_value = "mock-public-key"
        
        # 期限切れトークンはNoneが返されることを確認
        payload = jwt_utils.verify_cognito_jwt("expired.jwt.token")
        assert payload is None
    
    @patch('jwt_utils.get_signing_key')
    @patch('jwt.decode')
    def test_verify_cognito_jwt_invalid_signature(self, mock_jwt_decode, mock_get_key):
        """無効な署名のトークンテスト"""
        import jwt_utils
        
        # 無効な署名例外をシミュレート
        mock_jwt_decode.side_effect = jwt.InvalidSignatureError("Invalid signature")
        mock_get_key.return_value = "mock-public-key"
        
        # 無効な署名のトークンはNoneが返されることを確認
        payload = jwt_utils.verify_cognito_jwt("invalid.signature.token")
        assert payload is None
    
    @patch('jwt_utils.get_signing_key')
    @patch('jwt.decode')
    def test_verify_cognito_jwt_invalid_token_use(self, mock_jwt_decode, mock_get_key):
        """無効なtoken_useクレームのテスト"""
        import jwt_utils
        
        # 無効なtoken_useを持つペイロード
        mock_jwt_decode.return_value = {
            "sub": "test-user-123",
            "token_use": "invalid",  # 無効な値
            "iss": "https://cognito-idp.ap-northeast-1.amazonaws.com/ap-northeast-1_testpool"
        }
        mock_get_key.return_value = "mock-public-key"
        
        # 無効なtoken_useの場合はNoneが返されることを確認
        payload = jwt_utils.verify_cognito_jwt("invalid.token.use")
        assert payload is None
    
    @patch('jwt_utils.get_signing_key')
    @patch('jwt.decode')
    def test_verify_cognito_jwt_invalid_issuer(self, mock_jwt_decode, mock_get_key):
        """無効なissuerのテスト"""
        import jwt_utils
        
        # 無効なissuerを持つペイロード
        mock_jwt_decode.return_value = {
            "sub": "test-user-123",
            "token_use": "access",
            "iss": "https://malicious-site.com/fake-issuer"  # 無効なissuer
        }
        mock_get_key.return_value = "mock-public-key"
        
        # 無効なissuerの場合はNoneが返されることを確認
        payload = jwt_utils.verify_cognito_jwt("invalid.issuer.token")
        assert payload is None
    
    def test_extract_user_id_from_api_gateway_authorizer(self):
        """API Gateway Authorizerからのuser_id抽出テスト"""
        import jwt_utils
        
        event = {
            'requestContext': {
                'authorizer': {
                    'claims': {
                        'sub': 'api-gateway-user-123'
                    }
                }
            },
            'headers': {}
        }
        
        user_id = jwt_utils.extract_user_id_from_token(event)
        assert user_id == 'api-gateway-user-123'
    
    @patch('jwt_utils.verify_cognito_jwt')
    def test_extract_user_id_from_jwt_token(self, mock_verify):
        """JWTトークンからのuser_id抽出テスト"""
        import jwt_utils
        
        # モックの設定
        mock_verify.return_value = {
            "sub": "jwt-user-456",
            "token_use": "access"
        }
        
        event = {
            'requestContext': {},
            'headers': {
                'Authorization': 'Bearer valid.jwt.token'
            }
        }
        
        user_id = jwt_utils.extract_user_id_from_token(event)
        assert user_id == 'jwt-user-456'
        
        # verify_cognito_jwtが正しく呼ばれることを確認
        mock_verify.assert_called_once_with('valid.jwt.token')
    
    def test_extract_user_id_no_auth_header(self):
        """認証ヘッダーがない場合のテスト"""
        import jwt_utils
        
        event = {
            'requestContext': {},
            'headers': {}
        }
        
        user_id = jwt_utils.extract_user_id_from_token(event)
        assert user_id is None
    
    def test_extract_user_id_invalid_auth_header(self):
        """無効な認証ヘッダーのテスト"""
        import jwt_utils
        
        event = {
            'requestContext': {},
            'headers': {
                'Authorization': 'Basic invalid-auth-type'
            }
        }
        
        user_id = jwt_utils.extract_user_id_from_token(event)
        assert user_id is None


if __name__ == "__main__":
    pytest.main([__file__])