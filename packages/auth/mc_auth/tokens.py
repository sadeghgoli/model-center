import uuid
from datetime import UTC, datetime, timedelta

import jwt

from mc_shared.errors import PlatformError
from mc_shared.settings import get_settings


def issue_token(user_id: str, role: str, token_type: str) -> tuple[str, str, int]:
    settings = get_settings()
    if not settings.jwt_secret:
        raise PlatformError("internal_error", "JWT secret is not configured.", 500)
    if token_type == "access":
        ttl = settings.jwt_access_token_expire_minutes * 60
    else:
        ttl = settings.jwt_refresh_token_expire_days * 86400
    jti = str(uuid.uuid4())
    now = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "role": role,
        "type": token_type,
        "jti": jti,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl)).timestamp()),
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, jti, ttl


def decode_token(token: str, expected_type: str) -> dict:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError as exc:
        raise PlatformError("invalid_request", "Token has expired.", 401) from exc
    except jwt.PyJWTError as exc:
        raise PlatformError("invalid_request", "Token is invalid.", 401) from exc
    if payload.get("type") != expected_type:
        raise PlatformError("invalid_request", "Token type is invalid.", 401)
    return payload
