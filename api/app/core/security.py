import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import base58
import bcrypt
import jwt
from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey

from app.core.config import settings

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


def create_api_key() -> str:
    return secrets.token_urlsafe(32)


def hash_api_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()


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


def is_valid_wallet(wallet_address: str) -> bool:
    try:
        return len(base58.b58decode(wallet_address)) == 32
    except ValueError:
        return False


def create_wallet_nonce() -> str:
    return f"chongdae-auth:{secrets.token_hex(16)}"


def verify_wallet_signature(wallet_address: str, message: str, signature: str) -> bool:
    try:
        pubkey = base58.b58decode(wallet_address)
        raw_signature = base58.b58decode(signature)
    except ValueError:
        return False

    if len(pubkey) != 32 or len(raw_signature) != 64:
        return False

    try:
        VerifyKey(pubkey).verify(message.encode(), raw_signature)
    except BadSignatureError:
        return False
    return True
