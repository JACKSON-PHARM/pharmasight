"""Encryption helpers for sensitive KRA credentials at rest."""
from __future__ import annotations

import base64
import hashlib
import logging
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

logger = logging.getLogger(__name__)

ENC_PREFIX = "enc:v1:"


def _derive_fernet_key(raw: str) -> bytes:
    digest = hashlib.sha256((raw or "").encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    configured = (getattr(settings, "KRA_CREDENTIAL_ENCRYPTION_KEY", None) or "").strip()
    if configured:
        if len(configured) == 44 and configured.endswith("="):
            try:
                return Fernet(configured.encode("utf-8"))
            except Exception:
                pass
        key = _derive_fernet_key(configured)
        return Fernet(key)
    key = _derive_fernet_key((getattr(settings, "SECRET_KEY", None) or "").strip() or "change-me-in-production")
    return Fernet(key)


@lru_cache(maxsize=1)
def _legacy_fernets() -> list[Fernet]:
    raw = (getattr(settings, "KRA_CREDENTIAL_ENCRYPTION_OLD_KEYS", None) or "").strip()
    if not raw:
        return []
    out: list[Fernet] = []
    for part in raw.split(","):
        k = (part or "").strip()
        if not k:
            continue
        try:
            if len(k) == 44 and k.endswith("="):
                out.append(Fernet(k.encode("utf-8")))
            else:
                out.append(Fernet(_derive_fernet_key(k)))
        except Exception:
            logger.warning("Invalid legacy KRA encryption key format skipped")
    return out


def is_encrypted_value(value: str | None) -> bool:
    s = (value or "").strip()
    return s.startswith(ENC_PREFIX)


def encrypt_secret(plain: str | None) -> str | None:
    s = (plain or "").strip()
    if not s:
        return None
    if is_encrypted_value(s):
        return s
    token = _fernet().encrypt(s.encode("utf-8")).decode("utf-8")
    return f"{ENC_PREFIX}{token}"


def decrypt_secret(value: str | None) -> str:
    s = (value or "").strip()
    if not s:
        return ""
    if not is_encrypted_value(s):
        # Backward compatibility for existing plain rows.
        return s
    token = s[len(ENC_PREFIX) :].strip()
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        for legacy in _legacy_fernets():
            try:
                return legacy.decrypt(token.encode("utf-8")).decode("utf-8")
            except Exception:
                continue
        logger.warning("KRA credential decrypt failed (invalid token or key mismatch)")
        return ""
    except Exception as e:
        logger.warning("KRA credential decrypt error: %s", e)
        return ""


def ensure_encrypted_secret(value: str | None) -> str | None:
    s = (value or "").strip()
    if not s:
        return None
    if is_encrypted_value(s):
        return s
    return encrypt_secret(s)
