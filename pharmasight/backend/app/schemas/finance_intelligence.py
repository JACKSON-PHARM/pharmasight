"""
Operational financial intelligence API schemas.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ConfidenceSignalResponse(BaseModel):
    signal_id: str
    label: str
    score: float
    max_score: float
    value: Any = None
    explanation: str


class BranchConfidenceResponse(BaseModel):
    phase: str
    branch_id: str
    since: str
    until: str
    confidence_score: float
    authority_level: str
    authority_level_label: str
    authority_capabilities: Dict[str, bool]
    doctrine: Dict[str, Any]
    signals: List[ConfidenceSignalResponse]
    governance_snapshot: Dict[str, Any]
    traceability: Dict[str, str]


class RecoveryExposureResponse(BaseModel):
    phase: str
    branch_id: str
    since: str
    until: str
    as_of: str
    headline: Dict[str, Any]
    questions: Dict[str, Any]
    lineage_period_summary: Dict[str, Any]
    doctrine: Dict[str, Any]
    traceability: Dict[str, Any]
