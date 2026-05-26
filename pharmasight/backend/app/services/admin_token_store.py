"""
In-memory store for issued admin session tokens.
Used to verify Bearer token on /api/admin/* routes (except login).
"""
import threading
import time

# token -> (expiry timestamp, admin_user_id)
_admin_tokens: dict[str, tuple[float, str | None]] = {}
_lock = threading.Lock()


def _ttl_seconds() -> int:
    try:
        from app.config import settings

        return max(300, int(getattr(settings, "ADMIN_SESSION_TTL_SECONDS", 7200) or 7200))
    except Exception:
        return 7200


def add_admin_token(token: str, admin_user_id: str | None = None) -> None:
    if not token:
        return
    with _lock:
        _admin_tokens[token] = (time.time() + _ttl_seconds(), admin_user_id)


def is_valid_admin_token(token: str) -> bool:
    if not token or not token.strip():
        return False
    now = time.time()
    with _lock:
        entry = _admin_tokens.get(token)
        if entry is None:
            return False
        expiry, _admin_user_id = entry
        if now >= expiry:
            del _admin_tokens[token]
            return False
        return True


def get_admin_user_id(token: str) -> str | None:
    if not token or not token.strip():
        return None
    now = time.time()
    with _lock:
        entry = _admin_tokens.get(token)
        if entry is None:
            return None
        expiry, admin_user_id = entry
        if now >= expiry:
            del _admin_tokens[token]
            return None
        return admin_user_id


def revoke_admin_token(token: str) -> None:
    if not token:
        return
    with _lock:
        _admin_tokens.pop(token, None)
