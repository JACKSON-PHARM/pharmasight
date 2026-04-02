"""
OSCU incremental sync cursor helpers (lastReqDt).

OSCU spec v2.0 requires the TIS to persist the last successful retrieval date-time (CHAR(14))
for each kind of "Get" data and send it as lastReqDt on subsequent requests.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.etims_sync_cursor import EtimsSyncCursor


DEFAULT_LAST_REQ_DT = "20100101000000"  # safe floor (YYYYMMDDHHMMSS)


def _now_yyyymmddhhmmss() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


def normalize_last_req_dt(value: Optional[str]) -> str:
    """
    Return a valid lastReqDt string (CHAR(14)). If invalid/missing, return DEFAULT_LAST_REQ_DT.
    """
    if not value:
        return DEFAULT_LAST_REQ_DT
    s = str(value).strip()
    if len(s) != 14 or not s.isdigit():
        return DEFAULT_LAST_REQ_DT
    return s


def extract_result_dt(response_json: Any) -> Optional[str]:
    """
    Extract resultDt from a typical OSCU response.
    Returns None if absent/unparseable.
    """
    if not isinstance(response_json, dict):
        return None
    v = response_json.get("resultDt") or response_json.get("resultDate")
    if v is None:
        return None
    s = str(v).strip()
    if len(s) == 14 and s.isdigit():
        return s
    return None


@dataclass(frozen=True)
class EtimsCursorKey:
    company_id: UUID
    branch_id: UUID
    category: str


class EtimsSyncCursorService:
    """
    Small service for retrieving and advancing lastReqDt.

    Categories should be stable strings (recommended: OSCU endpoint name like "selectCodeList",
    "itemInfo", "getPurchaseTransactionInfo", etc.).
    """

    @staticmethod
    def get_last_req_dt(db: Session, *, company_id: UUID, branch_id: UUID, category: str) -> str:
        cat = (category or "").strip()
        if not cat:
            raise ValueError("category is required")
        row = (
            db.query(EtimsSyncCursor)
            .filter(
                EtimsSyncCursor.company_id == company_id,
                EtimsSyncCursor.branch_id == branch_id,
                EtimsSyncCursor.category == cat,
            )
            .first()
        )
        return normalize_last_req_dt(row.last_req_dt if row else None)

    @staticmethod
    def advance_on_success(
        db: Session,
        *,
        company_id: UUID,
        branch_id: UUID,
        category: str,
        response_json: Any,
        fallback_to_now: bool = True,
    ) -> str:
        """
        Update cursor after a successful retrieval.
        Uses response.resultDt when present; otherwise uses now() if fallback_to_now.
        Returns the stored last_req_dt.
        """
        cat = (category or "").strip()
        if not cat:
            raise ValueError("category is required")
        next_dt = extract_result_dt(response_json)
        if next_dt is None and fallback_to_now:
            next_dt = _now_yyyymmddhhmmss()
        next_dt = normalize_last_req_dt(next_dt)

        row = (
            db.query(EtimsSyncCursor)
            .filter(EtimsSyncCursor.branch_id == branch_id, EtimsSyncCursor.category == cat)
            .first()
        )
        if not row:
            row = EtimsSyncCursor(
                company_id=company_id,
                branch_id=branch_id,
                category=cat,
                last_req_dt=next_dt,
            )
            db.add(row)
        else:
            # Enforce tenant scope (single DB, multi-company)
            row.company_id = company_id
            row.last_req_dt = next_dt
        return next_dt

