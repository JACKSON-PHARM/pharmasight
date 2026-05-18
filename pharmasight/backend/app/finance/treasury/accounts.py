"""
Treasury account provisioning and resolution (E5).
"""
from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.finance.governance.classification import BRANCH_FINANCE, normalize_classification
from app.finance.doctrine.treasury import assert_treasury_label_safe
from app.finance.treasury.doctrine import DEFAULT_CLASSIFICATION_BY_ROUTING, ROUTING_TYPES
from app.models.cashbook_account import CashbookAccount


def ensure_branch_treasury_defaults(db: Session, *, company_id: UUID, branch_id: UUID) -> List[CashbookAccount]:
    """Provision standard till/mpesa/bank routing buckets for a branch (idempotent)."""
    specs = [
        ("TILL", "Branch cash till", "till", "cash"),
        ("MPESA", "Branch M-Pesa", "mpesa", "mpesa"),
        ("BANK", "Branch bank", "bank", "bank"),
    ]
    created: List[CashbookAccount] = []
    for code, name, routing, mode in specs:
        existing = (
            db.query(CashbookAccount)
            .filter(
                CashbookAccount.company_id == company_id,
                CashbookAccount.account_code == f"{branch_id}:{code}",
            )
            .first()
        )
        if existing:
            continue
        row = CashbookAccount(
            company_id=company_id,
            branch_id=branch_id,
            account_code=f"{branch_id}:{code}",
            name=name,
            routing_type=routing,
            payment_mode=mode,
            classification=DEFAULT_CLASSIFICATION_BY_ROUTING.get(routing, BRANCH_FINANCE),
        )
        db.add(row)
        created.append(row)
    if created:
        db.flush()
    return created


def resolve_treasury_account_for_payment_mode(
    db: Session,
    *,
    company_id: UUID,
    branch_id: UUID,
    payment_mode: str,
) -> Optional[CashbookAccount]:
    mode = (payment_mode or "cash").strip().lower()
    routing = "till" if mode == "cash" else mode if mode in ("mpesa", "bank") else "till"
    code = f"{branch_id}:{routing.upper()}"
    return (
        db.query(CashbookAccount)
        .filter(
            CashbookAccount.company_id == company_id,
            CashbookAccount.account_code == code,
            CashbookAccount.is_active.is_(True),
        )
        .first()
    )


def list_treasury_accounts(
    db: Session,
    *,
    company_id: UUID,
    branch_id: Optional[UUID] = None,
    active_only: bool = True,
) -> List[CashbookAccount]:
    q = db.query(CashbookAccount).filter(CashbookAccount.company_id == company_id)
    if branch_id is not None:
        q = q.filter(
            (CashbookAccount.branch_id == branch_id) | (CashbookAccount.branch_id.is_(None))
        )
    if active_only:
        q = q.filter(CashbookAccount.is_active.is_(True))
    return q.order_by(CashbookAccount.account_code).all()


def validate_treasury_name(name: str) -> str:
    assert_treasury_label_safe(name)
    return name.strip()


def validate_routing_type(routing_type: str) -> str:
    rt = (routing_type or "").strip().lower()
    if rt not in ROUTING_TYPES:
        raise ValueError(f"Invalid routing_type: {routing_type}")
    return rt


def validate_account_classification(classification: str) -> str:
    return normalize_classification(classification, default=BRANCH_FINANCE)
