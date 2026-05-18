"""
Finance semantic doctrine API (E5.5 / E6) — introspection for architectural invariants.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_tenant_db
from app.finance.doctrine.backfill import BACKFILL_FORBIDDEN, BACKFILL_INVARIANTS
from app.finance.doctrine.causal_lineage import introspect_causal_lineage_doctrine
from app.finance.doctrine.correlation import introspect_correlation_governance
from app.finance.doctrine.economic_position import introspect_economic_position_doctrine
from app.finance.doctrine.event_evolution import introspect_event_evolution_doctrine
from app.finance.authority.doctrine import introspect_authority_doctrine
from app.finance.accounting.doctrine import introspect_accounting_doctrine
from app.finance.accounting.registry import list_supported_event_types
from app.finance.doctrine.orchestration_boundary import introspect_orchestration_boundary
from app.finance.doctrine.projection import PROJECTION_INVARIANTS
from app.finance.doctrine.projection_freshness import introspect_projection_freshness
from app.finance.doctrine.settlement import introspect_settlement_rules
from app.finance.doctrine.temporal import TEMPORAL_SEMANTICS
from app.finance.doctrine.treasury import introspect_treasury_doctrine
from app.finance.events.correlation import introspect_correlation_taxonomy
from app.finance.governance.access import guard_finance_report_access
from app.finance.governance.request_context import bind_fastapi_request
from app.finance.projections.registry import introspect_projection_registry
from app.models import User

router = APIRouter(prefix="/finance/doctrine", tags=["Finance Doctrine"])


def _company_id(request: Request, db: Session, user: User) -> UUID:
    cid = getattr(request.state, "effective_company_id", None)
    if cid is not None:
        return cid
    from app.dependencies import get_effective_company_id_for_user

    return get_effective_company_id_for_user(db, user)


@router.get("")
def get_finance_doctrine(
    request: Request,
    user_db=Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    bind_fastapi_request(request)
    user, _ = user_db
    company_id = _company_id(request, db, user)
    guard_finance_report_access(
        db, user, company_id, "finance.reports.audit_read", "branch_finance"
    )
    return {
        "phase": "E6.7/E7",
        "projection": {
            "invariants": sorted(PROJECTION_INVARIANTS),
            "registry": introspect_projection_registry(),
            "freshness": introspect_projection_freshness(),
        },
        "correlation": {
            "taxonomy": introspect_correlation_taxonomy(),
            "governance": introspect_correlation_governance(),
        },
        "settlement": introspect_settlement_rules(),
        "treasury": introspect_treasury_doctrine(),
        "temporal": TEMPORAL_SEMANTICS,
        "backfill": {
            "invariants": sorted(BACKFILL_INVARIANTS),
            "forbidden": sorted(BACKFILL_FORBIDDEN),
        },
        "economic_position": introspect_economic_position_doctrine(),
        "causal_lineage": introspect_causal_lineage_doctrine(),
        "event_evolution": introspect_event_evolution_doctrine(),
        "orchestration_boundary": introspect_orchestration_boundary(),
        "semantics_api": "/api/finance/semantics/exposure/{accrual_event_id}",
        "authority": introspect_authority_doctrine(),
        "accounting": introspect_accounting_doctrine(),
        "orchestration_boundary": introspect_orchestration_boundary(),
        "accounting_api": "/api/finance/accounting",
        "supported_proposal_event_types": list_supported_event_types(),
    }
