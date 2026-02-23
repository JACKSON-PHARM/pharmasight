"""
Internal authentication: password hashing (bcrypt) and JWT (access, refresh, reset).
Dual-auth: internal JWT is primary; Supabase JWT can be accepted when configured.
Uses bcrypt directly to avoid passlib/bcrypt 4.x compatibility issues.
"""
from datetime import datetime, timezone, timedelta
from typing import Any, Optional
from uuid import uuid4

import bcrypt
from jose import JWTError, jwt
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.config import settings

# Bcrypt max password length (bytes)
BCRYPT_MAX_PASSWORD_BYTES = 72
DEFAULT_BCRYPT_ROUNDS = 12

# JWT claim names
CLAIM_SUB = "sub"
CLAIM_EMAIL = "email"
CLAIM_TENANT_SUBDOMAIN = "tenant_subdomain"
CLAIM_TYPE = "type"
CLAIM_EXP = "exp"
CLAIM_ISS = "iss"
CLAIM_JTI = "jti"

TYPE_ACCESS = "access"
TYPE_REFRESH = "refresh"
TYPE_RESET = "reset"
ISSUER_INTERNAL = "pharmasight-internal"


def _password_bytes(password: str, max_bytes: int = BCRYPT_MAX_PASSWORD_BYTES) -> bytes:
    """Encode password to bytes and truncate to bcrypt limit (72 bytes) to avoid ValueError."""
    raw = password.encode("utf-8")
    return raw[:max_bytes] if len(raw) > max_bytes else raw


def hash_password(password: str) -> str:
    """Return bcrypt hash of password. Passwords longer than 72 bytes are truncated (bcrypt limit)."""
    pw = _password_bytes(password)
    return bcrypt.hashpw(pw, bcrypt.gensalt(rounds=DEFAULT_BCRYPT_ROUNDS)).decode("ascii")


def verify_password(plain_password: str, password_hash: Optional[str]) -> bool:
    """Return True if plain_password matches password_hash. False if hash is None or invalid."""
    if not password_hash:
        return False
    try:
        pw = _password_bytes(plain_password)
        return bcrypt.checkpw(pw, password_hash.encode("ascii"))
    except Exception:
        return False


def _internal_encode(
    payload: dict,
    expires_delta: timedelta,
    token_type: str = TYPE_ACCESS,
) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        **payload,
        CLAIM_JTI: str(uuid4()),
        CLAIM_TYPE: token_type,
        CLAIM_ISS: ISSUER_INTERNAL,
        CLAIM_EXP: now + expires_delta,
    }
    return jwt.encode(
        payload,
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )


def create_access_token(
    user_id: str,
    email: str,
    tenant_subdomain: Optional[str] = None,
) -> str:
    """Create short-lived access token for API auth."""
    delta = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return _internal_encode(
        {
            CLAIM_SUB: str(user_id),
            CLAIM_EMAIL: email,
            CLAIM_TENANT_SUBDOMAIN: tenant_subdomain,
        },
        delta,
        token_type=TYPE_ACCESS,
    )


def create_refresh_token(user_id: str, email: str, tenant_subdomain: Optional[str] = None) -> str:
    """Create long-lived refresh token (used to obtain new access token)."""
    delta = timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    return _internal_encode(
        {
            CLAIM_SUB: str(user_id),
            CLAIM_EMAIL: email,
            CLAIM_TENANT_SUBDOMAIN: tenant_subdomain,
        },
        delta,
        token_type=TYPE_REFRESH,
    )


def create_reset_token(user_id: str, tenant_subdomain: str) -> str:
    """Create one-time reset token (link in email)."""
    delta = timedelta(minutes=settings.RESET_TOKEN_EXPIRE_MINUTES)
    return _internal_encode(
        {
            CLAIM_SUB: str(user_id),
            CLAIM_TENANT_SUBDOMAIN: tenant_subdomain,
        },
        delta,
        token_type=TYPE_RESET,
    )


def decode_internal_token(token: str, verify_exp: bool = True) -> Optional[dict]:
    """Decode and verify internal JWT. Returns payload dict or None. Does not check DB revocation (caller checks with is_token_revoked_in_db)."""
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            options={"verify_iss": True, "verify_exp": verify_exp},
            issuer=ISSUER_INTERNAL,
        )
        if not payload.get(CLAIM_SUB):
            return None
        return payload
    except (JWTError, Exception):
        return None


def is_token_revoked_in_db(session: Session, jti: Optional[str]) -> bool:
    """
    True if jti is in this DB's revoked_tokens table (tenant or legacy).
    The tenant/legacy DB is the source of truth for its users' sessions.
    """
    if not jti:
        return False
    try:
        row = session.execute(text("SELECT 1 FROM revoked_tokens WHERE jti = :jti"), {"jti": jti}).fetchone()
        return row is not None
    except Exception:
        return False


def revoke_token_in_db(session: Session, jti: str, expires_at: Optional[datetime] = None) -> None:
    """
    Insert jti into this DB's revoked_tokens table (tenant or legacy).
    Call from logout after resolving the user's tenant/legacy DB.
    """
    try:
        session.execute(
            text(
                "INSERT INTO revoked_tokens (jti, revoked_at, expires_at) VALUES (:jti, NOW(), :expires_at) ON CONFLICT (jti) DO NOTHING"
            ),
            {"jti": jti, "expires_at": expires_at},
        )
        session.commit()
    except Exception:
        session.rollback()
        raise


def decode_supabase_token(token: str) -> Optional[dict]:
    """Decode and verify Supabase JWT if SUPABASE_JWT_SECRET is set. Returns payload or None."""
    secret = getattr(settings, "SUPABASE_JWT_SECRET", None) or ""
    if not secret:
        return None
    try:
        # Supabase uses same HS256; issuer is typically "supabase" or project ref
        payload = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            options={"verify_iss": False, "verify_aud": False},
        )
        return payload
    except (JWTError, Exception):
        return None


def decode_token_dual(token: str) -> Optional[dict]:
    """
    Try internal JWT first, then Supabase JWT.
    Returns payload with at least sub; internal adds tenant_subdomain, email, type.
    """
    payload = decode_internal_token(token)
    if payload:
        return payload
    payload = decode_supabase_token(token)
    if payload:
        # Normalize: Supabase uses 'sub' for user id; no tenant in token
        return {
            CLAIM_SUB: payload.get("sub"),
            CLAIM_EMAIL: payload.get("email"),
            CLAIM_TENANT_SUBDOMAIN: None,  # Must come from header
            CLAIM_TYPE: TYPE_ACCESS,
        }
    return None
