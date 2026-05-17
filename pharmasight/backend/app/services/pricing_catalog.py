"""Load SightOps commercial pricing catalog (Kenya-facing) for admin API and provisioning hints."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

_CATALOG_PATH = (
    Path(__file__).resolve().parents[3] / "frontend" / "js" / "pricing" / "sightops_pricing_catalog.json"
)


@lru_cache(maxsize=1)
def load_pricing_catalog() -> Dict[str, Any]:
    if not _CATALOG_PATH.is_file():
        return {"version": "missing", "tiers": [], "seat_credits": {}}
    with _CATALOG_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def tier_by_slug(slug: Optional[str]) -> Optional[Dict[str, Any]]:
    catalog = load_pricing_catalog()
    s = (slug or "").strip().lower()
    if not s:
        return None
    for t in catalog.get("tiers") or []:
        if (t.get("slug") or "").lower() == s:
            return t
    aliases = catalog.get("legacy_tier_aliases") or {}
    mapped = aliases.get(s)
    if mapped:
        for t in catalog.get("tiers") or []:
            if (t.get("slug") or "").lower() == mapped:
                return t
    return None


def default_caps_for_plan(slug: Optional[str]) -> Dict[str, Optional[int]]:
    """Suggested company caps when assigning subscription_plan."""
    t = tier_by_slug(slug)
    if not t:
        return {}
    return {
        "user_limit": t.get("users"),
        "branch_limit": t.get("branches"),
        "product_limit": t.get("products"),
    }
