"""
Resolve finance policy pack from branch configuration (E5).
"""
from __future__ import annotations

from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.finance.events.policies import (
    HOSPITAL_INSURANCE,
    RETAIL_SIMPLE,
    WHOLESALE_AR,
    FinancialEventPolicyPack,
    resolve_policy_pack,
)
from app.models.company import Branch
from app.services.invoice_workflow_policy import (
    ENCOUNTER_CONSOLIDATED,
    RETAIL_COUNTER,
    WHOLESALE_DISTRIBUTION,
)


def _pack_id_for_invoice_workflow(workflow: str | None) -> str | None:
    """Align finance_policy_pack with branch fiscal doctrine (admin authoritative)."""
    wf = (workflow or "").strip().upper()
    if wf == RETAIL_COUNTER:
        return RETAIL_SIMPLE.pack_id
    if wf == WHOLESALE_DISTRIBUTION:
        return WHOLESALE_AR.pack_id
    if wf == ENCOUNTER_CONSOLIDATED:
        return HOSPITAL_INSURANCE.pack_id
    return None


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
    workflow = branch.invoice_workflow_type if branch else None
    doctrine_pack = _pack_id_for_invoice_workflow(workflow)
    explicit = branch.finance_policy_pack if branch else None
    # Prefer doctrine-aligned pack when DB override disagrees with invoice_workflow_type.
    pack_id = doctrine_pack or explicit
    if doctrine_pack and explicit and explicit != doctrine_pack:
        pack_id = doctrine_pack

    wf_upper = (workflow or "").strip().upper()
    branch_workflow = None
    if wf_upper in (ENCOUNTER_CONSOLIDATED, "ENCOUNTER", "HOSPITAL", "HOSPITAL_ENCOUNTER"):
        branch_workflow = "HOSPITAL"
    return resolve_policy_pack(
        explicit_pack_id=pack_id,
        sales_type=sales_type,
        branch_workflow=branch_workflow,
    )
