"""Map payment methods (and optional cashbook accounts) to GL cash accounts."""
from __future__ import annotations

from typing import Dict, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.accounting.company_settings import cash_gl_account_map
from app.accounting.constants import CONTROL_CASH
from app.accounting.coa_service import control_account_map, resolve_control_account
from app.models.accounting import ChartOfAccount


def normalize_payment_mode(method: Optional[str]) -> str:
    m = (method or "").strip().lower()
    if m in ("m-pesa", "mpesa", "mobile_money"):
        return "mpesa"
    if m in ("bank", "bank_transfer", "cheque", "check", "rtgs", "eft"):
        return "bank"
    if m in ("card", "visa", "mastercard", "debit", "credit_card"):
        return "card"
    return m or "cash"


def resolve_cash_gl_account_id(
    db: Session,
    company_id: UUID,
    payment_method: Optional[str],
    *,
    cashbook_account_id: Optional[UUID] = None,
) -> Optional[UUID]:
    """
    Resolve GL cash account from company_settings.accounting_cash_gl_by_payment_mode.

    Lookup order: cashbook_account_id (string key) → normalized payment_mode → "default".
    Returns None when unmapped (caller records gl_posting_failure).
    """
    mapping: Dict[str, str] = cash_gl_account_map(db, company_id)
    if not mapping:
        return None

    keys_to_try = []
    if cashbook_account_id is not None:
        keys_to_try.append(str(cashbook_account_id))
    keys_to_try.append(normalize_payment_mode(payment_method))
    keys_to_try.append("default")

    for key in keys_to_try:
        raw = mapping.get(key)
        if not raw:
            continue
        row = (
            db.query(ChartOfAccount)
            .filter(
                ChartOfAccount.id == UUID(str(raw)),
                ChartOfAccount.company_id == company_id,
                ChartOfAccount.is_active.is_(True),
            )
            .first()
        )
        if row:
            return row.id
    return None


def default_cash_gl_account_id(db: Session, company_id: UUID) -> UUID:
    """Control Cash account — use only when seeding settings, not for silent posting fallback."""
    return resolve_control_account(db, company_id, CONTROL_CASH).id
