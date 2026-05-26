"""
Certified operational AR customer statement (operational_ar_v1).

Authoritative sources ONLY:
  - customer_ledger_entries
  - sales_invoices / customer_payments / credit_notes for reference labels

NOT used: financial_events, projections, journal proposals, treasury, branch confidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.company import Branch, Company
from app.models.customer import Customer
from app.models.customer_financial import CustomerLedgerEntry, CustomerPayment
from app.models.sale import CreditNote, InvoicePayment, SalesInvoice
from app.models.user import User
from app.services.customer_ledger_service import CustomerLedgerService

STATEMENT_DOCTRINE = "operational_ar_v1"
TOLERANCE = Decimal("0.05")
Q2 = Decimal("0.01")


@dataclass(frozen=True)
class StatementBuildContext:
    company: Company
    branch: Optional[Branch]
    customer: Customer
    from_date: date
    to_date: date
    branch_id: Optional[UUID]
    prepared_by: Optional[str]
    statement_type: str = "summary"  # summary | detailed


def _quantize_money(v: Decimal) -> Decimal:
    return v.quantize(Q2, rounding=ROUND_HALF_UP)


def _entry_sort_key(e: CustomerLedgerEntry) -> Tuple:
    return (e.date, e.created_at or datetime.min.replace(tzinfo=timezone.utc), e.id)


def fetch_ledger_entries_ordered(
    db: Session,
    *,
    company_id: UUID,
    customer_id: UUID,
    branch_id: Optional[UUID],
    through_date: date,
) -> List[CustomerLedgerEntry]:
    q = db.query(CustomerLedgerEntry).filter(
        CustomerLedgerEntry.company_id == company_id,
        CustomerLedgerEntry.customer_id == customer_id,
        CustomerLedgerEntry.date <= through_date,
    )
    if branch_id is not None:
        q = q.filter(CustomerLedgerEntry.branch_id == branch_id)
    rows = q.all()
    rows.sort(key=_entry_sort_key)
    return rows


def sum_net_balance(entries: List[CustomerLedgerEntry], *, before: Optional[date] = None, through: Optional[date] = None) -> Decimal:
    total = Decimal("0")
    for e in entries:
        if before is not None and e.date >= before:
            continue
        if through is not None and e.date > through:
            continue
        total += Decimal(str(e.debit or 0)) - Decimal(str(e.credit or 0))
    return _quantize_money(total)


def _resolve_references(
    db: Session,
    entries: List[CustomerLedgerEntry],
) -> Dict[Tuple[str, UUID], Dict[str, Optional[str]]]:
    """Batch-load invoice nos, payment refs, credit note nos for statement lines."""
    inv_ids = [e.reference_id for e in entries if e.entry_type == "invoice" and e.reference_id]
    pay_ids = [e.reference_id for e in entries if e.entry_type == "payment" and e.reference_id]
    cn_ids = [e.reference_id for e in entries if e.entry_type == "credit_note" and e.reference_id]

    out: Dict[Tuple[str, UUID], Dict[str, Optional[str]]] = {}
    if inv_ids:
        for row in db.query(SalesInvoice.id, SalesInvoice.invoice_no).filter(SalesInvoice.id.in_(inv_ids)).all():
            out[("invoice", row[0])] = {"reference": row[1], "description": "Invoice"}
    if pay_ids:
        for row in (
            db.query(CustomerPayment.id, CustomerPayment.reference, CustomerPayment.method)
            .filter(CustomerPayment.id.in_(pay_ids))
            .all()
        ):
            out[("payment", row[0])] = {
                "reference": row[1] or row[2],
                "description": "Payment",
                "payment_method": row[2],
            }
        unresolved_pay_ids = [pid for pid in pay_ids if ("payment", pid) not in out]
        if unresolved_pay_ids:
            for row in (
                db.query(InvoicePayment.id, InvoicePayment.payment_reference, InvoicePayment.payment_mode)
                .filter(InvoicePayment.id.in_(unresolved_pay_ids))
                .all()
            ):
                out[("payment", row[0])] = {
                    "reference": row[1] or row[2],
                    "description": "Invoice payment",
                    "payment_method": row[2],
                }
    if cn_ids:
        for row in db.query(CreditNote.id, CreditNote.credit_note_no).filter(CreditNote.id.in_(cn_ids)).all():
            out[("credit_note", row[0])] = {"reference": row[1], "description": "Credit note"}
    if any(e.entry_type == "opening_balance" for e in entries):
        out[("opening_balance", UUID(int=0))] = {"reference": None, "description": "Opening balance"}
    return out


def _line_description(entry_type: str, ref_map: Dict[Tuple[str, UUID], Dict[str, Optional[str]]], reference_id: Optional[UUID]) -> Tuple[str, Optional[str]]:
    if entry_type == "opening_balance":
        return "Opening balance", None
    key = (entry_type, reference_id) if reference_id else None
    meta = ref_map.get(key) if key else None
    if meta:
        return meta.get("description") or entry_type.replace("_", " ").title(), meta.get("reference")
    return entry_type.replace("_", " ").title(), None


def build_statement_lines(
    all_entries: List[CustomerLedgerEntry],
    *,
    from_date: date,
    to_date: date,
    opening_balance: Decimal,
    ref_map: Dict[Tuple[str, UUID], Dict[str, Optional[str]]],
) -> Tuple[List[Dict[str, Any]], Decimal]:
    """
    Deterministic running balance: opening + sum(debit-credit) in period.
    Order: date ASC, created_at ASC, id ASC (entries pre-sorted).
    """
    lines: List[Dict[str, Any]] = []
    running = opening_balance
    for e in all_entries:
        if e.date < from_date or e.date > to_date:
            continue
        debit = _quantize_money(Decimal(str(e.debit or 0)))
        credit = _quantize_money(Decimal(str(e.credit or 0)))
        running = _quantize_money(running + debit - credit)
        desc, ref = _line_description(e.entry_type, ref_map, e.reference_id)
        lines.append(
            {
                "date": e.date,
                "entry_type": e.entry_type,
                "description": desc,
                "reference": ref,
                "debit": debit,
                "credit": credit,
                "balance": running,
            }
        )
    closing = running if lines else opening_balance
    return lines, closing


def _expand_statement_lines_detailed(
    db: Session,
    summary_lines: List[Dict[str, Any]],
    ref_map: Dict[Tuple[str, UUID], Dict[str, Optional[str]]],
) -> List[Dict[str, Any]]:
    """Insert invoice line-item rows beneath each invoice ledger row."""
    from sqlalchemy.orm import selectinload
    from app.models import SalesInvoice, SalesInvoiceItem

    inv_nos = [
        str(ln.get("reference"))
        for ln in summary_lines
        if ln.get("entry_type") == "invoice" and ln.get("reference")
    ]
    inv_by_no: Dict[str, SalesInvoice] = {}
    if inv_nos:
        for inv in (
            db.query(SalesInvoice)
            .options(selectinload(SalesInvoice.items).selectinload(SalesInvoiceItem.item))
            .filter(SalesInvoice.invoice_no.in_(inv_nos))
            .all()
        ):
            inv_by_no[inv.invoice_no] = inv

    expanded: List[Dict[str, Any]] = []
    for ln in summary_lines:
        expanded.append({**ln, "is_detail": False})
        if ln.get("entry_type") != "invoice":
            continue
        inv = inv_by_no.get(str(ln.get("reference") or ""))
        if not inv or not inv.items:
            continue
        for item in inv.items:
            name = getattr(item, "item_name", None) or (
                item.item.name if getattr(item, "item", None) else "Item"
            )
            qty = Decimal(str(item.quantity or 0))
            unit = item.unit_name or ""
            line_total = Decimal(str(item.line_total_inclusive or item.line_total_exclusive or 0))
            expanded.append(
                {
                    "date": ln["date"],
                    "entry_type": "invoice_line",
                    "description": f"  · {name} × {qty:g} {unit}".strip(),
                    "reference": None,
                    "debit": Decimal("0"),
                    "credit": Decimal("0"),
                    "balance": ln["balance"],
                    "is_detail": True,
                    "line_amount": _quantize_money(line_total),
                }
            )
    return expanded


def sum_invoice_open_balances(
    db: Session,
    *,
    company_id: UUID,
    customer_id: UUID,
    branch_id: Optional[UUID],
    as_of_date: date,
) -> Decimal:
    """
    Reconciliation assumption: open AR on posted invoices = sum(sales_invoices.balance)
    for BATCHED/PAID invoices with customer_id, invoice_date <= as_of_date.
    Credit notes may not yet reduce invoice.balance — expect WARNINGS when they exist.
    """
    q = db.query(SalesInvoice).filter(
        SalesInvoice.company_id == company_id,
        SalesInvoice.customer_id == customer_id,
        SalesInvoice.status.in_(("BATCHED", "PAID")),
        SalesInvoice.invoice_date <= as_of_date,
    )
    if branch_id is not None:
        q = q.filter(SalesInvoice.branch_id == branch_id)
    invoices = q.all()
    total = Decimal("0")
    for inv in invoices:
        bal = inv.balance
        if bal is None:
            from app.services.customer_invoice_payment_service import outstanding_after_settlements

            bal = outstanding_after_settlements(db, inv)
        total += Decimal(str(bal or 0))
    return _quantize_money(total)


def build_statement_integrity(
    db: Session,
    *,
    company_id: UUID,
    customer_id: UUID,
    branch_id: Optional[UUID],
    to_date: date,
    ledger_closing_balance: Decimal,
) -> Dict[str, Any]:
    """
    Cross-check ledger closing vs invoice open balances vs ledger service outstanding.
    PASS: |ledger - invoice_open| <= TOLERANCE and ledger service matches.
    PASS_WITH_WARNINGS: non-fatal classified gaps only.
    FAIL: material divergence.
    """
    warnings: List[str] = []
    invoice_open = sum_invoice_open_balances(
        db,
        company_id=company_id,
        customer_id=customer_id,
        branch_id=branch_id,
        as_of_date=to_date,
    )
    ledger_outstanding = CustomerLedgerService.get_outstanding_balance(
        db,
        customer_id,
        company_id,
        branch_id=branch_id,
        as_of_date=to_date,
    )
    ledger_outstanding = _quantize_money(ledger_outstanding)
    ledger_closing = _quantize_money(ledger_closing_balance)

    delta_invoices = ledger_closing - invoice_open
    delta_service = ledger_closing - ledger_outstanding

    if abs(delta_service) > TOLERANCE:
        warnings.append(
            f"ledger_closing ({ledger_closing}) differs from ledger_service_outstanding ({ledger_outstanding})"
        )

    cn_count = (
        db.query(CreditNote)
        .join(SalesInvoice, SalesInvoice.id == CreditNote.original_invoice_id)
        .filter(
            SalesInvoice.company_id == company_id,
            SalesInvoice.customer_id == customer_id,
            CreditNote.posting_status == "posted",
            CreditNote.credit_note_date <= to_date,
        )
    )
    if branch_id is not None:
        cn_count = cn_count.filter(CreditNote.branch_id == branch_id)
    if cn_count.count() > 0:
        posted_cn_without_ledger = 0
        for cn in cn_count.all():
            has = (
                db.query(CustomerLedgerEntry.id)
                .filter(
                    CustomerLedgerEntry.company_id == company_id,
                    CustomerLedgerEntry.entry_type == "credit_note",
                    CustomerLedgerEntry.reference_id == cn.id,
                )
                .first()
            )
            if not has:
                posted_cn_without_ledger += 1
        if posted_cn_without_ledger:
            warnings.append(
                f"{posted_cn_without_ledger} posted credit note(s) without customer ledger credit (invoice.balance may be overstated)"
            )

    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if customer and Decimal(str(customer.opening_balance or 0)) != 0:
        if not (
            db.query(CustomerLedgerEntry.id)
            .filter(
                CustomerLedgerEntry.company_id == company_id,
                CustomerLedgerEntry.customer_id == customer_id,
                CustomerLedgerEntry.entry_type == "opening_balance",
            )
            .first()
        ):
            warnings.append("customers.opening_balance is set but no opening_balance ledger row exists")

    if abs(delta_invoices) > TOLERANCE:
        if ledger_closing <= -TOLERANCE and invoice_open <= TOLERANCE:
            warnings.append(
                f"Customer account in credit ({ledger_closing}); ledger vs open invoices delta {delta_invoices} "
                "(historical payments may pre-date invoice debits — repaired on load when possible)"
            )
            status = "PASS_WITH_WARNINGS"
        elif ledger_closing > TOLERANCE and abs(delta_invoices) <= max(TOLERANCE * 20, Decimal("1.00")):
            warnings.append(
                f"Minor ledger vs invoice open delta ({delta_invoices}); within legacy tolerance"
            )
            status = "PASS_WITH_WARNINGS"
        else:
            status = "FAIL"
            warnings.append(
                f"ledger_closing ({ledger_closing}) vs invoice_open_balance_sum ({invoice_open}): delta {delta_invoices}"
            )
    elif warnings:
        status = "PASS_WITH_WARNINGS"
    else:
        status = "PASS"

    return {
        "ledger_closing_balance": ledger_closing,
        "invoice_open_balance_sum": invoice_open,
        "ledger_service_outstanding": ledger_outstanding,
        "delta": _quantize_money(delta_invoices),
        "status": status,
        "warnings": warnings,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "branch_id": str(branch_id) if branch_id else None,
        "customer_id": str(customer_id),
        "doctrine": STATEMENT_DOCTRINE,
    }


def build_operational_customer_statement(
    db: Session,
    ctx: StatementBuildContext,
) -> Dict[str, Any]:
    company_id = ctx.company.id
    customer_id = ctx.customer.id
    branch_id = ctx.branch_id

    from app.services.customer_invoice_payment_service import repair_customer_ar_for_statement

    repair_customer_ar_for_statement(
        db,
        company_id=company_id,
        customer_id=customer_id,
        branch_id=branch_id,
    )

    all_entries = fetch_ledger_entries_ordered(
        db,
        company_id=company_id,
        customer_id=customer_id,
        branch_id=branch_id,
        through_date=ctx.to_date,
    )
    opening_balance = sum_net_balance(all_entries, before=ctx.from_date)
    period_entries = [e for e in all_entries if ctx.from_date <= e.date <= ctx.to_date]
    ref_map = _resolve_references(db, period_entries)
    lines, closing_balance = build_statement_lines(
        all_entries,
        from_date=ctx.from_date,
        to_date=ctx.to_date,
        opening_balance=opening_balance,
        ref_map=ref_map,
    )
    ledger_closing = CustomerLedgerService.get_outstanding_balance(
        db,
        customer_id,
        company_id,
        branch_id=branch_id,
        as_of_date=ctx.to_date,
    )
    ledger_closing = _quantize_money(ledger_closing)
    if abs(ledger_closing - closing_balance) > TOLERANCE:
        closing_balance = ledger_closing
    statement_type = (ctx.statement_type or "summary").strip().lower()
    if statement_type == "detailed":
        lines = _expand_statement_lines_detailed(db, lines, ref_map)
    integrity = build_statement_integrity(
        db,
        company_id=company_id,
        customer_id=customer_id,
        branch_id=branch_id,
        to_date=ctx.to_date,
        ledger_closing_balance=closing_balance,
    )

    return {
        "customer_id": customer_id,
        "customer_name": ctx.customer.name,
        "customer_pin": ctx.customer.pin,
        "company_id": company_id,
        "company_name": ctx.company.name,
        "branch_id": branch_id,
        "branch_name": ctx.branch.name if ctx.branch else None,
        "from_date": ctx.from_date,
        "to_date": ctx.to_date,
        "opening_balance": opening_balance,
        "closing_balance": closing_balance,
        "lines": lines,
        "statement_type": statement_type,
        "statement_integrity": integrity,
        "prepared_by": ctx.prepared_by,
        "doctrine": STATEMENT_DOCTRINE,
    }
