"""Password hashing, JWT, Fernet token encryption, ingest-token handling.

IMPLEMENTATION DECISION: `bcrypt` is used directly instead of passlib[bcrypt]
(passlib is unmaintained and breaks with bcrypt>=4.1). Same algorithm.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings

JWT_ALG = "HS256"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("ascii"))
    except ValueError:
        return False


def create_jwt(user_id: str) -> str:
    s = get_settings()
    now = datetime.now(timezone.utc)
    payload = {"sub": user_id, "iat": now, "exp": now + timedelta(hours=s.jwt_expiry_hours)}
    return jwt.encode(payload, s.jwt_secret, algorithm=JWT_ALG)


def decode_jwt(token: str) -> str | None:
    try:
        payload = jwt.decode(token, get_settings().jwt_secret, algorithms=[JWT_ALG])
    except jwt.PyJWTError:
        return None
    return payload.get("sub")


# --- refresh-token encryption --------------------------------------------------
def _fernet() -> Fernet:
    key = get_settings().token_encryption_key
    if not key:
        raise RuntimeError("TOKEN_ENCRYPTION_KEY is not set")
    return Fernet(key.encode())


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt_secret(value: str) -> str | None:
    try:
        return _fernet().decrypt(value.encode()).decode()
    except (InvalidToken, RuntimeError):
        return None


# --- SMS ingest tokens ------------------------------------------------------------
# Token format: "<8-char prefix>.<secret>". The prefix is stored in clear to find
# the owning user; only the SHA-256 of the full token is stored.
def generate_ingest_token() -> tuple[str, str, str]:
    prefix = secrets.token_hex(4)
    token = f"{prefix}.{secrets.token_urlsafe(24)}"
    return token, prefix, sha256_hex(token)


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def token_matches(token: str, stored_hash: str | None) -> bool:
    if not stored_hash:
        return False
    return hmac.compare_digest(sha256_hex(token), stored_hash)
