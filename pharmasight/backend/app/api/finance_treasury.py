"""
Treasury routing dimension API (E5) — NOT accounting accounts.
"""
from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_tenant_db
from app.finance.governance.access import deny_unless_finance_permission, resolve_finance_branch_id
from app.finance.governance.classification import BRANCH_FINANCE, EXECUTIVE, MANAGEMENT
from app.finance.governance.context import assert_access, resolve_finance_access_context
from app.finance.governance.request_context import bind_fastapi_request
from app.finance.treasury.accounts import (
    ensure_branch_treasury_defaults,
    list_treasury_accounts,
    validate_account_classification,
    validate_routing_type,
    validate_treasury_name,
)
from app.models import User
from app.models.cashbook_account import CashbookAccount
from app.schemas.finance_e5 import (
    CashbookAccountCreate,
    CashbookAccountResponse,
    TreasuryProvisionResponse,
)

router = APIRouter(prefix="/finance/treasury", tags=["Finance Treasury"])


def _company_id(request: Request, db: Session, user: User) -> UUID:
    cid = getattr(request.state, "effective_company_id", None)
    if cid is not None:
        return cid
    from app.dependencies import get_effective_company_id_for_user

    cid = get_effective_company_id_for_user(db, user)
    if cid is None:
        raise HTTPException(status_code=400, detail="Company context not available")
    return cid


@router.get("/accounts", response_model=List[CashbookAccountResponse])
def list_accounts(
    request: Request,
    branch_id: Optional[UUID] = Query(None),
    user_db=Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    bind_fastapi_request(request)
    user, _ = user_db
    company_id = _company_id(request, db, user)
    ctx = resolve_finance_access_context(user, db, company_id)
    if branch_id:
        resolve_finance_branch_id(
            ctx,
            db,
            branch_id_query=branch_id,
            classification=BRANCH_FINANCE,
            permission="finance.cashbook.view_branch",
            registry_id="treasury.list_accounts",
        )
    else:
        deny_unless_finance_permission(
            db, user, company_id, "finance.cashbook.view_company", EXECUTIVE,
            registry_id="treasury.list_accounts",
        )
    rows = list_treasury_accounts(db, company_id=company_id, branch_id=branch_id)
    return rows


@router.post("/accounts", response_model=CashbookAccountResponse, status_code=201)
def create_account(
    body: CashbookAccountCreate,
    request: Request,
    user_db=Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    bind_fastapi_request(request)
    user, _ = user_db
    company_id = _company_id(request, db, user)
    ctx = resolve_finance_access_context(user, db, company_id)
    classification = validate_account_classification(body.classification)
    if body.branch_id:
        resolve_finance_branch_id(
            ctx,
            db,
            branch_id_query=body.branch_id,
            classification=classification,
            permission="finance.cashbook.reconcile_branch",
            registry_id="treasury.create_account",
        )
    else:
        assert_access(
            ctx, EXECUTIVE, db, permission="finance.cashbook.view_company",
            registry_id="treasury.create_account",
        )
    routing = validate_routing_type(body.routing_type)
    validate_treasury_name(body.name)
    existing = (
        db.query(CashbookAccount)
        .filter(CashbookAccount.company_id == company_id, CashbookAccount.account_code == body.account_code)
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="account_code already exists")
    row = CashbookAccount(
        company_id=company_id,
        branch_id=body.branch_id,
        account_code=body.account_code,
        name=body.name,
        routing_type=routing,
        payment_mode=body.payment_mode,
        classification=classification,
        notes=body.notes,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.post("/branches/{branch_id}/provision-defaults", response_model=TreasuryProvisionResponse)
def provision_branch_defaults(
    branch_id: UUID,
    request: Request,
    user_db=Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    bind_fastapi_request(request)
    user, _ = user_db
    company_id = _company_id(request, db, user)
    ctx = resolve_finance_access_context(user, db, company_id)
    resolve_finance_branch_id(
        ctx,
        db,
        branch_id_query=branch_id,
        classification=BRANCH_FINANCE,
        permission="finance.cashbook.reconcile_branch",
        registry_id="treasury.provision_defaults",
    )
    created = ensure_branch_treasury_defaults(db, company_id=company_id, branch_id=branch_id)
    db.commit()
    all_rows = list_treasury_accounts(db, company_id=company_id, branch_id=branch_id)
    return TreasuryProvisionResponse(created_count=len(created), accounts=all_rows)
