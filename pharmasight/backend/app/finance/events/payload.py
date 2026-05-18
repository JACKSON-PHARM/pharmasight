"""
financial_events payload validation (E3 lineage context only).
"""
from __future__ import annotations

from typing import Any

# Forbidden top-level keys — operational snapshot clones
_FORBIDDEN_PAYLOAD_KEYS = frozenset(
    {
        "invoice",
        "invoices",
        "customer",
        "customers",
        "supplier",
        "suppliers",
        "lines",
        "line_items",
        "items",
        "products",
        "inventory_lines",
        "ledger_entries",
        "allocations",
        "payments",
        "full_document",
        "snapshot",
    }
)

_MAX_PAYLOAD_DEPTH = 4
_MAX_PAYLOAD_KEYS = 32
_MAX_STRING_LEN = 512


def validate_event_payload(payload: dict[str, Any]) -> None:
    """
    Enforce lineage-context-only payloads.

    Raises ValueError when payload violates philosophy (no shadow operational storage).
    """
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")
    _walk(payload, depth=0)


def _walk(obj: Any, *, depth: int) -> None:
    if depth > _MAX_PAYLOAD_DEPTH:
        raise ValueError("payload exceeds maximum nesting depth")
    if isinstance(obj, dict):
        if len(obj) > _MAX_PAYLOAD_KEYS:
            raise ValueError("payload has too many keys at one level")
        for key, value in obj.items():
            k = str(key).lower()
            if k in _FORBIDDEN_PAYLOAD_KEYS:
                raise ValueError(f"forbidden payload key: {key}")
            if k.endswith("_lines") or k.endswith("_items"):
                raise ValueError(f"forbidden aggregate payload key: {key}")
            _walk(value, depth=depth + 1)
    elif isinstance(obj, list):
        if len(obj) > _MAX_PAYLOAD_KEYS:
            raise ValueError("payload list too large")
        for item in obj:
            _walk(item, depth=depth + 1)
    elif isinstance(obj, str) and len(obj) > _MAX_STRING_LEN:
        raise ValueError("payload string value too long")
