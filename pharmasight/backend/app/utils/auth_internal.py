"""
Internal authentication: password hashing (bcrypt) and JWT (access, refresh, reset).
Dual-auth: internal JWT is primary; Supabase JWT can be accepted when configured.
"""
from datetime import datetime, timezone, timedelta
from typing import Any, Optional
from uuid import UUID

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import settings

# Bcrypt for password hashing (same as passlib[bcrypt] in requirements)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)

# JWT claim names
CLAIM_SUB = "sub"
CLAIM_EMAIL = "email"
CLAIM_TENANT_SUBDOMAIN = "tenant_subdomain"
CLAIM_TYPE = "type"
CLAIM_EXP = "exp"
CLAIM_ISS = "iss"

TYPE_ACCESS = "access"
TYPE_REFRESH = "refresh"
TYPE_RESET = "reset"
ISSUER_INTERNAL = "pharmasight-internal"


def hash_password(password: str) -> str:
    """Return bcrypt hash of password."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, password_hash: Optional[str]) -> bool:
    """Return True if plain_password matches password_hash. False if hash is None or invalid."""
    if not password_hash:
        return False
    try:
        return pwd_context.verify(plain_password, password_hash)
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


def decode_internal_token(token: str) -> Optional[dict]:
    """Decode and verify internal JWT. Returns payload dict or None."""
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            options={"verify_iss": True},
            issuer=ISSUER_INTERNAL,
        )
        if not payload.get(CLAIM_SUB):
            return None
        return payload
    except (JWTError, Exception):
        return None


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
