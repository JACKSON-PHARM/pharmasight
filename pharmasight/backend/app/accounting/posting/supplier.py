"""GL posting for supplier AP flows."""
from __future__ import annotations

from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.accounting.constants import (
    CONTROL_AP,
    CONTROL_EXPENSE,
    CONTROL_INVENTORY,
    CONTROL_VAT_INPUT,
)
from app.accounting.coa_service import control_account_map, resolve_control_account
from app.accounting.posting.cash_account import resolve_cash_line_account
from app.accounting.posting.engine import post_journal_for_operation, post_journal_safe
from app.accounting.posting.types import PostingLineSpec, PostingResult
from app.models.purchase import SupplierInvoice
from app.models.supplier_financial import SupplierPayment

SOURCE_SUPPLIER_INVOICE = "supplier_invoice"
SOURCE_SUPPLIER_PAYMENT = "supplier_payment"
KIND_INVOICE = "supplier_invoice"
KIND_PAYMENT = "supplier_payment"


def _money(v) -> Decimal:
    return Decimal(str(v or 0))


def _invoice_uses_expense(invoice: SupplierInvoice) -> bool:
    ref = (invoice.internal_reference or invoice.reference or "").upper()
    return "SERVICE" in ref or "OPEX" in ref


def post_gl_for_supplier_invoice_batch(
    db: Session,
    invoice: SupplierInvoice,
    *,
    posted_by: Optional[UUID],
) -> List[PostingResult]:
    accounts = control_account_map(db, invoice.company_id)
    exclusive = _money(invoice.total_exclusive)
    vat = _money(invoice.vat_amount)
    inclusive = _money(invoice.total_inclusive)
    if inclusive <= 0:
        return []
    if exclusive <= 0 and inclusive > 0:
        exclusive = inclusive - vat
    debit_account = accounts[CONTROL_EXPENSE] if _invoice_uses_expense(invoice) else accounts[CONTROL_INVENTORY]
    lines: List[PostingLineSpec] = [
        PostingLineSpec(
            account_id=debit_account.id,
            debit=exclusive,
            description=f"Purchase — {invoice.invoice_number}",
        ),
    ]
    if vat > 0:
        lines.append(
            PostingLineSpec(
                account_id=accounts[CONTROL_VAT_INPUT].id,
                debit=vat,
                description=f"VAT input — {invoice.invoice_number}",
            )
        )
    lines.append(
        PostingLineSpec(
            account_id=accounts[CONTROL_AP].id,
            credit=inclusive,
            description=f"AP — {invoice.invoice_number}",
        )
    )
    return [
        post_journal_safe(
            db,
            company_id=invoice.company_id,
            branch_id=invoice.branch_id,
            posting_date=invoice.invoice_date,
            source_type=SOURCE_SUPPLIER_INVOICE,
            source_id=invoice.id,
            posting_kind=KIND_INVOICE,
            lines=lines,
            posted_by=posted_by,
            description=f"Supplier invoice {invoice.invoice_number}",
            metadata={"invoice_number": invoice.invoice_number},
        )
    ]


def post_gl_for_supplier_payment(
    db: Session,
    payment: SupplierPayment,
    *,
    posted_by: Optional[UUID],
) -> PostingResult:
    amount = _money(payment.amount)
    if amount <= 0:
        return PostingResult(False, None, "zero_amount")
    cash_acct_id, map_err = resolve_cash_line_account(
        db,
        company_id=payment.company_id,
        branch_id=payment.branch_id,
        source_type=SOURCE_SUPPLIER_PAYMENT,
        source_id=payment.id,
        posting_kind=KIND_PAYMENT,
        payment_method=payment.method,
    )
    if cash_acct_id is None:
        return PostingResult(False, None, map_err or "cash_gl_mapping_missing")

    accounts = control_account_map(db, payment.company_id)
    return post_journal_for_operation(
        db,
        company_id=payment.company_id,
        branch_id=payment.branch_id,
        posting_date=payment.payment_date,
        source_type=SOURCE_SUPPLIER_PAYMENT,
        source_id=payment.id,
        posting_kind=KIND_PAYMENT,
        lines=[
            PostingLineSpec(
                account_id=accounts[CONTROL_AP].id,
                debit=amount,
                description=f"AP settlement — {payment.reference or payment.id}",
            ),
            PostingLineSpec(
                account_id=cash_acct_id,
                credit=amount,
                description="Cash disbursement",
            ),
        ],
        posted_by=posted_by,
        description=f"Supplier payment {payment.id}",
        metadata={"method": payment.method},
    )
