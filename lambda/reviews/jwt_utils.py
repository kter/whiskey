"""
JWT Validation Utilities for AWS Cognito
AWS Cognito JWT検証ユーティリティ
"""
import json
import jwt
import requests
from functools import lru_cache
from typing import Optional, Dict, Any
import os


@lru_cache(maxsize=1)
def get_cognito_jwks() -> Dict[str, Any]:
    """
    AWS Cognito JWKSを取得（キャッシュ付き）
    """
    user_pool_id = os.environ.get('COGNITO_USER_POOL_ID')
    region = os.environ.get('AWS_REGION', 'ap-northeast-1')
    
    if not user_pool_id:
        raise ValueError("COGNITO_USER_POOL_ID environment variable is required")
    
    jwks_url = f"https://cognito-idp.{region}.amazonaws.com/{user_pool_id}/.well-known/jwks.json"
    
    try:
        response = requests.get(jwks_url, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"Failed to fetch JWKS: {e}")
        raise


def get_signing_key(token: str) -> str:
    """
    JWTトークンのヘッダーからkidを取得し、対応する公開鍵を返す
    """
    try:
        # JWTヘッダーをデコード（検証なし）
        header = jwt.get_unverified_header(token)
        kid = header.get('kid')
        
        if not kid:
            raise ValueError("Token header missing 'kid'")
        
        # JWKSから対応するキーを検索
        jwks = get_cognito_jwks()
        for key in jwks.get('keys', []):
            if key.get('kid') == kid:
                # JWKをPEMフォーマットに変換
                return jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(key))
        
        raise ValueError(f"Unable to find signing key with kid: {kid}")
        
    except Exception as e:
        print(f"Error getting signing key: {e}")
        raise


def verify_cognito_jwt(token: str) -> Optional[Dict[str, Any]]:
    """
    AWS Cognito JWTトークンを安全に検証
    
    Args:
        token: JWT token string
        
    Returns:
        Decoded payload if valid, None if invalid
    """
    try:
        # 署名検証用の公開鍵を取得
        signing_key = get_signing_key(token)
        
        # JWTを検証してデコード
        payload = jwt.decode(
            token,
            signing_key,
            algorithms=['RS256'],
            options={
                'verify_signature': True,
                'verify_exp': True,
                'verify_iat': True,
                'verify_aud': False,  # Cognito access tokensはaudクレームがない場合がある
            }
        )
        
        # Cognito特有の検証
        if payload.get('token_use') not in ['access', 'id']:
            raise ValueError("Invalid token_use claim")
        
        # issuer検証
        user_pool_id = os.environ.get('COGNITO_USER_POOL_ID')
        region = os.environ.get('AWS_REGION', 'ap-northeast-1')
        expected_iss = f"https://cognito-idp.{region}.amazonaws.com/{user_pool_id}"
        
        if payload.get('iss') != expected_iss:
            raise ValueError("Invalid issuer")
        
        return payload
        
    except jwt.ExpiredSignatureError:
        print("Token has expired")
        return None
    except jwt.InvalidSignatureError:
        print("Invalid token signature")
        return None
    except jwt.InvalidTokenError as e:
        print(f"Invalid token: {e}")
        return None
    except Exception as e:
        print(f"JWT verification error: {e}")
        return None


def extract_user_id_from_token(event: Dict[str, Any]) -> Optional[str]:
    """
    Lambdaイベントから安全にuser_idを抽出
    
    Args:
        event: Lambda event object
        
    Returns:
        User ID if authentication is valid, None otherwise
    """
    # まずAPI Gateway Cognito Authorizerからの情報を確認
    claims = event.get('requestContext', {}).get('authorizer', {}).get('claims', {})
    user_id = claims.get('sub')
    
    if user_id:
        return user_id
    
    # 手動でJWTトークンを検証
    auth_header = event.get('headers', {}).get('Authorization') or event.get('headers', {}).get('authorization')
    
    if not auth_header or not auth_header.startswith('Bearer '):
        return None
    
    token = auth_header.replace('Bearer ', '')
    
    # 安全なJWT検証を実行
    payload = verify_cognito_jwt(token)
    
    if payload:
        return payload.get('sub')
    
    return None