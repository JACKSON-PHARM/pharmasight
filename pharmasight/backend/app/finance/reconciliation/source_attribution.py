"""
Resolve operational attribution for cashbook / lineage drift items (Stage 2A.5).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Set
from uuid import UUID

from sqlalchemy.orm import Session

from app.finance.reconciliation.lineage_coverage import get_expectation_for_cashbook_source
from app.models import CashbookEntry
from app.models.customer_financial import CustomerPayment
from app.models.expense import Expense
from app.models.insurance_financial import InsuranceSettlement
from app.models.sale import SalesInvoice
from app.models.supplier_financial import SupplierPayment


def _fmt_date(d) -> Optional[str]:
    if d is None:
        return None
    if isinstance(d, datetime):
        return str(d.date())
    if isinstance(d, date):
        return str(d)
    return str(d)


def batch_resolve_attributions(
    db: Session,
    *,
    company_id: UUID,
    entries: List[CashbookEntry],
) -> Dict[str, Dict[str, Any]]:
    """
    Key: "{source_type}:{source_id}" → attribution dict.
    """
    by_type: Dict[str, Set[UUID]] = defaultdict(set)
    for e in entries:
        by_type[e.source_type].add(e.source_id)

    out: Dict[str, Dict[str, Any]] = {}

    def put(key: str, **fields):
        exp = get_expectation_for_cashbook_source(key.split(":")[0])
        out[key] = {
            "operational_module": exp.operational_module if exp else "Unknown",
            "workflow_label": exp.workflow_label if exp else key.split(":")[0],
            "workflow_id": exp.workflow_id if exp else None,
            "lineage_expected": bool(exp and exp.lineage_mandatory),
            "expected_event_types": list(exp.expected_event_types) if exp else [],
            "record_exists": fields.get("record_exists", False),
            "document_reference": fields.get("document_reference"),
            "operational_date": fields.get("operational_date"),
            "operational_status": fields.get("operational_status"),
            "source_entity_type": exp.source_entity_type if exp else None,
        }

    if by_type.get("expense"):
        ids = list(by_type["expense"])
        rows = (
            db.query(Expense)
            .filter(Expense.company_id == company_id, Expense.id.in_(ids))
            .all()
        )
        found = {r.id: r for r in rows}
        for sid in ids:
            r = found.get(sid)
            put(
                f"expense:{sid}",
                record_exists=r is not None,
                document_reference=(f"Expense {r.id}"[:80] if r else None),
                operational_date=_fmt_date(r.expense_date if r else None),
                operational_status=getattr(r, "status", None) if r else None,
            )

    if by_type.get("supplier_payment"):
        ids = list(by_type["supplier_payment"])
        rows = (
            db.query(SupplierPayment)
            .filter(SupplierPayment.company_id == company_id, SupplierPayment.id.in_(ids))
            .all()
        )
        found = {r.id: r for r in rows}
        for sid in ids:
            r = found.get(sid)
            ref = None
            if r:
                ref = getattr(r, "reference", None) or getattr(r, "payment_reference", None)
                ref = ref or f"Supplier payment {str(sid)[:8]}"
            put(
                f"supplier_payment:{sid}",
                record_exists=r is not None,
                document_reference=ref,
                operational_date=_fmt_date(getattr(r, "payment_date", None) if r else None),
                operational_status=None,
            )

    if by_type.get("sale"):
        ids = list(by_type["sale"])
        rows = (
            db.query(SalesInvoice)
            .filter(SalesInvoice.company_id == company_id, SalesInvoice.id.in_(ids))
            .all()
        )
        found = {r.id: r for r in rows}
        for sid in ids:
            r = found.get(sid)
            put(
                f"sale:{sid}",
                record_exists=r is not None,
                document_reference=r.invoice_no if r else None,
                operational_date=_fmt_date(r.invoice_date if r else None),
                operational_status=r.status if r else None,
            )

    if by_type.get("customer_payment"):
        ids = list(by_type["customer_payment"])
        rows = (
            db.query(CustomerPayment)
            .filter(CustomerPayment.company_id == company_id, CustomerPayment.id.in_(ids))
            .all()
        )
        found = {r.id: r for r in rows}
        for sid in ids:
            r = found.get(sid)
            put(
                f"customer_payment:{sid}",
                record_exists=r is not None,
                document_reference=getattr(r, "reference", None) if r else None,
                operational_date=_fmt_date(getattr(r, "payment_date", None) if r else None),
                operational_status=None,
            )

    if by_type.get("insurance_settlement"):
        ids = list(by_type["insurance_settlement"])
        rows = (
            db.query(InsuranceSettlement)
            .filter(InsuranceSettlement.company_id == company_id, InsuranceSettlement.id.in_(ids))
            .all()
        )
        found = {r.id: r for r in rows}
        for sid in ids:
            r = found.get(sid)
            put(
                f"insurance_settlement:{sid}",
                record_exists=r is not None,
                document_reference=getattr(r, "settlement_number", None) if r else None,
                operational_date=_fmt_date(getattr(r, "settlement_date", None) if r else None),
                operational_status=None,
            )

    # Fill unknown source types
    for e in entries:
        key = f"{e.source_type}:{e.source_id}"
        if key not in out:
            put(
                key,
                record_exists=False,
                document_reference=e.reference_number or e.description,
                operational_date=str(e.date),
            )

    return out


def attribution_for_entry(entry: CashbookEntry, cache: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    key = f"{entry.source_type}:{entry.source_id}"
    base = dict(cache.get(key) or {})
    base.setdefault("cashbook_reference", entry.reference_number)
    base.setdefault("cashbook_description", entry.description)
    return base
