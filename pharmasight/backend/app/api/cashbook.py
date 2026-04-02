"""
Cashbook API (money movement tracking).

Cashbook is a tracking layer sourced from existing flows (expenses + supplier payments).
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import List, Optional, Tuple
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_tenant_db, get_effective_company_id_for_user, _user_has_permission
from app.models import CashbookEntry, Branch, UserBranchRole, User
from app.schemas.cashbook import CashbookEntryResponse, CashbookSummaryResponse, CashbookDailyRow
from app.services.cashbook_service import backfill_cashbook_entries

# TODO(company_modules): Same as expenses — require_module("finance") needs company_modules defaults
# aligned before router-level gating to avoid breaking existing cashbook users.
router = APIRouter()


def _effective_company_id(request: Request, db: Session, user) -> UUID:
    cid = getattr(request.state, "effective_company_id", None)
    if cid is not None:
        return cid
    cid = get_effective_company_id_for_user(db, user)
    if cid is None:
        raise HTTPException(status_code=400, detail="Company context not available")
    return cid


def _parse_uuid(x: Optional[str]) -> Optional[UUID]:
    if not x:
        return None
    try:
        return UUID(str(x).strip())
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid UUID value")


def _require_reports_view_and_branch_access(
    request: Request,
    branch_id_query: Optional[UUID],
    x_branch_id: Optional[str],
    user_db: Tuple[User, Session],
) -> Tuple[object, Session, UUID]:
    user, db = user_db
    if not _user_has_permission(db, user.id, "reports.view"):
        raise HTTPException(status_code=403, detail="Permission reports.view required")

    company_id = _effective_company_id(request, db, user)

    branch_id_final = branch_id_query or _parse_uuid(x_branch_id)
    if not branch_id_final:
        raise HTTPException(status_code=400, detail="branch_id (or X-Branch-ID header) is required")

    # Branch access guard
    has_branch_access = (
        db.query(UserBranchRole)
        .filter(UserBranchRole.user_id == user.id, UserBranchRole.branch_id == branch_id_final)
        .first()
        is not None
    )
    if not has_branch_access:
        raise HTTPException(status_code=403, detail="You do not have access to this branch")

    # Branch existence guard (optional but clearer errors)
    branch = db.query(Branch).filter(Branch.id == branch_id_final).first()
    if not branch or str(branch.company_id) != str(company_id):
        raise HTTPException(status_code=404, detail="Branch not found")

    return user, db, branch_id_final


def _normalize_payment_mode(v: Optional[str]) -> Optional[str]:
    if v is None:
        return None
    m = (v or "").strip().lower()
    if not m:
        return None
    if m not in ("cash", "mpesa", "bank"):
        raise HTTPException(status_code=400, detail="payment_mode must be one of: cash, mpesa, bank")
    return m


def _normalize_source_type(v: Optional[str]) -> Optional[str]:
    if v is None:
        return None
    s = (v or "").strip().lower()
    if not s:
        return None
    if s not in ("expense", "supplier_payment", "sale"):
        raise HTTPException(status_code=400, detail="source_type must be one of: expense, supplier_payment, sale")
    return s


@router.get("/cashbook", response_model=List[CashbookEntryResponse])
def list_cashbook_entries(
    request: Request,
    branch_id: Optional[UUID] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    payment_mode: Optional[str] = Query(None),
    source_type: Optional[str] = Query(None),
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    x_branch_id: Optional[str] = Header(None, alias="X-Branch-ID"),
    user_db: Tuple[User, Session] = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user, db, branch_id_final = _require_reports_view_and_branch_access(
        request=request,
        branch_id_query=branch_id,
        x_branch_id=x_branch_id,
        user_db=(user_db[0], db),
    )
    company_id = _effective_company_id(request, db, user)

    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=400, detail="date_from must be <= date_to")

    payment_mode = _normalize_payment_mode(payment_mode)
    source_type = _normalize_source_type(source_type)

    # IMPORTANT: apply filters BEFORE calling limit()/offset().
    q = db.query(CashbookEntry).filter(
        CashbookEntry.company_id == company_id,
        CashbookEntry.branch_id == branch_id_final,
    )
    if date_from:
        q = q.filter(CashbookEntry.date >= date_from)
    if date_to:
        q = q.filter(CashbookEntry.date <= date_to)
    if payment_mode:
        q = q.filter(CashbookEntry.payment_mode == payment_mode)
    if source_type:
        q = q.filter(CashbookEntry.source_type == source_type)

    q = q.order_by(CashbookEntry.date.desc(), CashbookEntry.created_at.desc()).offset(offset).limit(limit)
    return q.all()


@router.get("/cashbook/summary", response_model=CashbookSummaryResponse)
def cashbook_summary(
    request: Request,
    branch_id: Optional[UUID] = Query(None),
    start_date: date = Query(..., description="Start date (YYYY-MM-DD)"),
    end_date: date = Query(..., description="End date (YYYY-MM-DD)"),
    payment_mode: Optional[str] = Query(None),
    source_type: Optional[str] = Query(None),
    include_daily: bool = Query(True),
    x_branch_id: Optional[str] = Header(None, alias="X-Branch-ID"),
    user_db: Tuple[User, Session] = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user, db, branch_id_final = _require_reports_view_and_branch_access(
        request=request,
        branch_id_query=branch_id,
        x_branch_id=x_branch_id,
        user_db=(user_db[0], db),
    )
    company_id = _effective_company_id(request, db, user)

    if start_date > end_date:
        raise HTTPException(status_code=400, detail="date_from must be <= date_to")

    payment_mode = _normalize_payment_mode(payment_mode)
    source_type = _normalize_source_type(source_type)

    base_filters = [
        CashbookEntry.company_id == company_id,
        CashbookEntry.branch_id == branch_id_final,
        CashbookEntry.date >= start_date,
        CashbookEntry.date <= end_date,
    ]
    if payment_mode:
        base_filters.append(CashbookEntry.payment_mode == payment_mode)
    if source_type:
        base_filters.append(CashbookEntry.source_type == source_type)

    total_inflow_q = db.query(
        func.coalesce(
            func.sum(
                case((CashbookEntry.type == "inflow", CashbookEntry.amount), else_=Decimal("0"))
            ),
            Decimal("0"),
        )
    ).filter(*base_filters)

    total_outflow_q = db.query(
        func.coalesce(
            func.sum(
                case((CashbookEntry.type == "outflow", CashbookEntry.amount), else_=Decimal("0"))
            ),
            Decimal("0"),
        )
    ).filter(*base_filters)

    total_inflow = total_inflow_q.scalar() or Decimal("0")
    total_outflow = total_outflow_q.scalar() or Decimal("0")
    net_cashflow = total_inflow - total_outflow

    breakdown: List[CashbookDailyRow] = []
    if include_daily:
        daily_rows = (
            db.query(
                CashbookEntry.date.label("d"),
                func.coalesce(func.sum(case((CashbookEntry.type == "inflow", CashbookEntry.amount), else_=Decimal("0"))), Decimal("0")).label(
                    "inflow"
                ),
                func.coalesce(func.sum(case((CashbookEntry.type == "outflow", CashbookEntry.amount), else_=Decimal("0"))), Decimal("0")).label(
                    "outflow"
                ),
            )
            .filter(*base_filters)
            .group_by(CashbookEntry.date)
            .order_by(CashbookEntry.date.asc())
            .all()
        )
        by_day = {r.d: r for r in daily_rows}
        breakdown = []
        cur = start_date
        while cur <= end_date:
            r = by_day.get(cur)
            inf = (r.inflow or Decimal("0")) if r else Decimal("0")
            ouf = (r.outflow or Decimal("0")) if r else Decimal("0")
            breakdown.append(
                CashbookDailyRow(
                    date=cur,
                    total_inflow=inf,
                    total_outflow=ouf,
                    net_cashflow=inf - ouf,
                )
            )
            cur += timedelta(days=1)

    return CashbookSummaryResponse(
        branch_id=branch_id_final,
        start_date=start_date,
        end_date=end_date,
        total_inflow=total_inflow,
        total_outflow=total_outflow,
        net_cashflow=net_cashflow,
        breakdown=breakdown,
    )


@router.post("/cashbook/backfill")
def cashbook_backfill(
    request: Request,
    start_date: date = Query(..., description="Start date (YYYY-MM-DD)"),
    end_date: date = Query(..., description="End date (YYYY-MM-DD)"),
    branch_id: Optional[UUID] = Query(None),
    x_branch_id: Optional[str] = Header(None, alias="X-Branch-ID"),
    user_db: Tuple[User, Session] = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Backfill cashbook entries from existing records for the given branch/date range.
    Idempotent: skips sources that already exist in cashbook_entries.
    """
    user, db, branch_id_final = _require_reports_view_and_branch_access(
        request=request,
        branch_id_query=branch_id,
        x_branch_id=x_branch_id,
        user_db=(user_db[0], db),
    )
    company_id = _effective_company_id(request, db, user)

    result = backfill_cashbook_entries(
        db,
        company_id=company_id,
        branch_id=branch_id_final,
        start_date=start_date,
        end_date=end_date,
        created_by=user.id,
    )
    db.commit()
    return result

