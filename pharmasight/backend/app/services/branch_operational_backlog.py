"""
Branch operational backlog: prior-date unposted documents that affect (or inform) stock workflows.

Blocking types prevent new documents in the matching module until resolved.
Non-blocking types are listed for visibility only (orders, quotations).
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import cast, Date as SaDate, func
from sqlalchemy.orm import Session

from app.models import (
    BranchTransfer,
    CreditNote,
    DepartmentSupplyTransfer,
    PurchaseOrder,
    Quotation,
    SalesInvoice,
    SupplierInvoice,
    SupplierReturn,
)
from app.models.branch_inventory import BranchOrder
from app.models.department_supply import DepartmentSupplyOrder

# document_type -> blocks_module (None = informational only)
_BLOCKING_RULES: Dict[str, Dict[str, Any]] = {
    "sales_invoice": {
        "blocks_module": "sales",
        "label": "Sales invoice",
        "is_blocking": True,
    },
    "supplier_invoice": {
        "blocks_module": "purchases",
        "label": "Supplier invoice",
        "is_blocking": True,
    },
    "branch_transfer": {
        "blocks_module": "branch_transfer",
        "label": "Branch transfer",
        "is_blocking": True,
    },
    "department_supply_transfer": {
        "blocks_module": "department_supply",
        "label": "Department transfer",
        "is_blocking": True,
    },
    "credit_note": {
        "blocks_module": "sales_returns",
        "label": "Credit note (return)",
        "is_blocking": True,
    },
    "supplier_return": {
        "blocks_module": "purchases_returns",
        "label": "Supplier return",
        "is_blocking": True,
    },
    "branch_order": {
        "blocks_module": None,
        "label": "Branch order",
        "is_blocking": False,
    },
    "department_supply_order": {
        "blocks_module": None,
        "label": "Department order",
        "is_blocking": False,
    },
    "purchase_order": {
        "blocks_module": None,
        "label": "Purchase order",
        "is_blocking": False,
    },
    "quotation": {
        "blocks_module": None,
        "label": "Quotation",
        "is_blocking": False,
    },
}


def _row(
    document_type: str,
    doc_id: UUID,
    document_no: str,
    document_date: date,
    status: str,
    *,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    meta = _BLOCKING_RULES[document_type]
    out = {
        "document_type": document_type,
        "id": str(doc_id),
        "document_no": document_no or str(doc_id),
        "document_date": document_date.isoformat() if document_date else None,
        "status": status,
        "label": meta["label"],
        "blocks_module": meta["blocks_module"],
        "is_blocking": bool(meta["is_blocking"]),
    }
    if extra:
        out.update(extra)
    return out


def _created_date_column(model):
    return cast(func.date(model.created_at), SaDate)


def fetch_branch_operational_backlog(
    db: Session,
    company_id: UUID,
    branch_id: UUID,
    business_date: date,
    *,
    per_type_limit: int = 30,
) -> Dict[str, Any]:
    """All prior-date open operational documents for a branch."""
    blocking: List[Dict[str, Any]] = []
    informational: List[Dict[str, Any]] = []

    def add_rows(rows: List[Dict[str, Any]]) -> None:
        for r in rows:
            if r["is_blocking"]:
                blocking.append(r)
            else:
                informational.append(r)

    # --- Blocking: stock-affecting drafts / unposted ---

    sales = (
        db.query(SalesInvoice)
        .filter(
            SalesInvoice.company_id == company_id,
            SalesInvoice.branch_id == branch_id,
            SalesInvoice.status == "DRAFT",
            SalesInvoice.invoice_date < business_date,
        )
        .order_by(SalesInvoice.invoice_date.asc(), SalesInvoice.invoice_no.asc())
        .limit(per_type_limit)
        .all()
    )
    add_rows([
        _row("sales_invoice", inv.id, inv.invoice_no, inv.invoice_date, inv.status or "DRAFT")
        for inv in sales
    ])

    supplier_inv = (
        db.query(SupplierInvoice)
        .filter(
            SupplierInvoice.company_id == company_id,
            SupplierInvoice.branch_id == branch_id,
            SupplierInvoice.status == "DRAFT",
            SupplierInvoice.invoice_date < business_date,
        )
        .order_by(SupplierInvoice.invoice_date.asc(), SupplierInvoice.invoice_number.asc())
        .limit(per_type_limit)
        .all()
    )
    add_rows([
        _row(
            "supplier_invoice",
            inv.id,
            inv.invoice_number,
            inv.invoice_date,
            inv.status or "DRAFT",
        )
        for inv in supplier_inv
    ])

    branch_xfer = (
        db.query(BranchTransfer)
        .filter(
            BranchTransfer.company_id == company_id,
            BranchTransfer.status == "DRAFT",
            BranchTransfer.supplying_branch_id == branch_id,
            _created_date_column(BranchTransfer) < business_date,
        )
        .order_by(BranchTransfer.created_at.asc())
        .limit(per_type_limit)
        .all()
    )
    add_rows([
        _row(
            "branch_transfer",
            t.id,
            t.transfer_number or "",
            (t.created_at.date() if t.created_at else business_date),
            t.status,
            extra={"supplying_branch_id": str(t.supplying_branch_id), "receiving_branch_id": str(t.receiving_branch_id)},
        )
        for t in branch_xfer
    ])

    dept_xfer = (
        db.query(DepartmentSupplyTransfer)
        .filter(
            DepartmentSupplyTransfer.company_id == company_id,
            DepartmentSupplyTransfer.branch_id == branch_id,
            DepartmentSupplyTransfer.status == "DRAFT",
            _created_date_column(DepartmentSupplyTransfer) < business_date,
        )
        .order_by(DepartmentSupplyTransfer.created_at.asc())
        .limit(per_type_limit)
        .all()
    )
    add_rows([
        _row(
            "department_supply_transfer",
            t.id,
            t.transfer_number or "",
            (t.created_at.date() if t.created_at else business_date),
            t.status,
        )
        for t in dept_xfer
    ])

    credit_notes = (
        db.query(CreditNote)
        .filter(
            CreditNote.company_id == company_id,
            CreditNote.branch_id == branch_id,
            CreditNote.posting_status != "posted",
            CreditNote.credit_note_date < business_date,
        )
        .order_by(CreditNote.credit_note_date.asc(), CreditNote.credit_note_no.asc())
        .limit(per_type_limit)
        .all()
    )
    add_rows([
        _row(
            "credit_note",
            cn.id,
            cn.credit_note_no,
            cn.credit_note_date,
            cn.posting_status or "pending",
        )
        for cn in credit_notes
    ])

    supplier_returns = (
        db.query(SupplierReturn)
        .filter(
            SupplierReturn.company_id == company_id,
            SupplierReturn.branch_id == branch_id,
            SupplierReturn.posting_status != "posted",
            SupplierReturn.return_date < business_date,
        )
        .order_by(SupplierReturn.return_date.asc(), SupplierReturn.return_document_no.asc())
        .limit(per_type_limit)
        .all()
    )
    add_rows([
        _row(
            "supplier_return",
            r.id,
            r.return_document_no or "",
            r.return_date,
            r.posting_status or r.status or "pending",
        )
        for r in supplier_returns
    ])

    # --- Informational: no stock block ---

    branch_orders = (
        db.query(BranchOrder)
        .filter(
            BranchOrder.company_id == company_id,
            BranchOrder.ordering_branch_id == branch_id,
            BranchOrder.status == "DRAFT",
            _created_date_column(BranchOrder) < business_date,
        )
        .order_by(BranchOrder.created_at.asc())
        .limit(per_type_limit)
        .all()
    )
    add_rows([
        _row(
            "branch_order",
            o.id,
            o.order_number or "",
            (o.created_at.date() if o.created_at else business_date),
            o.status,
        )
        for o in branch_orders
    ])

    dept_orders = (
        db.query(DepartmentSupplyOrder)
        .filter(
            DepartmentSupplyOrder.company_id == company_id,
            DepartmentSupplyOrder.branch_id == branch_id,
            DepartmentSupplyOrder.status == "DRAFT",
            _created_date_column(DepartmentSupplyOrder) < business_date,
        )
        .order_by(DepartmentSupplyOrder.created_at.asc())
        .limit(per_type_limit)
        .all()
    )
    add_rows([
        _row(
            "department_supply_order",
            o.id,
            o.order_number or "",
            (o.created_at.date() if o.created_at else business_date),
            o.status,
        )
        for o in dept_orders
    ])

    purchase_orders = (
        db.query(PurchaseOrder)
        .filter(
            PurchaseOrder.company_id == company_id,
            PurchaseOrder.branch_id == branch_id,
            PurchaseOrder.status.in_(("PENDING", "APPROVED")),
            PurchaseOrder.order_date < business_date,
        )
        .order_by(PurchaseOrder.order_date.asc(), PurchaseOrder.order_number.asc())
        .limit(per_type_limit)
        .all()
    )
    add_rows([
        _row("purchase_order", po.id, po.order_number, po.order_date, po.status or "PENDING")
        for po in purchase_orders
    ])

    quotations = (
        db.query(Quotation)
        .filter(
            Quotation.company_id == company_id,
            Quotation.branch_id == branch_id,
            Quotation.status == "draft",
            Quotation.quotation_date < business_date,
        )
        .order_by(Quotation.quotation_date.asc(), Quotation.quotation_no.asc())
        .limit(per_type_limit)
        .all()
    )
    add_rows([
        _row("quotation", q.id, q.quotation_no, q.quotation_date, q.status or "draft")
        for q in quotations
    ])

    blocked_modules = sorted(
        {r["blocks_module"] for r in blocking if r.get("blocks_module")}
    )
    return {
        "business_date": business_date.isoformat(),
        "blocking_count": len(blocking),
        "informational_count": len(informational),
        "blocking_documents": blocking,
        "informational_documents": informational,
        "blocked_modules": blocked_modules,
        "may_create_new_sales_draft": "sales" not in blocked_modules,
        "may_create_new_supplier_invoice": "purchases" not in blocked_modules,
        "may_create_new_branch_transfer": "branch_transfer" not in blocked_modules,
        "may_create_new_department_transfer": "department_supply" not in blocked_modules,
    }


def assert_module_not_blocked(
    db: Session,
    company_id: UUID,
    branch_id: UUID,
    business_date: date,
    module: str,
) -> None:
    """Raise HTTP 409 if module is blocked by prior-date unposted documents."""
    from fastapi import HTTPException

    summary = fetch_branch_operational_backlog(db, company_id, branch_id, business_date)
    if module not in summary.get("blocked_modules", []):
        return
    docs = [
        d for d in summary["blocking_documents"]
        if d.get("blocks_module") == module
    ]
    refs = ", ".join(d["document_no"] for d in docs[:5])
    extra = len(docs) - 5
    suffix = f" (+{extra} more)" if extra > 0 else ""
    module_labels = {
        "sales": "new sales",
        "purchases": "new supplier invoices",
        "branch_transfer": "new branch transfers",
        "department_supply": "new department transfers",
        "sales_returns": "new returns / credit notes",
        "purchases_returns": "new supplier returns",
    }
    action = module_labels.get(module, f"new {module} documents")
    raise HTTPException(
        status_code=409,
        detail=(
            f"Cannot {action}: unposted document(s) from earlier dates remain ({refs}{suffix}). "
            "Open the notification bell to review, then batch, delete, or update them."
        ),
    )
