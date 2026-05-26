"""
Database-backed platform admin authentication.

Flow:
1. Password check against a bcrypt hash.
2. Email OTP challenge.
3. Short-lived bearer token stored server-side.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.services.email_service import EmailService
from app.utils.auth_internal import hash_password, validate_new_password, verify_password


LEGACY_DEFAULT_ADMIN_EMAIL = "jackmwas102@gmail.com"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_email(value: str) -> str:
    raw = (value or "").strip().lower()
    return raw


def _secret_hash(value: str) -> str:
    return hmac.new(
        (settings.SECRET_KEY or "").encode("utf-8"),
        (value or "").encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _mask_email(email: str) -> str:
    local, _, domain = (email or "").partition("@")
    if not domain:
        return "configured admin email"
    if len(local) <= 2:
        return f"{local[:1]}***@{domain}"
    return f"{local[:2]}***@{domain}"


class AdminAuthService:
    """Platform admin credential, OTP, and reset operations."""

    @staticmethod
    def ensure_seed_admin(db: Session) -> None:
        """Ensure the first platform admin row exists."""
        email = settings.PLATFORM_ADMIN_EMAIL
        if not email:
            return
        if email != LEGACY_DEFAULT_ADMIN_EMAIL:
            existing_new = db.execute(
                text("SELECT id FROM platform_admin_users WHERE lower(email) = :email"),
                {"email": email},
            ).mappings().first()
            if not existing_new:
                legacy = db.execute(
                    text("SELECT id FROM platform_admin_users WHERE lower(email) = :email"),
                    {"email": LEGACY_DEFAULT_ADMIN_EMAIL},
                ).mappings().first()
                if legacy:
                    db.execute(
                        text(
                            """
                            UPDATE platform_admin_users
                            SET email = :email, updated_at = NOW()
                            WHERE id = :id
                            """
                        ),
                        {"email": email, "id": legacy["id"]},
                    )
                    return
        row = db.execute(
            text("SELECT id, password_hash FROM platform_admin_users WHERE lower(email) = :email"),
            {"email": email},
        ).mappings().first()
        if row:
            if not row["password_hash"] and settings.PLATFORM_ADMIN_INITIAL_PASSWORD:
                db.execute(
                    text(
                        """
                        UPDATE platform_admin_users
                        SET password_hash = :password_hash, updated_at = NOW()
                        WHERE id = :id
                        """
                    ),
                    {"password_hash": hash_password(settings.PLATFORM_ADMIN_INITIAL_PASSWORD), "id": row["id"]},
                )
            return
        existing_active = db.execute(
            text("SELECT id FROM platform_admin_users WHERE is_active = TRUE ORDER BY created_at ASC LIMIT 1")
        ).mappings().first()
        if existing_active:
            return
        db.execute(
            text(
                """
                INSERT INTO platform_admin_users (email, password_hash, is_active)
                VALUES (:email, :password_hash, TRUE)
                """
            ),
            {
                "email": email,
                "password_hash": hash_password(settings.PLATFORM_ADMIN_INITIAL_PASSWORD)
                if settings.PLATFORM_ADMIN_INITIAL_PASSWORD
                else None,
            },
        )

    @staticmethod
    def _find_admin_by_identifier(db: Session, identifier: str):
        clean = _normalize_email(identifier)
        if clean == "admin":
            return db.execute(
                text(
                    """
                    SELECT id, email, password_hash, is_active
                    FROM platform_admin_users
                    WHERE is_active = TRUE
                    ORDER BY created_at ASC
                    LIMIT 1
                    """
                )
            ).mappings().first()
        return db.execute(
            text(
                """
                SELECT id, email, password_hash, is_active
                FROM platform_admin_users
                WHERE lower(email) = :email
                """
            ),
            {"email": clean},
        ).mappings().first()

    @staticmethod
    def start_login(username: str, password: str) -> dict:
        """Verify password and send OTP. Returns challenge details."""
        email = _normalize_email(username)
        db = SessionLocal()
        try:
            AdminAuthService.ensure_seed_admin(db)
            row = AdminAuthService._find_admin_by_identifier(db, email)
            if not row or not row["is_active"]:
                return {"ok": False, "reason": "invalid"}
            if not row["password_hash"]:
                return {"ok": False, "reason": "password_not_set", "email": row["email"]}
            if not verify_password(password or "", row["password_hash"]):
                return {"ok": False, "reason": "invalid"}

            otp = f"{secrets.randbelow(1000000):06d}"
            expires_at = _now() + timedelta(minutes=max(1, settings.ADMIN_OTP_EXPIRE_MINUTES))
            challenge_id = db.execute(
                text(
                    """
                    INSERT INTO platform_admin_otp_challenges
                        (admin_user_id, otp_hash, expires_at)
                    VALUES (:admin_user_id, :otp_hash, :expires_at)
                    RETURNING id
                    """
                ),
                {
                    "admin_user_id": row["id"],
                    "otp_hash": _secret_hash(otp),
                    "expires_at": expires_at,
                },
            ).scalar_one()
            sent = EmailService.send_admin_login_otp(
                row["email"],
                otp,
                expire_minutes=max(1, settings.ADMIN_OTP_EXPIRE_MINUTES),
            )
            db.commit()
            return {
                "ok": True,
                "challenge_id": str(challenge_id),
                "email": row["email"],
                "email_masked": _mask_email(row["email"]),
                "email_sent": bool(sent),
            }
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def verify_otp(challenge_id: str, otp: str) -> dict:
        """Consume an OTP challenge and return admin identity."""
        clean_otp = "".join(ch for ch in (otp or "") if ch.isdigit())
        db = SessionLocal()
        try:
            row = db.execute(
                text(
                    """
                    SELECT c.id, c.admin_user_id, c.otp_hash, c.expires_at, c.consumed_at,
                           c.attempt_count, u.email, u.is_active
                    FROM platform_admin_otp_challenges c
                    JOIN platform_admin_users u ON u.id = c.admin_user_id
                    WHERE c.id = CAST(:id AS UUID)
                    """
                ),
                {"id": challenge_id},
            ).mappings().first()
            if not row or not row["is_active"] or row["consumed_at"]:
                return {"ok": False, "reason": "invalid"}
            if row["expires_at"] <= _now():
                return {"ok": False, "reason": "expired"}
            if int(row["attempt_count"] or 0) >= 5:
                return {"ok": False, "reason": "locked"}

            db.execute(
                text("UPDATE platform_admin_otp_challenges SET attempt_count = attempt_count + 1 WHERE id = :id"),
                {"id": row["id"]},
            )
            if len(clean_otp) != 6 or not hmac.compare_digest(row["otp_hash"], _secret_hash(clean_otp)):
                db.commit()
                return {"ok": False, "reason": "invalid"}

            db.execute(
                text("UPDATE platform_admin_otp_challenges SET consumed_at = NOW() WHERE id = :id"),
                {"id": row["id"]},
            )
            db.execute(
                text("UPDATE platform_admin_users SET last_login_at = NOW(), updated_at = NOW() WHERE id = :id"),
                {"id": row["admin_user_id"]},
            )
            db.commit()
            return {"ok": True, "admin_user_id": str(row["admin_user_id"]), "email": row["email"]}
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def request_password_reset(email_or_username: str, base_url: str) -> dict:
        """Create and send a password reset link. Returns a non-enumerating result."""
        email = _normalize_email(email_or_username)
        db = SessionLocal()
        try:
            AdminAuthService.ensure_seed_admin(db)
            row = AdminAuthService._find_admin_by_identifier(db, email)
            if not row or not row["is_active"]:
                db.commit()
                return {"email_sent": False}

            token = secrets.token_urlsafe(40)
            expires_at = _now() + timedelta(minutes=max(5, settings.ADMIN_RESET_TOKEN_EXPIRE_MINUTES))
            db.execute(
                text(
                    """
                    INSERT INTO platform_admin_password_resets
                        (admin_user_id, token_hash, expires_at)
                    VALUES (:admin_user_id, :token_hash, :expires_at)
                    """
                ),
                {
                    "admin_user_id": row["id"],
                    "token_hash": _secret_hash(token),
                    "expires_at": expires_at,
                },
            )
            reset_url = f"{base_url.rstrip('/')}/app#login?admin_reset_token={token}"
            sent = EmailService.send_admin_password_reset(
                row["email"],
                reset_url,
                expire_minutes=max(5, settings.ADMIN_RESET_TOKEN_EXPIRE_MINUTES),
            )
            db.commit()
            return {"email_sent": bool(sent)}
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def get_admin_profile(admin_user_id: str) -> dict:
        """Return the current platform admin profile."""
        db = SessionLocal()
        try:
            row = db.execute(
                text(
                    """
                    SELECT id, email, is_active, last_login_at
                    FROM platform_admin_users
                    WHERE id = CAST(:id AS UUID)
                    """
                ),
                {"id": admin_user_id},
            ).mappings().first()
            if not row or not row["is_active"]:
                return {"ok": False, "reason": "Admin account not found."}
            return {
                "ok": True,
                "admin_user_id": str(row["id"]),
                "email": row["email"],
                "email_masked": _mask_email(row["email"]),
                "last_login_at": row["last_login_at"].isoformat() if row["last_login_at"] else None,
            }
        finally:
            db.close()

    @staticmethod
    def request_email_change(admin_user_id: str, new_email: str) -> dict:
        """Send an OTP to the requested new admin email address."""
        email = _normalize_email(new_email)
        if not email or "@" not in email:
            return {"ok": False, "reason": "Enter a valid email address."}
        if len(email) > 255:
            return {"ok": False, "reason": "Email address is too long."}
        db = SessionLocal()
        try:
            current = db.execute(
                text(
                    """
                    SELECT id, email, is_active
                    FROM platform_admin_users
                    WHERE id = CAST(:id AS UUID)
                    """
                ),
                {"id": admin_user_id},
            ).mappings().first()
            if not current or not current["is_active"]:
                return {"ok": False, "reason": "Admin account not found."}
            if current["email"].lower() == email:
                return {"ok": False, "reason": "This is already the admin email."}
            conflict = db.execute(
                text(
                    """
                    SELECT id
                    FROM platform_admin_users
                    WHERE lower(email) = :email AND id <> CAST(:id AS UUID)
                    """
                ),
                {"email": email, "id": admin_user_id},
            ).mappings().first()
            if conflict:
                return {"ok": False, "reason": "That email is already used by another platform admin."}

            otp = f"{secrets.randbelow(1000000):06d}"
            expires_at = _now() + timedelta(minutes=max(1, settings.ADMIN_OTP_EXPIRE_MINUTES))
            request_id = db.execute(
                text(
                    """
                    INSERT INTO platform_admin_email_change_requests
                        (admin_user_id, new_email, otp_hash, expires_at)
                    VALUES (:admin_user_id, :new_email, :otp_hash, :expires_at)
                    RETURNING id
                    """
                ),
                {
                    "admin_user_id": admin_user_id,
                    "new_email": email,
                    "otp_hash": _secret_hash(otp),
                    "expires_at": expires_at,
                },
            ).scalar_one()
            sent = EmailService.send_admin_email_change_otp(
                email,
                otp,
                expire_minutes=max(1, settings.ADMIN_OTP_EXPIRE_MINUTES),
            )
            db.commit()
            return {
                "ok": bool(sent),
                "request_id": str(request_id),
                "email_masked": _mask_email(email),
                "email_sent": bool(sent),
                "reason": None if sent else "Verification code could not be sent. Check SMTP settings.",
            }
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def verify_email_change(admin_user_id: str, request_id: str, otp: str) -> dict:
        """Consume an email-change OTP and update the admin email."""
        clean_otp = "".join(ch for ch in (otp or "") if ch.isdigit())
        db = SessionLocal()
        try:
            row = db.execute(
                text(
                    """
                    SELECT r.id, r.admin_user_id, r.new_email, r.otp_hash, r.expires_at,
                           r.consumed_at, r.attempt_count, u.is_active
                    FROM platform_admin_email_change_requests r
                    JOIN platform_admin_users u ON u.id = r.admin_user_id
                    WHERE r.id = CAST(:id AS UUID)
                      AND r.admin_user_id = CAST(:admin_user_id AS UUID)
                    """
                ),
                {"id": request_id, "admin_user_id": admin_user_id},
            ).mappings().first()
            if not row or not row["is_active"] or row["consumed_at"]:
                return {"ok": False, "reason": "Invalid verification request."}
            if row["expires_at"] <= _now():
                return {"ok": False, "reason": "Verification code expired."}
            if int(row["attempt_count"] or 0) >= 5:
                return {"ok": False, "reason": "Too many verification attempts. Request a new code."}
            db.execute(
                text("UPDATE platform_admin_email_change_requests SET attempt_count = attempt_count + 1 WHERE id = :id"),
                {"id": row["id"]},
            )
            if len(clean_otp) != 6 or not hmac.compare_digest(row["otp_hash"], _secret_hash(clean_otp)):
                db.commit()
                return {"ok": False, "reason": "Invalid verification code."}
            conflict = db.execute(
                text(
                    """
                    SELECT id
                    FROM platform_admin_users
                    WHERE lower(email) = :email AND id <> CAST(:id AS UUID)
                    """
                ),
                {"email": row["new_email"], "id": admin_user_id},
            ).mappings().first()
            if conflict:
                db.rollback()
                return {"ok": False, "reason": "That email is already used by another platform admin."}
            db.execute(
                text(
                    """
                    UPDATE platform_admin_users
                    SET email = :email, updated_at = NOW()
                    WHERE id = CAST(:id AS UUID)
                    """
                ),
                {"email": row["new_email"], "id": admin_user_id},
            )
            db.execute(
                text("UPDATE platform_admin_email_change_requests SET consumed_at = NOW() WHERE id = :id"),
                {"id": row["id"]},
            )
            db.commit()
            return {"ok": True, "email": row["new_email"], "email_masked": _mask_email(row["new_email"])}
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def reset_password(token: str, new_password: str) -> dict:
        """Consume a reset token and set a new admin password."""
        pw_error = validate_new_password(new_password or "")
        if pw_error:
            return {"ok": False, "reason": pw_error}
        db = SessionLocal()
        try:
            row = db.execute(
                text(
                    """
                    SELECT r.id, r.admin_user_id, r.expires_at, r.consumed_at, u.is_active
                    FROM platform_admin_password_resets r
                    JOIN platform_admin_users u ON u.id = r.admin_user_id
                    WHERE r.token_hash = :token_hash
                    """
                ),
                {"token_hash": _secret_hash(token or "")},
            ).mappings().first()
            if not row or not row["is_active"] or row["consumed_at"]:
                return {"ok": False, "reason": "Invalid or expired reset link."}
            if row["expires_at"] <= _now():
                return {"ok": False, "reason": "Invalid or expired reset link."}
            db.execute(
                text(
                    """
                    UPDATE platform_admin_users
                    SET password_hash = :password_hash, updated_at = NOW()
                    WHERE id = :id
                    """
                ),
                {"password_hash": hash_password(new_password), "id": row["admin_user_id"]},
            )
            db.execute(
                text("UPDATE platform_admin_password_resets SET consumed_at = NOW() WHERE id = :id"),
                {"id": row["id"]},
            )
            db.commit()
            return {"ok": True}
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()


DEFAULT_ADMIN_EMAIL = settings.PLATFORM_ADMIN_EMAIL
