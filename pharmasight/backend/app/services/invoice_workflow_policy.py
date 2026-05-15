"""
Branch-scoped invoice workflow / fiscal doctrine (policy foundation).

invoice_workflow_type on Branch defines fiscal authority and future enforcement anchors.
It does NOT define patient entry pathway (retail vs encounter).

See: database/migrations/124_branch_invoice_workflow_type.sql
"""
from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.company import Branch

if TYPE_CHECKING:
    from app.models.sale import SalesInvoice

RETAIL_COUNTER = "RETAIL_COUNTER"
ENCOUNTER_CONSOLIDATED = "ENCOUNTER_CONSOLIDATED"

_ALLOWED = frozenset({RETAIL_COUNTER, ENCOUNTER_CONSOLIDATED})


def normalize_invoice_workflow_type(value: object | None) -> str:
    """Return a safe workflow token; unknown values fall back to RETAIL_COUNTER."""
    raw = (value if value is not None else RETAIL_COUNTER)
    v = str(raw).strip().upper()
    return v if v in _ALLOWED else RETAIL_COUNTER


def get_invoice_workflow_type(branch: Branch | None) -> str:
    """
    Resolve fiscal doctrine for a loaded Branch row.
    Use after migration; pre-migration DBs without the column are handled via getattr.
    """
    if branch is None:
        return RETAIL_COUNTER
    raw = getattr(branch, "invoice_workflow_type", None)
    return normalize_invoice_workflow_type(raw)


def get_invoice_workflow_type_for_branch(db: Session, branch_id: UUID) -> str:
    """Load branch by id and return normalized invoice_workflow_type."""
    row = db.query(Branch).filter(Branch.id == branch_id).first()
    return get_invoice_workflow_type(row)


def is_encounter_consolidated_branch(db: Session, branch_id: UUID) -> bool:
    return get_invoice_workflow_type_for_branch(db, branch_id) == ENCOUNTER_CONSOLIDATED


def note_invoice_finalization_policy(
    db: Session,
    invoice: "SalesInvoice",
    *,
    context: str,
) -> str:
    """
    Extension point: invoice batch / stock commit / status finalization (sales path).

    RETAIL_COUNTER: pharmacy-first path remains authoritative (no change).

    ENCOUNTER_CONSOLIDATED: fiscal finalization authority will move under billing-office
    orchestration. Stock commit timing (batch vs dispense) will be policy-driven later.

    context: logical call site name for future logging (e.g. "batch_sales_invoice").
    """
    wf = get_invoice_workflow_type_for_branch(db, invoice.branch_id)
    if wf == ENCOUNTER_CONSOLIDATED:
        # TODO(ENCOUNTER_CONSOLIDATED): Block pharmacy-only batch as sole fiscal finalizer when
        # billing merge + clearance workflow is implemented; route batch authority per doctrine.
        # TODO(ENCOUNTER_CONSOLIDATED): Respect stock_commit_timing (AT_BATCH vs AT_DISPENSE) here.
        # TODO(ENCOUNTER_CONSOLIDATED): Do not assume reception-only; support departmental initiators.
        _ = context  # reserved for structured logging
    return wf


def note_fiscal_pdf_and_print_policy(
    db: Session,
    invoice: "SalesInvoice",
    *,
    context: str,
) -> str:
    """
    Extension point: fiscal PDF / print paths that may trigger or require KRA data.

    ENCOUNTER_CONSOLIDATED: future — require fiscal_cleared (or equivalent) before treating
    pharmacy print as authoritative fiscal output.
    """
    wf = get_invoice_workflow_type_for_branch(db, invoice.branch_id)
    if wf == ENCOUNTER_CONSOLIDATED:
        # TODO(ENCOUNTER_CONSOLIDATED): Gate fiscal PDF on billing-office fiscal clearance, not pharmacy alone.
        # TODO(ENCOUNTER_CONSOLIDATED): Align with cashier approval step before fiscal-sign PDF.
        _ = context
    return wf


def note_kra_submission_workflow_anchor(db: Session, invoice: "SalesInvoice") -> str:
    """
    Extension point: synchronous submit, outbox worker, and PDF-triggered submit.

    ENCOUNTER_CONSOLIDATED: KRA submission must eventually occur only after billing consolidation,
    cashier clearance, and explicit fiscal clearance — not on pharmacy narrative alone.
    """
    wf = get_invoice_workflow_type_for_branch(db, invoice.branch_id)
    if wf == ENCOUNTER_CONSOLIDATED:
        # TODO(ENCOUNTER_CONSOLIDATED): assert fiscal_cleared (or billing_fiscal_clearance) before OSCU submit.
        # TODO(ENCOUNTER_CONSOLIDATED): Reject submit_sales_invoice from pharmacy-only contexts when appropriate.
        # TODO(ENCOUNTER_CONSOLIDATED): Ensure outbox worker respects same clearance as HTTP submit path.
        pass
    return wf
