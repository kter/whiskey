"""Compatibility imports for the JWT helpers now owned by the shared layer."""

import sys
from pathlib import Path

try:
    from whiskey_common.jwt_utils import (  # noqa: F401
        extract_user_id_from_event,
        extract_user_id_from_token,
        get_cognito_jwks,
        get_signing_key,
        validate_authorizer_claims,
        verify_cognito_jwt,
    )
except ModuleNotFoundError as exc:
    if exc.name != "whiskey_common":
        raise
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common" / "python"))
    from whiskey_common.jwt_utils import (  # noqa: F401
        extract_user_id_from_event,
        extract_user_id_from_token,
        get_cognito_jwks,
        get_signing_key,
        validate_authorizer_claims,
        verify_cognito_jwt,
    )
