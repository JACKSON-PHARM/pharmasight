"""Helpers for reversal document audit metadata (Phase 1: hashing, request context)."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel
from starlette.requests import Request


def client_ip_from_request(request: Request | None) -> str | None:
    if request is None:
        return None
    xff = request.headers.get("x-forwarded-for")
    if xff:
        first = xff.split(",")[0].strip()
        return (first or None)[:64] if first else None
    if request.client and request.client.host:
        return str(request.client.host)[:64]
    return None


def user_agent_from_request(request: Request | None) -> str | None:
    if request is None:
        return None
    ua = request.headers.get("user-agent")
    return (ua.strip()[:2000] if ua and ua.strip() else None)


def canonical_json_sha256(payload: Any) -> str:
    """Deterministic SHA-256 hex of JSON (sorted keys, compact separators)."""
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def pydantic_payload_hash(model: BaseModel) -> str:
    """Hash a Pydantic model's JSON-safe dump with stable list ordering where applicable."""
    data = model.model_dump(mode="json")
    items = data.get("items")
    lines = data.get("lines")
    if isinstance(items, list):
        data = {**data, "items": sorted(items, key=_reversal_line_sort_key)}
    elif isinstance(lines, list):
        data = {**data, "lines": sorted(lines, key=_reversal_line_sort_key)}
    return canonical_json_sha256(data)


def _reversal_line_sort_key(row: dict) -> tuple:
    return (
        str(row.get("original_sale_item_id") or ""),
        str(row.get("item_id") or ""),
        str(row.get("batch_number") or ""),
        str(row.get("quantity_returned") or row.get("quantity") or ""),
    )
