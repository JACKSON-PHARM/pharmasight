"""Normalize phone-like strings to digits-only international format for wa.me links."""

from __future__ import annotations


def digits_only(value: str | None) -> str:
    return "".join(c for c in (value or "") if c.isdigit())


def normalize_whatsapp_e164(raw: str | None, *, default_e164: str) -> str:
    """
    Best-effort E.164 digits for WhatsApp click-to-chat.
    Supports Kenya-style local numbers starting with 0 (07…) when no country code present.
    """
    d = digits_only(raw)
    fallback = digits_only(default_e164) or "254708476318"
    if not d:
        return fallback
    # Kenya: 07xxxxxxxx (10 digits) -> 2547xxxxxxxx
    if d.startswith("0") and len(d) >= 10:
        d = "254" + d[1:]
    elif len(d) == 9 and d.startswith("7"):
        d = "254" + d
    return d
