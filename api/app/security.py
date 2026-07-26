import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

from app.config import settings

ACCESS = "access"
REFRESH = "refresh"

PASSWORD_MAX_BYTES = 72


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


def _create_token(user_id: int, token_type: str, ttl: int) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "type": token_type,
        "jti": uuid.uuid4().hex,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(user_id: int) -> str:
    return _create_token(user_id, ACCESS, settings.access_token_ttl)


def create_refresh_token(user_id: int) -> str:
    return _create_token(user_id, REFRESH, settings.refresh_token_ttl)


def decode_token(token: str, expected_type: str) -> dict[str, Any]:
    payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    if payload.get("type") != expected_type:
        raise jwt.InvalidTokenError("token type mismatch")
    if "sub" not in payload or "jti" not in payload:
        raise jwt.InvalidTokenError("missing claims")
    return payload


def token_expires_at(payload: dict[str, Any]) -> datetime:
    return datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
