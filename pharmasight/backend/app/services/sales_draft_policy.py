"""
Sales draft policy — delegates to branch operational backlog (sales module).
"""
from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy.orm import Session

from app.services.branch_operational_backlog import (
    assert_module_not_blocked,
    fetch_branch_operational_backlog,
)


def assert_branch_may_create_new_sales_draft(
    db: Session,
    company_id: UUID,
    branch_id: UUID,
    business_date: date,
) -> None:
    assert_module_not_blocked(db, company_id, branch_id, business_date, "sales")


def branch_draft_policy_summary(
    db: Session,
    company_id: UUID,
    branch_id: UUID,
    business_date: date,
) -> dict:
    """Backward-compatible shape for GET /sales/.../draft-policy."""
    summary = fetch_branch_operational_backlog(db, company_id, branch_id, business_date)
    blocking = [d for d in summary["blocking_documents"] if d["document_type"] == "sales_invoice"]
    return {
        "may_create_new_draft": summary["may_create_new_sales_draft"],
        "blocking_draft_count": len(blocking),
        "blocking_invoices": [
            {
                "id": d["id"],
                "invoice_no": d["document_no"],
                "invoice_date": d["document_date"],
            }
            for d in blocking
        ],
        "blocked_modules": summary.get("blocked_modules", []),
        "blocking_count": summary.get("blocking_count", 0),
    }
