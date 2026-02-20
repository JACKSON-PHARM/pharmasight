"""
Shared logic for building public-facing URLs used in emails (password reset, invites, etc.).
Uses APP_PUBLIC_URL when set to a non-localhost URL; otherwise infers from the request
so links work on Render (or any host) when the user is on the frontend.
"""
from urllib.parse import urlparse

from fastapi import Request

from app.config import settings


def get_public_base_url(request: Request) -> str:
    """
    Base URL for email links (password reset, invite/setup, etc.).
    - When APP_PUBLIC_URL is set and not localhost → use it.
    - Otherwise use the request's Origin (or Referer) so the link points to the
      frontend the user is on (e.g. on Render, frontend and backend can be different).
    - Fallback: x-forwarded-host/host for same-service deploys, then localhost.
    """
    base = (settings.APP_PUBLIC_URL or "").strip().rstrip("/")
    if base and "localhost" not in base and "127.0.0.1" not in base:
        return base
    # Infer from request so links work on Render without setting APP_PUBLIC_URL
    origin = request.headers.get("origin") or request.headers.get("referer")
    if origin:
        try:
            parsed = urlparse(origin)
            if parsed.scheme and parsed.netloc:
                return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
        except Exception:
            pass
    # Fallback: request host (e.g. when frontend and backend are same service)
    scheme = request.headers.get("x-forwarded-proto") or request.url.scheme or "https"
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
    if host:
        return f"{scheme}://{host.split(',')[0].strip()}".rstrip("/")
    return base or "http://localhost:3000"
