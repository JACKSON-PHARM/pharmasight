"""
Shared logic for building public-facing URLs used in emails (password reset, invites, etc.).
Set APP_PUBLIC_URL to your public frontend URL so invite and reset links work for recipients;
otherwise links fall back to request origin (or localhost) and will not work for external users.
"""
import logging
from urllib.parse import urlparse

from fastapi import Request

from app.config import settings

logger = logging.getLogger(__name__)


def get_public_base_url(request: Request) -> str:
    """
    Base URL for email links (password reset, invite/setup, etc.).
    - When APP_PUBLIC_URL is set and not localhost → use it (required for links sent to external users).
    - Otherwise use the request's Origin (or Referer) so the link points to the frontend the user is on.
    - Fallback: x-forwarded-host/host, then localhost (links will not work for recipients).
    """
    base = (settings.APP_PUBLIC_URL or "").strip().rstrip("/")
    if base and "localhost" not in base.lower() and "127.0.0.1" not in base:
        return base
    # Infer from request (e.g. when frontend and backend are on same host on Render)
    origin = request.headers.get("origin") or request.headers.get("referer")
    if origin:
        try:
            parsed = urlparse(origin)
            if parsed.scheme and parsed.netloc and "localhost" not in (parsed.netloc or "").lower() and "127.0.0.1" not in (parsed.netloc or ""):
                return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
        except Exception:
            pass
    # Fallback: request host or localhost
    scheme = request.headers.get("x-forwarded-proto") or request.url.scheme or "https"
    host = (request.headers.get("x-forwarded-host") or request.headers.get("host") or "").split(",")[0].strip()
    if host and "localhost" not in host.lower() and "127.0.0.1" not in host:
        return f"{scheme}://{host}".rstrip("/")
    result = base or "http://localhost:3000"
    logger.warning(
        "Invite/reset links use localhost and will not work for external users. "
        "Set APP_PUBLIC_URL to your public frontend URL (e.g. https://app.pharmasight.com) in .env or environment."
    )
    return result
