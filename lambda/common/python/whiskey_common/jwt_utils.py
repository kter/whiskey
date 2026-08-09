"""Strict Cognito ID-token validation."""

import json
import os
from functools import lru_cache
from typing import Any, Mapping

import jwt
import requests


def _required_environment() -> tuple[str, str, str]:
    user_pool_id = os.environ.get("COGNITO_USER_POOL_ID")
    client_id = os.environ.get("COGNITO_CLIENT_ID")
    region = os.environ.get("AWS_REGION", "ap-northeast-1")
    if not user_pool_id:
        raise ValueError("COGNITO_USER_POOL_ID environment variable is required")
    if not client_id:
        raise ValueError("COGNITO_CLIENT_ID environment variable is required")
    return user_pool_id, client_id, region


@lru_cache(maxsize=1)
def get_cognito_jwks() -> dict[str, Any]:
    user_pool_id, _client_id, region = _required_environment()
    url = f"https://cognito-idp.{region}.amazonaws.com/{user_pool_id}/.well-known/jwks.json"
    response = requests.get(url, timeout=(3.05, 5))
    response.raise_for_status()
    jwks = response.json()
    if not isinstance(jwks, dict) or not isinstance(jwks.get("keys"), list):
        raise ValueError("Invalid Cognito JWKS response")
    return jwks


def _find_signing_key(jwks: Mapping[str, Any], kid: str):
    for key in jwks.get("keys", []):
        if key.get("kid") == kid:
            return jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(key))
    return None


def get_signing_key(token: str):
    header = jwt.get_unverified_header(token)
    if header.get("alg") != "RS256":
        raise ValueError("Token must use RS256")
    kid = header.get("kid")
    if not kid:
        raise ValueError("Token header missing kid")

    signing_key = _find_signing_key(get_cognito_jwks(), kid)
    if signing_key is not None:
        return signing_key

    get_cognito_jwks.cache_clear()
    signing_key = _find_signing_key(get_cognito_jwks(), kid)
    if signing_key is None:
        raise ValueError("Unable to find signing key")
    return signing_key


def verify_cognito_jwt(token: str) -> dict[str, Any] | None:
    try:
        user_pool_id, client_id, region = _required_environment()
        issuer = f"https://cognito-idp.{region}.amazonaws.com/{user_pool_id}"
        payload = jwt.decode(
            token,
            get_signing_key(token),
            algorithms=["RS256"],
            audience=client_id,
            issuer=issuer,
            options={"require": ["exp", "iat", "iss", "aud", "sub", "token_use"]},
        )
        if payload.get("token_use") != "id":
            raise jwt.InvalidTokenError("token_use must be id")
        return payload
    except (jwt.PyJWTError, requests.RequestException, ValueError, TypeError):
        return None


def validate_authorizer_claims(claims: Mapping[str, Any]) -> str | None:
    """Validate defense-in-depth claims supplied by API Gateway."""
    try:
        user_pool_id, client_id, region = _required_environment()
    except ValueError:
        return None
    expected_issuer = f"https://cognito-idp.{region}.amazonaws.com/{user_pool_id}"
    if claims.get("aud") != client_id or claims.get("token_use") != "id":
        return None
    if claims.get("iss") and claims.get("iss") != expected_issuer:
        return None
    subject = claims.get("sub")
    return subject if isinstance(subject, str) and subject else None


def extract_user_id_from_event(event: Mapping[str, Any]) -> str | None:
    authorizer = ((event.get("requestContext") or {}).get("authorizer") or {})
    claims = authorizer.get("claims")
    if isinstance(claims, Mapping) and claims:
        return validate_authorizer_claims(claims)

    headers = event.get("headers") or {}
    authorization = headers.get("Authorization") or headers.get("authorization")
    if not isinstance(authorization, str) or not authorization.startswith("Bearer "):
        return None
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        return None
    payload = verify_cognito_jwt(token)
    return payload.get("sub") if payload else None
