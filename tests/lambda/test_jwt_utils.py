from unittest.mock import Mock

import jwt
import pytest

from tests.lambda_module_loader import load_lambda_module


jwt_utils = load_lambda_module(
    "whiskey_common_jwt_utils_tests",
    "lambda/common/python/whiskey_common/jwt_utils.py",
)


@pytest.fixture(autouse=True)
def cognito_environment(monkeypatch):
    monkeypatch.setenv("COGNITO_USER_POOL_ID", "ap-northeast-1_pool")
    monkeypatch.setenv("COGNITO_CLIENT_ID", "client-123")
    monkeypatch.setenv("AWS_REGION", "ap-northeast-1")
    jwt_utils.get_cognito_jwks.cache_clear()
    yield
    jwt_utils.get_cognito_jwks.cache_clear()


def test_authorizer_claims_require_id_token_and_exact_audience(monkeypatch):
    valid = {
        "sub": "user-1",
        "aud": "client-123",
        "token_use": "id",
        "iss": "https://cognito-idp.ap-northeast-1.amazonaws.com/ap-northeast-1_pool",
    }
    assert jwt_utils.extract_user_id_from_event(
        {"requestContext": {"authorizer": {"claims": valid}}, "headers": {}}
    ) == "user-1"

    verify = Mock(return_value={"sub": "must-not-run"})
    monkeypatch.setattr(jwt_utils, "verify_cognito_jwt", verify)
    invalid = dict(valid, aud="another-client")
    event = {
        "requestContext": {"authorizer": {"claims": invalid}},
        "headers": {"Authorization": "Bearer otherwise.valid.token"},
    }
    assert jwt_utils.extract_user_id_from_event(event) is None
    verify.assert_not_called()

    assert jwt_utils.validate_authorizer_claims(dict(valid, token_use="access")) is None


def test_manual_bearer_path_uses_complete_verifier(monkeypatch):
    verify = Mock(return_value={"sub": "local-user"})
    monkeypatch.setattr(jwt_utils, "verify_cognito_jwt", verify)
    event = {"requestContext": {}, "headers": {"authorization": "Bearer signed.jwt.token"}}
    assert jwt_utils.extract_user_id_from_event(event) == "local-user"
    verify.assert_called_once_with("signed.jwt.token")


def test_verify_cognito_jwt_pins_algorithm_audience_issuer_and_required_claims(monkeypatch):
    monkeypatch.setattr(jwt_utils, "get_signing_key", lambda _token: "public-key")
    decode = Mock(return_value={"sub": "user-1", "token_use": "id"})
    monkeypatch.setattr(jwt_utils.jwt, "decode", decode)

    assert jwt_utils.verify_cognito_jwt("signed.jwt.token")["sub"] == "user-1"
    decode.assert_called_once_with(
        "signed.jwt.token",
        "public-key",
        algorithms=["RS256"],
        audience="client-123",
        issuer="https://cognito-idp.ap-northeast-1.amazonaws.com/ap-northeast-1_pool",
        options={"require": ["exp", "iat", "iss", "aud", "sub", "token_use"]},
    )


def test_verify_rejects_access_tokens_and_invalid_signatures(monkeypatch):
    monkeypatch.setattr(jwt_utils, "get_signing_key", lambda _token: "public-key")
    monkeypatch.setattr(jwt_utils.jwt, "decode", lambda *args, **kwargs: {"sub": "u", "token_use": "access"})
    assert jwt_utils.verify_cognito_jwt("access.jwt.token") is None

    def invalid(*_args, **_kwargs):
        raise jwt.InvalidSignatureError("invalid")

    monkeypatch.setattr(jwt_utils.jwt, "decode", invalid)
    assert jwt_utils.verify_cognito_jwt("forged.jwt.token") is None


def test_unknown_kid_refreshes_jwks_once(monkeypatch):
    first = Mock()
    first.raise_for_status.return_value = None
    first.json.return_value = {"keys": [{"kid": "old"}]}
    second = Mock()
    second.raise_for_status.return_value = None
    second.json.return_value = {"keys": [{"kid": "rotated"}]}
    get = Mock(side_effect=[first, second])
    monkeypatch.setattr(jwt_utils.requests, "get", get)
    monkeypatch.setattr(jwt_utils.jwt, "get_unverified_header", lambda _token: {"alg": "RS256", "kid": "rotated"})
    monkeypatch.setattr(jwt_utils.jwt.algorithms.RSAAlgorithm, "from_jwk", lambda _jwk: "rotated-key")

    assert jwt_utils.get_signing_key("token") == "rotated-key"
    assert get.call_count == 2


def test_unknown_kid_is_rejected_after_single_refresh(monkeypatch):
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"keys": [{"kid": "old"}]}
    get = Mock(return_value=response)
    monkeypatch.setattr(jwt_utils.requests, "get", get)
    monkeypatch.setattr(jwt_utils.jwt, "get_unverified_header", lambda _token: {"alg": "RS256", "kid": "missing"})

    with pytest.raises(ValueError, match="Unable to find signing key"):
        jwt_utils.get_signing_key("token")
    assert get.call_count == 2
