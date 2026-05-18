"""Resolve cash GL line for payment postings."""
from __future__ import annotations

from typing import Optional, Tuple
from uuid import UUID

from sqlalchemy.orm import Session

from app.accounting.cash_gl_mapping import resolve_cash_gl_account_id
from app.accounting.posting.engine import record_posting_failure


def resolve_cash_line_account(
    db: Session,
    *,
    company_id: UUID,
    branch_id: UUID,
    source_type: str,
    source_id: UUID,
    posting_kind: str,
    payment_method: Optional[str],
    cashbook_account_id: Optional[UUID] = None,
) -> Tuple[Optional[UUID], Optional[str]]:
    """
    Returns (account_id, error_message). error_message set when mapping missing.
    """
    account_id = resolve_cash_gl_account_id(
        db,
        company_id,
        payment_method,
        cashbook_account_id=cashbook_account_id,
    )
    if account_id is not None:
        return account_id, None

    mode = (payment_method or "cash").strip().lower()
    msg = (
        f"No GL cash account mapping for payment_mode={mode!r}. "
        f"Configure company_settings.accounting_cash_gl_by_payment_mode "
        f"(keys: payment mode, cashbook_account_id, or 'default')."
    )
    record_posting_failure(
        db,
        company_id=company_id,
        branch_id=branch_id,
        source_type=source_type,
        source_id=source_id,
        posting_kind=posting_kind,
        error_message=msg,
    )
    return None, msg
