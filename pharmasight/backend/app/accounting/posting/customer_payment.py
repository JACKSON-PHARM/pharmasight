"""GL posting for customer AR collections."""
from __future__ import annotations

from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.accounting.constants import CONTROL_AR
from app.accounting.coa_service import control_account_map
from app.accounting.posting.cash_account import resolve_cash_line_account
from app.accounting.posting.engine import post_journal_for_operation
from app.accounting.posting.types import PostingLineSpec, PostingResult
from app.models.customer_financial import CustomerPayment

SOURCE_CUSTOMER_PAYMENT = "customer_payment"
KIND_PAYMENT = "customer_payment"


def _money(v) -> Decimal:
    return Decimal(str(v or 0))


def post_gl_for_customer_payment(
    db: Session,
    payment: CustomerPayment,
    *,
    posted_by: Optional[UUID],
) -> PostingResult:
    """
    Dr Cash / Cr AR when a customer payment is recorded.
    Uses payment.company_id and payment.branch_id from the operational document.
    """
    amount = _money(payment.amount)
    if amount <= 0:
        return PostingResult(False, None, "zero_amount")

    company_id = payment.company_id
    branch_id = payment.branch_id
    if company_id is None or branch_id is None:
        return PostingResult(False, None, "missing_company_or_branch")

    cash_acct_id, map_err = resolve_cash_line_account(
        db,
        company_id=company_id,
        branch_id=branch_id,
        source_type=SOURCE_CUSTOMER_PAYMENT,
        source_id=payment.id,
        posting_kind=KIND_PAYMENT,
        payment_method=payment.method,
    )
    if cash_acct_id is None:
        return PostingResult(False, None, map_err or "cash_gl_mapping_missing")

    accounts = control_account_map(db, company_id)
    return post_journal_for_operation(
        db,
        company_id=company_id,
        branch_id=branch_id,
        posting_date=payment.payment_date,
        source_type=SOURCE_CUSTOMER_PAYMENT,
        source_id=payment.id,
        posting_kind=KIND_PAYMENT,
        lines=[
            PostingLineSpec(
                account_id=cash_acct_id,
                debit=amount,
                description=f"Customer receipt — {payment.reference or payment.id}",
            ),
            PostingLineSpec(
                account_id=accounts[CONTROL_AR].id,
                credit=amount,
                description=f"AR settlement — {payment.reference or payment.id}",
            ),
        ],
        posted_by=posted_by,
        description=f"Customer payment {payment.id}",
        metadata={
            "method": payment.method,
            "customer_id": str(payment.customer_id),
        },
    )
