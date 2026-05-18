"""
Resolve finance policy pack from branch configuration (E5).
"""
from __future__ import annotations

from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.finance.events.policies import FinancialEventPolicyPack, resolve_policy_pack
from app.models.company import Branch


def resolve_policy_pack_for_branch(
    db: Session,
    *,
    company_id: UUID,
    branch_id: UUID,
    sales_type: str | None = None,
) -> FinancialEventPolicyPack:
    branch = (
        db.query(Branch)
        .filter(Branch.id == branch_id, Branch.company_id == company_id)
        .first()
    )
    explicit = branch.finance_policy_pack if branch else None
    workflow = branch.invoice_workflow_type if branch else None
    wf_upper = (workflow or "").upper()
    branch_workflow = None
    if wf_upper in ("ENCOUNTER", "HOSPITAL", "HOSPITAL_ENCOUNTER"):
        branch_workflow = "HOSPITAL"
    return resolve_policy_pack(
        explicit_pack_id=explicit,
        sales_type=sales_type,
        branch_workflow=branch_workflow,
    )
