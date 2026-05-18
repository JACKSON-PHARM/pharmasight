"""GL posting for sales invoices (batch)."""
from __future__ import annotations

from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.accounting.constants import (
    CONTROL_AR,
    CONTROL_CASH,
    CONTROL_COGS,
    CONTROL_INVENTORY,
    CONTROL_REVENUE,
    CONTROL_VAT_OUTPUT,
)
from app.accounting.coa_service import control_account_map
from app.accounting.posting.cash_account import resolve_cash_line_account
from app.accounting.posting.engine import post_journal_for_operation
from app.accounting.posting.types import PostingLineSpec, PostingResult
from app.models.inventory import InventoryLedger
from app.models.sale import SalesInvoice

SOURCE_SALES_INVOICE = "sales_invoice"
KIND_REVENUE = "sale_revenue"
KIND_COGS = "sale_cogs"


def _money(v) -> Decimal:
    return Decimal(str(v or 0))


def _revenue_uses_cash(invoice: SalesInvoice) -> bool:
    """Cash-basis retail: Dr Cash when invoice is paid at batch without open AR."""
    ps = (invoice.payment_status or "").strip().upper()
    if ps == "PAID" and not invoice.customer_id:
        return True
    if ps == "PAID" and _money(invoice.balance) <= Decimal("0.01"):
        bal = _money(invoice.balance)
        if bal <= Decimal("0.01"):
            return True
    pm = (getattr(invoice, "payment_mode", None) or "").strip().lower()
    if ps == "PAID" and pm in ("cash", "mpesa", "card", "bank", "cheque"):
        if not invoice.customer_id:
            return True
        if _money(invoice.balance) <= Decimal("0.01"):
            return True
    return False


def _build_revenue_lines(
    accounts: dict,
    invoice: SalesInvoice,
    *,
    cash_account_id: Optional[UUID] = None,
) -> List[PostingLineSpec]:
    exclusive = _money(invoice.total_exclusive)
    vat = _money(invoice.vat_amount)
    inclusive = _money(invoice.total_inclusive)
    if inclusive <= 0:
        return []
    if exclusive <= 0 and inclusive > 0:
        exclusive = inclusive - vat
    if exclusive < 0:
        exclusive = Decimal("0")
    if vat < 0:
        vat = Decimal("0")
    if exclusive + vat != inclusive and inclusive > exclusive:
        vat = inclusive - exclusive

    uses_cash = _revenue_uses_cash(invoice)
    if uses_cash:
        debit_acct_id = cash_account_id or accounts[CONTROL_CASH].id
        debit_label = "Cash"
    else:
        debit_acct_id = accounts[CONTROL_AR].id
        debit_label = "AR"
    lines: List[PostingLineSpec] = [
        PostingLineSpec(
            account_id=debit_acct_id,
            debit=inclusive,
            description=f"{debit_label} — {invoice.invoice_no}",
        ),
        PostingLineSpec(
            account_id=accounts[CONTROL_REVENUE].id,
            credit=exclusive,
            description=f"Revenue — {invoice.invoice_no}",
        ),
    ]
    if vat > 0:
        lines.append(
            PostingLineSpec(
                account_id=accounts[CONTROL_VAT_OUTPUT].id,
                credit=vat,
                description=f"VAT output — {invoice.invoice_no}",
            )
        )
    elif inclusive > exclusive:
        lines[1] = PostingLineSpec(
            account_id=accounts[CONTROL_REVENUE].id,
            credit=inclusive,
            description=f"Revenue — {invoice.invoice_no}",
        )
    return lines


def _sum_sale_cogs(ledger_entries: List[InventoryLedger], invoice_id: UUID) -> Decimal:
    total = Decimal("0")
    for e in ledger_entries:
        if (
            e.reference_type == "sales_invoice"
            and e.reference_id == invoice_id
            and e.transaction_type == "SALE"
        ):
            total += _money(e.total_cost)
    return total


def post_gl_for_sales_invoice_batch(
    db: Session,
    invoice: SalesInvoice,
    ledger_entries: List[InventoryLedger],
    *,
    posted_by: Optional[UUID],
) -> List[PostingResult]:
    """
    Materialize sale_revenue and sale_cogs journals. Soft-fail per kind.
    Call inside the same transaction as inventory/subledger posts when possible.
    """
    company_id = invoice.company_id
    branch_id = invoice.branch_id
    posting_date = invoice.invoice_date
    accounts = control_account_map(db, company_id)
    results: List[PostingResult] = []

    cash_acct_id: Optional[UUID] = None
    if _revenue_uses_cash(invoice):
        cash_acct_id, map_err = resolve_cash_line_account(
            db,
            company_id=company_id,
            branch_id=branch_id,
            source_type=SOURCE_SALES_INVOICE,
            source_id=invoice.id,
            posting_kind=KIND_REVENUE,
            payment_method=getattr(invoice, "payment_mode", None),
        )
        if cash_acct_id is None:
            results.append(PostingResult(False, None, map_err or "cash_gl_mapping_missing"))
            return results

    rev_lines = _build_revenue_lines(accounts, invoice, cash_account_id=cash_acct_id)
    if rev_lines:
        results.append(
            post_journal_for_operation(
                db,
                company_id=company_id,
                branch_id=branch_id,
                posting_date=posting_date,
                source_type=SOURCE_SALES_INVOICE,
                source_id=invoice.id,
                posting_kind=KIND_REVENUE,
                lines=rev_lines,
                posted_by=posted_by,
                description=f"Sales revenue {invoice.invoice_no}",
                metadata={"invoice_no": invoice.invoice_no, "doctrine": "operational_ar_m1"},
            )
        )

    cogs_amount = _sum_sale_cogs(ledger_entries, invoice.id)
    if cogs_amount > 0:
        results.append(
            post_journal_for_operation(
                db,
                company_id=company_id,
                branch_id=branch_id,
                posting_date=posting_date,
                source_type=SOURCE_SALES_INVOICE,
                source_id=invoice.id,
                posting_kind=KIND_COGS,
                lines=[
                    PostingLineSpec(
                        account_id=accounts[CONTROL_COGS].id,
                        debit=cogs_amount,
                        description=f"COGS — {invoice.invoice_no}",
                    ),
                    PostingLineSpec(
                        account_id=accounts[CONTROL_INVENTORY].id,
                        credit=cogs_amount,
                        description=f"Inventory relief — {invoice.invoice_no}",
                    ),
                ],
                posted_by=posted_by,
                description=f"Sales COGS {invoice.invoice_no}",
                metadata={"invoice_no": invoice.invoice_no, "cogs_amount": str(cogs_amount)},
            )
        )

    return results
