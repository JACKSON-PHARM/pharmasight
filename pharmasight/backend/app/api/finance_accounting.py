"""
E7 accounting orchestration API — journal proposals (interpretation only).
"""
from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session, selectinload

from app.dependencies import get_current_user, get_tenant_db
from app.finance.accounting.doctrine import introspect_accounting_doctrine
from app.finance.accounting.posting import (
    approve_journal_proposal,
    post_journal_proposal,
    reverse_journal_proposal,
)
from app.finance.accounting.proposer import generate_journal_proposal_from_event
from app.finance.accounting.registry import list_supported_event_types
from app.finance.authority.doctrine import introspect_authority_doctrine
from app.finance.authority.eligibility import assess_posting_eligibility
from app.finance.doctrine.orchestration_boundary import introspect_orchestration_boundary
from app.finance.governance.access import guard_finance_report_access
from app.finance.governance.request_context import bind_fastapi_request
from app.models import User
from app.models.journal_proposal import JournalProposal
from app.schemas.finance_accounting import (
    GenerateProposalRequest,
    JournalProposalEvidenceResponse,
    JournalProposalLineResponse,
    JournalProposalResponse,
    PostingEligibilityResponse,
    ProposalActionResponse,
)

router = APIRouter(prefix="/finance/accounting", tags=["Finance Accounting"])


def _company_id(request: Request, db: Session, user: User) -> UUID:
    cid = getattr(request.state, "effective_company_id", None)
    if cid is not None:
        return cid
    from app.dependencies import get_effective_company_id_for_user

    cid = get_effective_company_id_for_user(db, user)
    if cid is None:
        raise HTTPException(status_code=400, detail="Company context not available")
    return cid


def _to_response(p: JournalProposal) -> JournalProposalResponse:
    return JournalProposalResponse(
        id=p.id,
        company_id=p.company_id,
        branch_id=p.branch_id,
        proposal_number=p.proposal_number,
        status=p.status,
        policy_pack_id=p.policy_pack_id,
        source_financial_event_id=p.source_financial_event_id,
        reversal_of_proposal_id=p.reversal_of_proposal_id,
        commercial_transaction_id=p.commercial_transaction_id,
        currency_code=p.currency_code,
        total_amount=p.total_amount,
        occurred_at=p.occurred_at,
        authoritative=False,
        derived=True,
        lines=[JournalProposalLineResponse.model_validate(l) for l in (p.lines or [])],
        evidence=[
            JournalProposalEvidenceResponse(
                financial_event_id=e.financial_event_id,
                link_semantic=e.link_semantic,
            )
            for e in (p.evidence_links or [])
        ],
        created_at=p.created_at,
        approved_at=p.approved_at,
        posted_at=p.posted_at,
    )


@router.get("/doctrine")
def get_accounting_doctrine(
    request: Request,
    user_db=Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    bind_fastapi_request(request)
    user, _ = user_db
    company_id = _company_id(request, db, user)
    guard_finance_report_access(db, user, company_id, "finance.gl.view", "management")
    return {
        "accounting": introspect_accounting_doctrine(),
        "authority": introspect_authority_doctrine(),
        "orchestration_boundary": introspect_orchestration_boundary(),
        "supported_event_types": list_supported_event_types(),
    }


@router.get("/eligibility/{financial_event_id}", response_model=PostingEligibilityResponse)
def check_eligibility(
    financial_event_id: UUID,
    request: Request,
    for_post: bool = Query(False),
    user_db=Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    bind_fastapi_request(request)
    user, _ = user_db
    company_id = _company_id(request, db, user)
    guard_finance_report_access(
        db, user, company_id, "finance.gl.post" if for_post else "finance.gl.view", "management"
    )
    result = assess_posting_eligibility(
        db,
        company_id=company_id,
        financial_event_id=financial_event_id,
        user_id=user.id,
        for_post=for_post,
    )
    return PostingEligibilityResponse(
        eligible=result.eligible,
        reasons=list(result.reasons),
        commercial_state=result.commercial_state,
        requires_permission=result.requires_permission,
    )


@router.post("/proposals/generate", response_model=ProposalActionResponse)
def generate_proposal(
    body: GenerateProposalRequest,
    request: Request,
    user_db=Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    bind_fastapi_request(request)
    user, _ = user_db
    company_id = _company_id(request, db, user)
    guard_finance_report_access(db, user, company_id, "finance.gl.view", "management")
    outcome = generate_journal_proposal_from_event(
        db,
        company_id=company_id,
        financial_event_id=body.financial_event_id,
        actor_user_id=user.id,
        policy_pack_id=body.policy_pack_id,
    )
    if not outcome.proposal_id:
        raise HTTPException(status_code=400, detail=outcome.message)
    return ProposalActionResponse(
        success=outcome.created, message=outcome.message, proposal_id=outcome.proposal_id
    )


@router.get("/proposals", response_model=List[JournalProposalResponse])
def list_proposals(
    request: Request,
    status: Optional[str] = Query(None),
    branch_id: Optional[UUID] = Query(None),
    limit: int = Query(100, le=500),
    user_db=Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    bind_fastapi_request(request)
    user, _ = user_db
    company_id = _company_id(request, db, user)
    guard_finance_report_access(db, user, company_id, "finance.gl.view", "management")
    q = (
        db.query(JournalProposal)
        .options(selectinload(JournalProposal.lines), selectinload(JournalProposal.evidence_links))
        .filter(JournalProposal.company_id == company_id)
    )
    if status:
        q = q.filter(JournalProposal.status == status)
    if branch_id:
        q = q.filter(JournalProposal.branch_id == branch_id)
    rows = q.order_by(JournalProposal.created_at.desc()).limit(limit).all()
    return [_to_response(p) for p in rows]


@router.get("/proposals/{proposal_id}", response_model=JournalProposalResponse)
def get_proposal(
    proposal_id: UUID,
    request: Request,
    user_db=Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    bind_fastapi_request(request)
    user, _ = user_db
    company_id = _company_id(request, db, user)
    guard_finance_report_access(db, user, company_id, "finance.gl.view", "management")
    p = (
        db.query(JournalProposal)
        .options(selectinload(JournalProposal.lines), selectinload(JournalProposal.evidence_links))
        .filter(JournalProposal.id == proposal_id, JournalProposal.company_id == company_id)
        .first()
    )
    if not p:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return _to_response(p)


@router.post("/proposals/{proposal_id}/approve", response_model=ProposalActionResponse)
def approve_proposal(
    proposal_id: UUID,
    request: Request,
    user_db=Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    bind_fastapi_request(request)
    user, _ = user_db
    company_id = _company_id(request, db, user)
    guard_finance_report_access(db, user, company_id, "finance.gl.post", "management")
    outcome = approve_journal_proposal(
        db, company_id=company_id, proposal_id=proposal_id, actor_user_id=user.id
    )
    if not outcome.success:
        raise HTTPException(status_code=400, detail=outcome.message)
    return ProposalActionResponse(True, outcome.message, outcome.proposal_id)


@router.post("/proposals/{proposal_id}/post", response_model=ProposalActionResponse)
def post_proposal(
    proposal_id: UUID,
    request: Request,
    user_db=Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    bind_fastapi_request(request)
    user, _ = user_db
    company_id = _company_id(request, db, user)
    guard_finance_report_access(db, user, company_id, "finance.gl.post", "management")
    outcome = post_journal_proposal(
        db, company_id=company_id, proposal_id=proposal_id, actor_user_id=user.id
    )
    if not outcome.success:
        raise HTTPException(status_code=400, detail=outcome.message)
    return ProposalActionResponse(True, outcome.message, outcome.proposal_id)


@router.post("/proposals/{proposal_id}/reverse", response_model=ProposalActionResponse)
def reverse_proposal(
    proposal_id: UUID,
    request: Request,
    user_db=Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    bind_fastapi_request(request)
    user, _ = user_db
    company_id = _company_id(request, db, user)
    guard_finance_report_access(db, user, company_id, "finance.gl.post", "management")
    outcome = reverse_journal_proposal(
        db, company_id=company_id, proposal_id=proposal_id, actor_user_id=user.id
    )
    if not outcome.success:
        raise HTTPException(status_code=400, detail=outcome.message)
    return ProposalActionResponse(True, outcome.message, outcome.proposal_id)
