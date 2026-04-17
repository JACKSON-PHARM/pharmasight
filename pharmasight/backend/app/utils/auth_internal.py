"""
Internal authentication: password hashing (bcrypt) and JWT (access, refresh, reset).
Uses bcrypt directly to avoid passlib/bcrypt 4.x compatibility issues.
"""
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional, Tuple
from uuid import uuid4

import bcrypt
from jose import JWTError, jwt
from jose.exceptions import ExpiredSignatureError
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
CLAIM_COMPANY_ID = "company_id"
CLAIM_TYPE = "type"
CLAIM_EXP = "exp"
CLAIM_ISS = "iss"
CLAIM_JTI = "jti"

# Impersonation (PLATFORM_ADMIN only): frontend can show banner; no privilege escalation
CLAIM_IMPERSONATION = "impersonation"
CLAIM_IMPERSONATED_BY = "impersonated_by"

TYPE_ACCESS = "access"
TYPE_REFRESH = "refresh"
TYPE_RESET = "reset"
TYPE_SIGNUP_HANDOFF = "signup_handoff"
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


def validate_new_password(password: str) -> Optional[str]:
    """
    Validate new password for submission. Applies only to new password input; does not touch stored hashes.
    Returns None if valid, or an error message string if invalid.
    Policy: minimum 8 characters; at least 1 letter and 1 digit. No special character requirement.
    """
    if not password or len(password) < 8:
        return "Password must be at least 8 characters."
    has_letter = any(c.isalpha() for c in password)
    has_digit = any(c.isdigit() for c in password)
    if not has_letter or not has_digit:
        return "Password must contain at least one letter and one digit."
    return None


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
    company_id: Optional[str] = None,
) -> str:
    """Create short-lived access token for API auth. company_id used for RLS and multi-company scoping."""
    payload = {
        CLAIM_SUB: str(user_id),
        CLAIM_EMAIL: email,
        CLAIM_TENANT_SUBDOMAIN: tenant_subdomain,
    }
    if company_id is not None:
        payload[CLAIM_COMPANY_ID] = str(company_id)
    delta = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return _internal_encode(payload, delta, token_type=TYPE_ACCESS)


def create_refresh_token(
    user_id: str,
    email: str,
    tenant_subdomain: Optional[str] = None,
    company_id: Optional[str] = None,
) -> str:
    """Create long-lived refresh token (used to obtain new access token). company_id for consistency with access token."""
    payload = {
        CLAIM_SUB: str(user_id),
        CLAIM_EMAIL: email,
        CLAIM_TENANT_SUBDOMAIN: tenant_subdomain,
    }
    if company_id is not None:
        payload[CLAIM_COMPANY_ID] = str(company_id)
    delta = timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    return _internal_encode(payload, delta, token_type=TYPE_REFRESH)


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


def create_signup_handoff_token(
    *,
    access_token: str,
    refresh_token: str,
    user_id: str,
    email: str,
    username: Optional[str],
    tenant_subdomain: Optional[str],
    expires_minutes: int = 15,
) -> str:
    """
    Short-lived JWT carrying access + refresh tokens for cross-origin marketing → ERP handoff.
    Client sends this once to POST /api/auth/exchange-signup-handoff; prefer URL hash (not sent to server).
    """
    payload: Dict[str, Any] = {
        CLAIM_SUB: str(user_id),
        CLAIM_EMAIL: (email or "").strip(),
        "h_at": access_token,
        "h_rt": refresh_token,
        "uname": (username or "") or "",
    }
    if tenant_subdomain is not None:
        payload[CLAIM_TENANT_SUBDOMAIN] = tenant_subdomain
    return _internal_encode(
        payload,
        timedelta(minutes=expires_minutes),
        token_type=TYPE_SIGNUP_HANDOFF,
    )


def decode_signup_handoff_token(token: str) -> Optional[dict]:
    """Decode a signup handoff JWT. Returns dict with access_token, refresh_token, user_id, email, username, tenant_subdomain or None."""
    pl = decode_internal_token(token, verify_exp=True)
    if not pl:
        return None
    if (pl.get(CLAIM_TYPE) or "").strip() != TYPE_SIGNUP_HANDOFF:
        return None
    at = pl.get("h_at")
    rt = pl.get("h_rt")
    uid = pl.get(CLAIM_SUB)
    if not at or not rt or not uid:
        return None
    return {
        "access_token": at,
        "refresh_token": rt,
        "user_id": str(uid),
        "email": (pl.get(CLAIM_EMAIL) or "").strip(),
        "username": ((pl.get("uname") or "") or "").strip() or None,
        "tenant_subdomain": ((pl.get(CLAIM_TENANT_SUBDOMAIN) or "") or "").strip() or None,
    }


# Short expiry for impersonation (no refresh; admin must re-impersonate to extend)
IMPERSONATION_TOKEN_EXPIRE_MINUTES = 15


def create_impersonation_access_token(
    user_id: str,
    email: str,
    tenant_subdomain: Optional[str],
    company_id: Optional[str],
    impersonated_by: str,
    expires_minutes: int = IMPERSONATION_TOKEN_EXPIRE_MINUTES,
) -> str:
    """
    Create a short-lived access token for PLATFORM_ADMIN impersonation.
    Token has same shape as normal access token (sub, email, company_id, etc.) so get_current_user
    treats the request as the impersonated user. No privilege escalation: permissions are those of
    the impersonated user only. Frontend can show admin banner by checking claim "impersonation": true.
    """
    payload = {
        CLAIM_SUB: str(user_id),
        CLAIM_EMAIL: email,
        CLAIM_TENANT_SUBDOMAIN: tenant_subdomain,
        CLAIM_IMPERSONATION: True,
        CLAIM_IMPERSONATED_BY: str(impersonated_by),
    }
    if company_id is not None:
        payload[CLAIM_COMPANY_ID] = str(company_id)
    delta = timedelta(minutes=expires_minutes)
    return _internal_encode(payload, delta, token_type=TYPE_ACCESS)


def decode_internal_token_or_reason(token: str, verify_exp: bool = True) -> Tuple[Optional[dict], Optional[str]]:
    """
    Decode and verify internal JWT. Returns (payload, None) on success, (None, reason) on failure.
    Does not check DB revocation (caller uses _lookup_user_if_not_revoked / is_token_revoked_in_db).
    """
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            options={"verify_iss": True, "verify_exp": verify_exp},
            issuer=ISSUER_INTERNAL,
        )
        if not payload.get(CLAIM_SUB):
            return None, "missing_sub_claim"
        return payload, None
    except ExpiredSignatureError:
        return None, "expired"
    except JWTError as e:
        return None, f"jwt_error:{type(e).__name__}"
    except Exception as e:
        return None, f"decode_error:{type(e).__name__}"


def decode_internal_token(token: str, verify_exp: bool = True) -> Optional[dict]:
    """Decode and verify internal JWT. Returns payload dict or None."""
    payload, _ = decode_internal_token_or_reason(token, verify_exp=verify_exp)
    return payload


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


# -----------------------------------------------------------------------------
# Refresh token storage (per-device, rotation, revoke on logout)
# Table: refresh_tokens (migration 039). All queries are tenant-scoped (session is tenant/legacy DB).
# -----------------------------------------------------------------------------

def insert_refresh_token(
    session: Session,
    user_id: str,
    jti: str,
    expires_at: datetime,
    tenant_id: Optional[str] = None,
    device_info: Optional[str] = None,
    issued_at: Optional[datetime] = None,
) -> None:
    """Insert a new refresh token row. Caller must commit if needed."""
    from uuid import uuid4
    now = issued_at or datetime.now(timezone.utc)
    session.execute(
        text(
            """
            INSERT INTO refresh_tokens (id, user_id, jti, issued_at, expires_at, device_info, tenant_id, is_active)
            VALUES (:id, CAST(:user_id AS UUID), :jti, :issued_at, :expires_at, :device_info, CAST(:tenant_id AS UUID), TRUE)
            """
        ),
        {
            "id": str(uuid4()),
            "user_id": user_id,
            "jti": jti,
            "issued_at": now,
            "expires_at": expires_at,
            "device_info": device_info,
            "tenant_id": tenant_id,
        },
    )


def get_active_refresh_token_by_jti(session: Session, jti: str):
    """Return the refresh_tokens row if active and not expired, else None. Caller uses same DB session."""
    if not jti:
        return None
    try:
        row = session.execute(
            text(
                """
                SELECT id, user_id, jti, issued_at, expires_at, device_info, tenant_id, is_active
                FROM refresh_tokens
                WHERE jti = :jti AND is_active = TRUE AND expires_at > NOW()
                """
            ),
            {"jti": jti},
        ).fetchone()
        return row
    except Exception:
        return None


def deactivate_refresh_token_by_jti(session: Session, jti: str) -> None:
    """Set is_active = FALSE for the given jti."""
    try:
        session.execute(
            text("UPDATE refresh_tokens SET is_active = FALSE WHERE jti = :jti"),
            {"jti": jti},
        )
    except Exception:
        session.rollback()
        raise


def deactivate_all_refresh_tokens_for_user(session: Session, user_id: str) -> None:
    """Invalidate all active refresh tokens for this user (in this tenant/legacy DB)."""
    try:
        session.execute(
            text("UPDATE refresh_tokens SET is_active = FALSE WHERE user_id = CAST(:user_id AS UUID) AND is_active = TRUE"),
            {"user_id": user_id},
        )
    except Exception:
        session.rollback()
        raise


def count_active_refresh_tokens(session: Session, user_id: str) -> int:
    """Number of active (is_active=TRUE, not expired) refresh tokens for this user."""
    try:
        row = session.execute(
            text(
                """
                SELECT COUNT(*) FROM refresh_tokens
                WHERE user_id = CAST(:user_id AS UUID) AND is_active = TRUE AND expires_at > NOW()
                """
            ),
            {"user_id": user_id},
        ).fetchone()
        return row[0] if row else 0
    except Exception:
        return 0


# Max concurrent active refresh tokens (sessions) per user per tenant. Oldest revoked when exceeded.
MAX_ACTIVE_REFRESH_TOKENS_PER_USER = 3


def revoke_oldest_refresh_tokens_over_limit(session: Session, user_id: str, max_active: int = MAX_ACTIVE_REFRESH_TOKENS_PER_USER) -> None:
    """If user has more than max_active active tokens, deactivate oldest by issued_at until at most max_active remain."""
    try:
        session.execute(
            text(
                """
                WITH ranked AS (
                    SELECT id, ROW_NUMBER() OVER (ORDER BY issued_at DESC) AS rn
                    FROM refresh_tokens
                    WHERE user_id = CAST(:user_id AS UUID) AND is_active = TRUE AND expires_at > NOW()
                )
                UPDATE refresh_tokens rt SET is_active = FALSE
                FROM ranked r WHERE rt.id = r.id AND r.rn > :max_active
                """
            ),
            {"user_id": user_id, "max_active": max_active},
        )
    except Exception:
        session.rollback()
        raise


def decode_token_dual(token: str) -> Optional[dict]:
    """
    Decode and verify PharmaSight internal JWT only.

    NOTE: Supabase JWT verification has been removed. Supabase must not participate in authentication.
    """
    return decode_internal_token(token)
