"""Schemas for finance shadow reconciliation (Stage 2A)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class TreasuryMovementReconciliationResponse(BaseModel):
    phase: str
    branch_id: str
    since: str
    until: str
    legacy_cashbook: Dict[str, Any]
    lineage_projection: Dict[str, Any]
    comparison: Dict[str, Any]
    drift_items: List[Dict[str, Any]] = Field(default_factory=list)
    policy: Dict[str, Any] = Field(default_factory=dict)
