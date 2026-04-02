"""
OAuth2 client credentials for KRA eTIMS OSCU API.

Sandbox: token is requested via GET ``{ETIMS_SANDBOX_OAUTH_BASE}/v1/token/generate?grant_type=client_credentials``.
Production: typically ``{api_base}/oauth2/v1/generate`` (legacy gateway path).
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Dict, Tuple

import requests

from app.config import settings
from app.services.etims.constants import OAUTH_TOKEN_PATH_APIGEE, OAUTH_TOKEN_PATH_LEGACY

logger = logging.getLogger(__name__)

_lock = threading.Lock()
# key -> (access_token, expires_at_epoch)
_token_cache: Dict[Tuple[str, str, str, str], Tuple[str, float]] = {}


def get_access_token(
    *,
    api_base: str,
    username: str,
    password: str,
    timeout: int = 45,
    environment: str | None = None,
) -> str:
    """
    Return a valid Bearer token, refreshing when expired (60s skew).

    ``api_base`` is the OSCU API root (e.g. .../etims-oscu/api/v1 for sandbox).
    For sandbox, OAuth is usually on ``ETIMS_SANDBOX_OAUTH_BASE`` with
    ``OAUTH_TOKEN_PATH_APIGEE``; production uses ``api_base`` + legacy path.
    """
    if not (username or "").strip() or not (password or "").strip():
        logger.warning(
            "eTIMS OAuth: refusing token request — missing client id or secret. "
            "Configure ETIMS_APP_CONSUMER_KEY and ETIMS_APP_CONSUMER_SECRET (or branch OAuth fields)."
        )
        raise RuntimeError(
            "eTIMS OAuth: missing client id/secret. Set ETIMS_APP_CONSUMER_KEY and ETIMS_APP_CONSUMER_SECRET."
        )

    env = (environment or "sandbox").strip().lower()
    if env == "production":
        token_base = api_base.rstrip("/")
        token_path = OAUTH_TOKEN_PATH_LEGACY
    else:
        oauth_host = (getattr(settings, "ETIMS_SANDBOX_OAUTH_BASE", None) or "").strip().rstrip("/")
        token_base = oauth_host or api_base.rstrip("/")
        token_path = OAUTH_TOKEN_PATH_APIGEE

    key = (token_base, token_path, username, password)
    now = time.time()
    with _lock:
        hit = _token_cache.get(key)
        if hit and hit[1] > now + 60:
            return hit[0]

    url = f"{token_base}{token_path}"
    params = {"grant_type": "client_credentials"}
    try:
        # Align with Postman sandbox collection: use GET for token generation.
        if env == "production":
            r = requests.post(
                url,
                auth=(username, password),
                params=params,
                timeout=timeout,
            )
        else:
            r = requests.get(
                url,
                auth=(username, password),
                params=params,
                timeout=timeout,
            )
    except requests.RequestException as e:
        logger.warning("eTIMS OAuth request failed: %s", e)
        raise RuntimeError(f"eTIMS OAuth network error: {e}") from e

    if r.status_code >= 400:
        logger.warning("eTIMS OAuth HTTP %s: %s", r.status_code, r.text[:500])
        raise RuntimeError(f"eTIMS OAuth failed: HTTP {r.status_code}")

    data = r.json() if r.text else {}
    token = data.get("access_token")
    if not token:
        raise RuntimeError("eTIMS OAuth response missing access_token")

    expires_in = float(data.get("expires_in") or 3600)
    with _lock:
        _token_cache[key] = (token, now + expires_in)
    return token


def clear_token_cache() -> None:
    """Test / admin use only."""
    with _lock:
        _token_cache.clear()
