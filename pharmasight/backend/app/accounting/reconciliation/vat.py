"""
VAT reconciliation — GL vs operational invoice VAT (always); KRA submission layer when enabled.

Doctrine:
- GL always reflects item/invoice VAT (zero-rated → 0, standard → line vat_amount). Never strip VAT from posting.
- companies.kra_enabled gates **authority reporting** (eTIMS submitted totals), not GL line construction.
- Does not duplicate eTIMS/OSCU tax math.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.accounting.constants import CONTROL_VAT_INPUT, CONTROL_VAT_OUTPUT
from app.accounting.coa_service import control_account_map
from app.accounting.posting.engine import build_idempotency_key
from app.models.accounting import GlJournalEntry, GlJournalLine
from app.models.purchase import SupplierInvoice
from app.models.sale import CreditNote, SalesInvoice
from app.services.etims.kra_company_activation import company_kra_execution_enabled

RECON_TOLERANCE = Decimal("0.05")
Q2 = Decimal("0.01")

_SALES_POSTED_STATUSES = ("BATCHED", "PAID")
_KIND_SALE_REVENUE = "sale_revenue"
_KIND_SUPPLIER_INVOICE = "supplier_invoice"
_KIND_CREDIT_NOTE_REVENUE = "credit_note_revenue"


def _q(v: Decimal) -> Decimal:
    return v.quantize(Q2, rounding=ROUND_HALF_UP)


def _money(v) -> Decimal:
    return _q(Decimal(str(v or 0)))


def gl_vat_period_movement(
    db: Session,
    *,
    company_id: UUID,
    account_id: UUID,
    normal_credit: bool,
    from_date: date,
    to_date: date,
    branch_id: Optional[UUID],
) -> Decimal:
    """Net VAT movement on account within inclusive posting_date range."""
    q = (
        db.query(
            func.coalesce(func.sum(GlJournalLine.debit), 0),
            func.coalesce(func.sum(GlJournalLine.credit), 0),
        )
        .join(GlJournalEntry, GlJournalEntry.id == GlJournalLine.journal_entry_id)
        .filter(
            GlJournalEntry.company_id == company_id,
            GlJournalEntry.status == "POSTED",
            GlJournalEntry.posting_date >= from_date,
            GlJournalEntry.posting_date <= to_date,
            GlJournalLine.account_id == account_id,
        )
    )
    if branch_id is not None:
        q = q.filter(GlJournalLine.branch_id == branch_id)
    row = q.first()
    if not row:
        return Decimal("0")
    deb, cred = Decimal(str(row[0] or 0)), Decimal(str(row[1] or 0))
    if normal_credit:
        return _q(cred - deb)
    return _q(deb - cred)


def _gl_posted_for(
    db: Session,
    *,
    company_id: UUID,
    source_type: str,
    source_id: UUID,
    posting_kind: str,
) -> bool:
    key = build_idempotency_key(source_type, source_id, posting_kind)
    return (
        db.query(GlJournalEntry.id)
        .filter(
            GlJournalEntry.company_id == company_id,
            GlJournalEntry.idempotency_key == key,
            GlJournalEntry.status == "POSTED",
        )
        .first()
        is not None
    )


def compute_gl_operational_status(
    *,
    gl_output: Decimal,
    gl_input: Decimal,
    operational_output_net: Decimal,
    operational_input: Decimal,
) -> str:
    """PASS | FAIL — internal books: GL control accounts vs operational documents."""
    out_delta = abs(gl_output - operational_output_net)
    in_delta = abs(gl_input - operational_input)
    if out_delta > RECON_TOLERANCE or in_delta > RECON_TOLERANCE:
        return "FAIL"
    return "PASS"


def compute_kra_submission_status(
    *,
    kra_enabled: bool,
    gl_operational_status: str,
    etims_submitted_output: Decimal,
    operational_sales_output: Decimal,
) -> str:
    """
    NOT_APPLICABLE — KRA off (no eTIMS authority reporting).
    PASS | WARN | FAIL — when KRA on; WARN if submitted VAT ≠ batched sales VAT.
    """
    if not kra_enabled:
        return "NOT_APPLICABLE"
    if gl_operational_status == "FAIL":
        return "FAIL"
    if abs(etims_submitted_output - operational_sales_output) > RECON_TOLERANCE:
        return "WARN"
    return "PASS"


def compute_overall_vat_status(gl_operational_status: str, kra_submission_status: str) -> str:
    if gl_operational_status == "FAIL" or kra_submission_status == "FAIL":
        return "FAIL"
    if kra_submission_status == "WARN":
        return "WARN"
    if kra_submission_status == "NOT_APPLICABLE":
        return gl_operational_status
    return "PASS"


def build_vat_reconciliation(
    db: Session,
    *,
    company_id: UUID,
    from_date: date,
    to_date: date,
    branch_id: Optional[UUID] = None,
) -> Dict[str, Any]:
    kra_enabled = company_kra_execution_enabled(db, company_id)
    base = {
        "company_id": str(company_id),
        "branch_id": str(branch_id) if branch_id else None,
        "from_date": str(from_date),
        "to_date": str(to_date),
        "doctrine": "gl_vat_reconciliation_m1",
        "kra_enabled": kra_enabled,
        "tolerance": str(RECON_TOLERANCE),
    }

    accounts = control_account_map(db, company_id)
    vat_out_acct = accounts.get(CONTROL_VAT_OUTPUT)
    vat_in_acct = accounts.get(CONTROL_VAT_INPUT)

    gl_output = Decimal("0")
    gl_input = Decimal("0")
    if vat_out_acct:
        gl_output = gl_vat_period_movement(
            db,
            company_id=company_id,
            account_id=vat_out_acct.id,
            normal_credit=True,
            from_date=from_date,
            to_date=to_date,
            branch_id=branch_id,
        )
    if vat_in_acct:
        gl_input = gl_vat_period_movement(
            db,
            company_id=company_id,
            account_id=vat_in_acct.id,
            normal_credit=False,
            from_date=from_date,
            to_date=to_date,
            branch_id=branch_id,
        )

    sales_q = db.query(SalesInvoice).filter(
        SalesInvoice.company_id == company_id,
        SalesInvoice.invoice_date >= from_date,
        SalesInvoice.invoice_date <= to_date,
        SalesInvoice.status.in_(_SALES_POSTED_STATUSES),
    )
    if branch_id is not None:
        sales_q = sales_q.filter(SalesInvoice.branch_id == branch_id)
    sales_rows = sales_q.all()

    cn_q = db.query(CreditNote).filter(
        CreditNote.company_id == company_id,
        CreditNote.credit_note_date >= from_date,
        CreditNote.credit_note_date <= to_date,
        CreditNote.posting_status == "posted",
    )
    if branch_id is not None:
        cn_q = cn_q.filter(CreditNote.branch_id == branch_id)
    credit_rows = cn_q.all()

    purch_q = db.query(SupplierInvoice).filter(
        SupplierInvoice.company_id == company_id,
        SupplierInvoice.invoice_date >= from_date,
        SupplierInvoice.invoice_date <= to_date,
        SupplierInvoice.status == "BATCHED",
    )
    if branch_id is not None:
        purch_q = purch_q.filter(SupplierInvoice.branch_id == branch_id)
    purchase_rows = purch_q.all()

    operational_sales_output = sum((_money(r.vat_amount) for r in sales_rows), Decimal("0"))
    operational_credit_output = sum((_money(r.vat_amount) for r in credit_rows), Decimal("0"))
    operational_output_net = _q(operational_sales_output - operational_credit_output)
    operational_input = sum((_money(r.vat_amount) for r in purchase_rows), Decimal("0"))

    etims_submitted_output = Decimal("0")
    if kra_enabled:
        etims_submitted_output = sum(
            (
                _money(r.vat_amount)
                for r in sales_rows
                if (getattr(r, "submission_status", None) or "").strip().lower() == "submitted"
            ),
            Decimal("0"),
        )

    differences: List[Dict[str, Any]] = []

    for inv in sales_rows:
        vat = _money(inv.vat_amount)
        if vat <= 0:
            continue
        if not _gl_posted_for(
            db,
            company_id=company_id,
            source_type="sales_invoice",
            source_id=inv.id,
            posting_kind=_KIND_SALE_REVENUE,
        ):
            differences.append(
                {
                    "document_type": "sales_invoice",
                    "document_id": str(inv.id),
                    "document_number": inv.invoice_no,
                    "vat_amount": str(vat),
                    "reason": "GL missing",
                }
            )
        if kra_enabled:
            sub = (getattr(inv, "submission_status", None) or "").strip().lower()
            if sub != "submitted":
                differences.append(
                    {
                        "document_type": "sales_invoice",
                        "document_id": str(inv.id),
                        "document_number": inv.invoice_no,
                        "vat_amount": str(vat),
                        "reason": "Not submitted to eTIMS",
                        "submission_status": sub or None,
                    }
                )

    for cn in credit_rows:
        vat = _money(cn.vat_amount)
        if vat <= 0:
            continue
        if not _gl_posted_for(
            db,
            company_id=company_id,
            source_type="credit_note",
            source_id=cn.id,
            posting_kind=_KIND_CREDIT_NOTE_REVENUE,
        ):
            differences.append(
                {
                    "document_type": "credit_note",
                    "document_id": str(cn.id),
                    "document_number": cn.credit_note_no,
                    "vat_amount": str(vat),
                    "reason": "GL missing",
                }
            )

    for inv in purchase_rows:
        vat = _money(inv.vat_amount)
        if vat <= 0:
            continue
        if not _gl_posted_for(
            db,
            company_id=company_id,
            source_type="supplier_invoice",
            source_id=inv.id,
            posting_kind=_KIND_SUPPLIER_INVOICE,
        ):
            differences.append(
                {
                    "document_type": "supplier_invoice",
                    "document_id": str(inv.id),
                    "document_number": inv.invoice_number,
                    "vat_amount": str(vat),
                    "reason": "GL missing",
                }
            )

    gl_operational_status = compute_gl_operational_status(
        gl_output=gl_output,
        gl_input=gl_input,
        operational_output_net=operational_output_net,
        operational_input=operational_input,
    )
    kra_submission_status = compute_kra_submission_status(
        kra_enabled=kra_enabled,
        gl_operational_status=gl_operational_status,
        etims_submitted_output=etims_submitted_output,
        operational_sales_output=operational_sales_output,
    )
    status = compute_overall_vat_status(gl_operational_status, kra_submission_status)

    message = None
    if not kra_enabled:
        message = (
            "KRA/eTIMS reporting not enabled — GL vs operational VAT computed; "
            "eTIMS submission checks skipped"
        )

    return {
        **base,
        "status": status,
        "gl_operational_status": gl_operational_status,
        "kra_submission_status": kra_submission_status,
        "message": message,
        "gl_vat_output": gl_output,
        "gl_vat_input": gl_input,
        "operational_vat_output_sales": operational_sales_output,
        "operational_vat_output_credit_notes": operational_credit_output,
        "operational_vat_output_net": operational_output_net,
        "operational_vat_input": operational_input,
        "etims_submitted_vat_output": etims_submitted_output if kra_enabled else None,
        "delta_output_gl_vs_operational": _q(gl_output - operational_output_net),
        "delta_input_gl_vs_operational": _q(gl_input - operational_input),
        "delta_etims_vs_operational_sales": (
            _q(etims_submitted_output - operational_sales_output) if kra_enabled else None
        ),
        "differences": differences,
        "difference_count": len(differences),
    }
