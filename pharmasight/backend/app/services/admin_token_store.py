"""
In-memory store for issued admin session tokens.
Used to verify Bearer token on /api/admin/* routes (except login).
"""
import threading
import time

# token -> expiry timestamp (time.time() + TTL)
_admin_tokens: dict[str, float] = {}
_lock = threading.Lock()
TTL_SECONDS = 24 * 3600  # 24 hours


def add_admin_token(token: str) -> None:
    if not token:
        return
    with _lock:
        _admin_tokens[token] = time.time() + TTL_SECONDS


def is_valid_admin_token(token: str) -> bool:
    if not token or not token.strip():
        return False
    now = time.time()
    with _lock:
        expiry = _admin_tokens.get(token)
        if expiry is None:
            return False
        if now >= expiry:
            del _admin_tokens[token]
            return False
        return True
