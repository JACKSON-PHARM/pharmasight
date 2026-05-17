"""
Branch-scoped invoice workflow / fiscal doctrine (policy foundation).

invoice_workflow_type on Branch defines fiscal authority and future enforcement anchors.
It does NOT define patient entry pathway (retail vs encounter).

See: database/migrations/124_branch_invoice_workflow_type.sql
database/migrations/132_branch_wholesale_doctrine.sql
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.company import Branch

if TYPE_CHECKING:
    from app.models.sale import SalesInvoice

RETAIL_COUNTER = "RETAIL_COUNTER"
ENCOUNTER_CONSOLIDATED = "ENCOUNTER_CONSOLIDATED"
WHOLESALE_DISTRIBUTION = "WHOLESALE_DISTRIBUTION"

_ALLOWED = frozenset({RETAIL_COUNTER, ENCOUNTER_CONSOLIDATED, WHOLESALE_DISTRIBUTION})


def normalize_invoice_workflow_type(value: object | None) -> str:
    """Return a safe workflow token; unknown values fall back to RETAIL_COUNTER."""
    raw = value if value is not None else RETAIL_COUNTER
    v = str(raw).strip().upper()
    return v if v in _ALLOWED else RETAIL_COUNTER


def doctrine_label(workflow_type: str) -> str:
    wf = normalize_invoice_workflow_type(workflow_type)
    if wf == ENCOUNTER_CONSOLIDATED:
        return "Encounter consolidated"
    if wf == WHOLESALE_DISTRIBUTION:
        return "Wholesale distribution"
    return "Retail counter"


def get_invoice_workflow_type(branch: Branch | None) -> str:
    if branch is None:
        return RETAIL_COUNTER
    raw = getattr(branch, "invoice_workflow_type", None)
    return normalize_invoice_workflow_type(raw)


def get_invoice_workflow_type_for_branch(db: Session, branch_id: UUID) -> str:
    row = db.query(Branch).filter(Branch.id == branch_id).first()
    return get_invoice_workflow_type(row)


def is_encounter_consolidated_branch(db: Session, branch_id: UUID) -> bool:
    return get_invoice_workflow_type_for_branch(db, branch_id) == ENCOUNTER_CONSOLIDATED


def is_wholesale_distribution_branch(db: Session, branch_id: UUID) -> bool:
    return get_invoice_workflow_type_for_branch(db, branch_id) == WHOLESALE_DISTRIBUTION


def is_wholesale_distribution(branch: Branch | None) -> bool:
    return get_invoice_workflow_type(branch) == WHOLESALE_DISTRIBUTION


def default_sales_type_for_branch(db: Session, branch_id: UUID) -> str:
    """Default pricing tier for new sales on this branch."""
    if is_wholesale_distribution_branch(db, branch_id):
        return "WHOLESALE"
    return "RETAIL"


def note_invoice_finalization_policy(
    db: Session,
    invoice: "SalesInvoice",
    *,
    context: str,
) -> str:
    wf = get_invoice_workflow_type_for_branch(db, invoice.branch_id)
    if wf == ENCOUNTER_CONSOLIDATED:
        _ = context
    return wf


def note_fiscal_pdf_and_print_policy(
    db: Session,
    invoice: "SalesInvoice",
    *,
    context: str,
) -> str:
    wf = get_invoice_workflow_type_for_branch(db, invoice.branch_id)
    if wf == ENCOUNTER_CONSOLIDATED:
        _ = context
    return wf


def note_kra_submission_workflow_anchor(db: Session, invoice: "SalesInvoice") -> str:
    wf = get_invoice_workflow_type_for_branch(db, invoice.branch_id)
    if wf == ENCOUNTER_CONSOLIDATED:
        pass
    return wf


def assert_wholesale_branch_for_customer_sale(
    db: Session,
    branch_id: UUID,
    *,
    customer_id: Optional[UUID],
) -> None:
    """B2B customer master links require a wholesale-distribution branch."""
    if not customer_id:
        return
    if not is_wholesale_distribution_branch(db, branch_id):
        from fastapi import HTTPException

        raise HTTPException(
            status_code=400,
            detail=(
                "Linked B2B customers are only allowed on branches with "
                "Wholesale distribution doctrine."
            ),
        )
