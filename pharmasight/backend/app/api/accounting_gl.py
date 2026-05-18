"""
M1 authoritative GL API — trial balance and chart of accounts.

Reports read GL only (not projections or financial_events).
"""
from __future__ import annotations

from datetime import date
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.accounting.coa_service import company_has_coa, provision_default_chart_of_accounts
from app.accounting.fiscal_period_service import close_fiscal_period, provision_current_open_period
from app.accounting.posting_failures_service import list_gl_posting_failures, resolve_gl_posting_failure
from app.accounting.reconciliation.control_accounts import build_control_reconciliation
from app.accounting.reconciliation.vat import build_vat_reconciliation
from app.accounting.reports.balance_sheet import build_balance_sheet
from app.accounting.reports.profit_and_loss import build_profit_and_loss
from app.accounting.reports.trial_balance import build_trial_balance
from app.dependencies import get_current_user, get_tenant_db
from app.finance.governance.access import guard_finance_report_access
from app.finance.governance.classification import MANAGEMENT
from app.finance.governance.request_context import bind_fastapi_request
from app.models import User
from app.models.accounting import ChartOfAccount
from app.schemas.accounting import (
    BalanceSheetResponse,
    ChartOfAccountResponse,
    ControlReconciliationResponse,
    GlPostingFailureListResponse,
    GlPostingFailureResolveResponse,
    ProfitAndLossResponse,
    TrialBalanceResponse,
    VatReconciliationResponse,
)

router = APIRouter(prefix="/accounting", tags=["Accounting GL"])


def _company_id(request: Request, db: Session, user: User) -> UUID:
    cid = getattr(request.state, "effective_company_id", None)
    if cid is not None:
        return cid
    from app.dependencies import get_effective_company_id_for_user

    cid = get_effective_company_id_for_user(db, user)
    if cid is None:
        raise HTTPException(status_code=400, detail="Company context not available")
    return cid


@router.get("/trial-balance", response_model=TrialBalanceResponse)
def get_trial_balance(
    request: Request,
    as_of_date: Optional[date] = Query(None, description="As-of date (inclusive)"),
    branch_id: Optional[UUID] = Query(None),
    user_db=Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    bind_fastapi_request(request)
    user, _ = user_db
    company_id = _company_id(request, db, user)
    as_of = as_of_date or date.today()

    guard_finance_report_access(
        db,
        user,
        company_id,
        "accounting.reports",
        MANAGEMENT,
        branch_id=branch_id,
    )

    if not company_has_coa(db, company_id):
        provision_default_chart_of_accounts(db, company_id)
        provision_current_open_period(db, company_id, as_of=as_of)
        db.commit()

    data = build_trial_balance(db, company_id=company_id, as_of_date=as_of, branch_id=branch_id)
    return TrialBalanceResponse(
        company_id=data["company_id"],
        branch_id=data["branch_id"],
        as_of_date=data["as_of_date"],
        doctrine=data["doctrine"],
        lines=data["lines"],
        totals=data["totals"],
        balanced=data["balanced"],
    )


@router.get("/chart-of-accounts", response_model=List[ChartOfAccountResponse])
def list_chart_of_accounts(
    request: Request,
    active_only: bool = Query(True),
    user_db=Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    bind_fastapi_request(request)
    user, _ = user_db
    company_id = _company_id(request, db, user)

    from app.dependencies import _user_has_permission

    if not _user_has_permission(db, user.id, "accounting.view"):
        raise HTTPException(status_code=403, detail="Permission denied: accounting.view")

    q = db.query(ChartOfAccount).filter(ChartOfAccount.company_id == company_id)
    if active_only:
        q = q.filter(ChartOfAccount.is_active.is_(True))
    return q.order_by(ChartOfAccount.code.asc()).all()


@router.post("/provision", status_code=204)
def provision_accounting_baseline(
    request: Request,
    user_db=Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """Seed CoA and current fiscal period for the company (idempotent)."""
    bind_fastapi_request(request)
    user, _ = user_db
    company_id = _company_id(request, db, user)

    from app.dependencies import _user_has_permission

    if not _user_has_permission(db, user.id, "accounting.post"):
        raise HTTPException(status_code=403, detail="Permission denied: accounting.post")

    provision_default_chart_of_accounts(db, company_id)
    provision_current_open_period(db, company_id)
    db.commit()
    return None


@router.get("/posting-failures", response_model=GlPostingFailureListResponse)
def get_posting_failures(
    request: Request,
    unresolved_only: bool = Query(True, description="When true, only open failures"),
    branch_id: Optional[UUID] = Query(None),
    source_type: Optional[str] = Query(None, description="Filter by source_type e.g. sales_invoice"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user_db=Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """Surface GL soft-fail records so finance can remediate before period close."""
    bind_fastapi_request(request)
    user, _ = user_db
    company_id = _company_id(request, db, user)

    from app.dependencies import _user_has_permission

    if not _user_has_permission(db, user.id, "accounting.view"):
        raise HTTPException(status_code=403, detail="Permission denied: accounting.view")

    data = list_gl_posting_failures(
        db,
        company_id=company_id,
        branch_id=branch_id,
        unresolved_only=unresolved_only,
        source_type=source_type,
        limit=limit,
        offset=offset,
    )
    return GlPostingFailureListResponse(**data)


@router.post("/posting-failures/{failure_id}/resolve", response_model=GlPostingFailureResolveResponse)
def resolve_posting_failure(
    request: Request,
    failure_id: UUID,
    user_db=Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """Mark a posting failure resolved after manual GL fix or replay."""
    bind_fastapi_request(request)
    user, _ = user_db
    company_id = _company_id(request, db, user)

    from app.dependencies import _user_has_permission

    if not _user_has_permission(db, user.id, "accounting.post"):
        raise HTTPException(status_code=403, detail="Permission denied: accounting.post")

    try:
        row = resolve_gl_posting_failure(db, company_id=company_id, failure_id=failure_id)
        db.commit()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    resolved_at = row.resolved_at.isoformat() if row.resolved_at else ""
    return GlPostingFailureResolveResponse(id=str(row.id), resolved_at=resolved_at)


@router.get("/reconciliation/vat", response_model=VatReconciliationResponse)
def get_vat_reconciliation(
    request: Request,
    from_date: date = Query(...),
    to_date: date = Query(...),
    branch_id: Optional[UUID] = Query(None),
    user_db=Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    bind_fastapi_request(request)
    user, _ = user_db
    company_id = _company_id(request, db, user)
    if from_date > to_date:
        raise HTTPException(status_code=400, detail="from_date must be <= to_date")

    guard_finance_report_access(
        db, user, company_id, "accounting.reports", MANAGEMENT, branch_id=branch_id
    )

    data = build_vat_reconciliation(
        db,
        company_id=company_id,
        from_date=from_date,
        to_date=to_date,
        branch_id=branch_id,
    )
    return VatReconciliationResponse(**data)


@router.get("/reconciliation/control", response_model=ControlReconciliationResponse)
def get_control_reconciliation(
    request: Request,
    as_of_date: Optional[date] = Query(None),
    branch_id: Optional[UUID] = Query(None, description="Required for inventory and cash controls"),
    user_db=Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    bind_fastapi_request(request)
    user, _ = user_db
    company_id = _company_id(request, db, user)
    as_of = as_of_date or date.today()

    guard_finance_report_access(
        db, user, company_id, "accounting.reports", MANAGEMENT, branch_id=branch_id
    )

    if not company_has_coa(db, company_id):
        provision_default_chart_of_accounts(db, company_id)
        db.commit()

    data = build_control_reconciliation(
        db, company_id=company_id, branch_id=branch_id, as_of_date=as_of
    )
    return ControlReconciliationResponse(**data)


@router.get("/reconciliation", response_class=HTMLResponse)
def control_reconciliation_dashboard(
    request: Request,
    as_of_date: Optional[date] = Query(None),
    branch_id: Optional[UUID] = Query(None),
    user_db=Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """Simple HTML dashboard for control reconciliation."""
    bind_fastapi_request(request)
    user, _ = user_db
    company_id = _company_id(request, db, user)
    as_of = as_of_date or date.today()
    guard_finance_report_access(
        db, user, company_id, "accounting.reports", MANAGEMENT, branch_id=branch_id
    )
    data = build_control_reconciliation(
        db, company_id=company_id, branch_id=branch_id, as_of_date=as_of
    )
    rows = ""
    for c in data["controls"]:
        cls = "fail" if c["status"] == "FAIL" else "pass"
        rows += (
            f"<tr class='{cls}'><td>{c['label']}</td>"
            f"<td>{c['subledger_balance']}</td><td>{c['gl_balance']}</td>"
            f"<td>{c['delta']}</td><td>{c['status']}</td>"
            f"<td>{', '.join(c.get('warnings') or [])}</td></tr>"
        )
    html = f"""<!DOCTYPE html>
<html><head><title>Control Reconciliation</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 2rem; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #ccc; padding: 0.5rem; text-align: right; }}
th:first-child, td:first-child {{ text-align: left; }}
.pass {{ background: #ecfdf5; }}
.fail {{ background: #fef2f2; }}
</style></head><body>
<h1>Control account reconciliation</h1>
<p>Company: {data['company_id']} | Branch: {data.get('branch_id') or 'all'} |
As of: {data['as_of_date']} | Overall: <strong>{data['overall_status']}</strong></p>
<table>
<thead><tr><th>Control</th><th>Subledger</th><th>GL</th><th>Delta</th><th>Status</th><th>Warnings</th></tr></thead>
<tbody>{rows or '<tr><td colspan="6">No controls (provision CoA; set branch for inventory/cash)</td></tr>'}</tbody>
</table>
<p><a href="/api/accounting/reconciliation/control?as_of_date={as_of}">JSON API</a></p>
</body></html>"""
    return HTMLResponse(content=html)


@router.get("/profit-and-loss", response_model=ProfitAndLossResponse)
def get_profit_and_loss(
    request: Request,
    from_date: date = Query(...),
    to_date: date = Query(...),
    branch_id: Optional[UUID] = Query(None),
    user_db=Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    bind_fastapi_request(request)
    user, _ = user_db
    company_id = _company_id(request, db, user)
    if from_date > to_date:
        raise HTTPException(status_code=400, detail="from_date must be <= to_date")

    guard_finance_report_access(
        db, user, company_id, "accounting.reports", MANAGEMENT, branch_id=branch_id
    )

    data = build_profit_and_loss(
        db,
        company_id=company_id,
        from_date=from_date,
        to_date=to_date,
        branch_id=branch_id,
    )
    return ProfitAndLossResponse(**data)


@router.get("/balance-sheet", response_model=BalanceSheetResponse)
def get_balance_sheet(
    request: Request,
    as_of_date: Optional[date] = Query(None),
    branch_id: Optional[UUID] = Query(None),
    user_db=Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    bind_fastapi_request(request)
    user, _ = user_db
    company_id = _company_id(request, db, user)
    as_of = as_of_date or date.today()

    guard_finance_report_access(
        db, user, company_id, "accounting.reports", MANAGEMENT, branch_id=branch_id
    )

    data = build_balance_sheet(
        db, company_id=company_id, as_of_date=as_of, branch_id=branch_id
    )
    return BalanceSheetResponse(**data)


@router.post("/fiscal-periods/{period_id}/close", status_code=204)
def close_period_endpoint(
    request: Request,
    period_id: UUID,
    branch_id: Optional[UUID] = Query(None, description="Branch scope for reconciliation gate"),
    close_notes: Optional[str] = Query(None),
    user_db=Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    bind_fastapi_request(request)
    user, _ = user_db
    company_id = _company_id(request, db, user)

    from app.dependencies import _user_has_permission

    if not _user_has_permission(db, user.id, "accounting.close_period"):
        raise HTTPException(status_code=403, detail="Permission denied: accounting.close_period")

    try:
        close_fiscal_period(
            db,
            company_id=company_id,
            period_id=period_id,
            closed_by=user.id,
            close_notes=close_notes,
            branch_id_for_recon=branch_id,
        )
        db.commit()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return None
