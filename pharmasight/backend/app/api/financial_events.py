"""
Financial events API — read-only lineage + E4 replay/integrity (governed).
"""
from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_tenant_db
from app.finance.events.lineage import build_enriched_lineage
from app.finance.events.correlation import introspect_correlation_taxonomy
from app.finance.events.policies import introspect_policy_packs
from app.finance.events.registry import introspect_event_registry
from app.finance.events.replay import replay_emission_failure, replay_unresolved_failures
from app.finance.events.integrity import verify_company_lineage
from app.finance.governance.access import guard_finance_report_access
from app.finance.governance.classification import BRANCH_FINANCE, MANAGEMENT
from app.finance.governance.request_context import bind_fastapi_request
from app.models import User
from app.models.financial_event import FinancialEvent, FinancialEventEmissionFailure
from app.schemas.financial_events import (
    EmissionFailureResponse,
    FinancialEventLineageResponse,
    FinancialEventResponse,
    IntegrityFindingResponse,
    ReplayLogResponse,
    ReplayOutcomeResponse,
    SettlementLinkResponse,
)

router = APIRouter(prefix="/finance/events", tags=["Financial Events"])


def _company_id(request: Request, db: Session, user: User) -> UUID:
    cid = getattr(request.state, "effective_company_id", None)
    if cid is not None:
        return cid
    from app.dependencies import get_effective_company_id_for_user

    cid = get_effective_company_id_for_user(db, user)
    if cid is None:
        raise HTTPException(status_code=400, detail="Company context not available")
    return cid


def _to_lineage_response(data: dict) -> FinancialEventLineageResponse:
    links = data.get("settlement_links") or {}
    return FinancialEventLineageResponse(
        event=FinancialEventResponse.model_validate(data["event"]),
        reversals=[FinancialEventResponse.model_validate(r) for r in data["reversals"]],
        caused_by=FinancialEventResponse.model_validate(data["caused_by"]) if data.get("caused_by") else None,
        settles=[FinancialEventResponse.model_validate(s) for s in data.get("settles", [])],
        settlement_links={
            "as_settlement": [SettlementLinkResponse.model_validate(x) for x in links.get("settles", [])],
            "settled_by": [SettlementLinkResponse.model_validate(x) for x in links.get("settled_by", [])],
        },
        replay_logs=[ReplayLogResponse.model_validate(r) for r in data.get("replay_logs", [])],
        correlation_events=[
            FinancialEventResponse.model_validate(c) for c in data.get("correlation_events", [])
        ],
    )


@router.get("/registry")
def get_event_registry(
    request: Request,
    user_db=Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    bind_fastapi_request(request)
    user, _ = user_db
    company_id = _company_id(request, db, user)
    guard_finance_report_access(db, user, company_id, "finance.reports.audit_read", BRANCH_FINANCE)
    return {
        "events": introspect_event_registry(),
        "policy_packs": introspect_policy_packs(),
        "correlation_taxonomy": introspect_correlation_taxonomy(),
    }


@router.get("/integrity", response_model=List[IntegrityFindingResponse])
def get_lineage_integrity(
    request: Request,
    branch_id: Optional[UUID] = Query(None),
    since: Optional[date] = Query(None),
    user_db=Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    bind_fastapi_request(request)
    user, _ = user_db
    company_id = _company_id(request, db, user)
    guard_finance_report_access(
        db, user, company_id, "finance.reports.audit_read", BRANCH_FINANCE, branch_id=branch_id
    )
    findings = verify_company_lineage(db, company_id=company_id, branch_id=branch_id, since=since)
    return [IntegrityFindingResponse.model_validate(f.__dict__) for f in findings]


@router.get("/failures", response_model=List[EmissionFailureResponse])
def list_emission_failures(
    request: Request,
    unresolved_only: bool = Query(True),
    limit: int = Query(100, ge=1, le=500),
    user_db=Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    bind_fastapi_request(request)
    user, _ = user_db
    company_id = _company_id(request, db, user)
    guard_finance_report_access(db, user, company_id, "finance.reports.audit_read", BRANCH_FINANCE)
    q = db.query(FinancialEventEmissionFailure).filter(
        FinancialEventEmissionFailure.company_id == company_id
    )
    if unresolved_only:
        q = q.filter(FinancialEventEmissionFailure.resolved_at.is_(None))
    rows = q.order_by(FinancialEventEmissionFailure.created_at.desc()).limit(limit).all()
    return [EmissionFailureResponse.model_validate(r) for r in rows]


@router.post("/failures/{failure_id}/replay", response_model=ReplayOutcomeResponse)
def replay_failure(
    failure_id: UUID,
    request: Request,
    user_db=Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    bind_fastapi_request(request)
    user, _ = user_db
    company_id = _company_id(request, db, user)
    guard_finance_report_access(db, user, company_id, "finance.reports.audit_read", BRANCH_FINANCE)
    outcome = replay_emission_failure(db, failure_id, company_id=company_id, actor_user_id=user.id)
    return ReplayOutcomeResponse(
        failure_id=outcome.failure_id,
        result=outcome.result.value,
        financial_event_id=outcome.financial_event_id,
        message=outcome.message,
    )


@router.post("/failures/replay-unresolved", response_model=List[ReplayOutcomeResponse])
def replay_all_unresolved(
    request: Request,
    limit: int = Query(100, ge=1, le=500),
    user_db=Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    bind_fastapi_request(request)
    user, _ = user_db
    company_id = _company_id(request, db, user)
    guard_finance_report_access(db, user, company_id, "finance.reports.audit_read", BRANCH_FINANCE)
    outcomes = replay_unresolved_failures(db, company_id=company_id, actor_user_id=user.id, limit=limit)
    return [
        ReplayOutcomeResponse(
            failure_id=o.failure_id,
            result=o.result.value,
            financial_event_id=o.financial_event_id,
            message=o.message,
        )
        for o in outcomes
    ]


@router.get("", response_model=List[FinancialEventResponse])
def list_financial_events(
    request: Request,
    branch_id: Optional[UUID] = Query(None),
    event_type: Optional[str] = Query(None),
    source_entity_type: Optional[str] = Query(None),
    source_entity_id: Optional[UUID] = Query(None),
    correlation_group: Optional[str] = Query(None),
    occurred_from: Optional[date] = Query(None),
    occurred_to: Optional[date] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user_db=Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    bind_fastapi_request(request)
    user, _ = user_db
    company_id = _company_id(request, db, user)
    report_ctx = guard_finance_report_access(
        db,
        user,
        company_id,
        "finance.reports.management",
        MANAGEMENT,
        branch_id=branch_id,
    )
    q = db.query(FinancialEvent).filter(FinancialEvent.company_id == company_id)
    q = report_ctx.apply_branch_filter(q, FinancialEvent.branch_id, branch_id)
    if event_type:
        q = q.filter(FinancialEvent.event_type == event_type)
    if source_entity_type:
        q = q.filter(FinancialEvent.source_entity_type == source_entity_type)
    if source_entity_id:
        q = q.filter(FinancialEvent.source_entity_id == source_entity_id)
    if correlation_group:
        q = q.filter(FinancialEvent.correlation_group == correlation_group)
    if occurred_from:
        q = q.filter(FinancialEvent.occurred_at >= datetime.combine(occurred_from, datetime.min.time()))
    if occurred_to:
        q = q.filter(FinancialEvent.occurred_at <= datetime.combine(occurred_to, datetime.max.time()))
    rows = q.order_by(FinancialEvent.occurred_at.desc()).offset(offset).limit(limit).all()
    return [FinancialEventResponse.model_validate(r) for r in rows]


@router.get("/{event_id}", response_model=FinancialEventLineageResponse)
def get_financial_event_lineage(
    event_id: UUID,
    request: Request,
    user_db=Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    bind_fastapi_request(request)
    user, _ = user_db
    company_id = _company_id(request, db, user)
    row = (
        db.query(FinancialEvent)
        .filter(FinancialEvent.id == event_id, FinancialEvent.company_id == company_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Event not found")
    guard_finance_report_access(
        db,
        user,
        company_id,
        "finance.reports.management",
        MANAGEMENT,
        branch_id=row.branch_id,
    )
    enriched = build_enriched_lineage(db, company_id=company_id, event=row)
    return _to_lineage_response(enriched)
