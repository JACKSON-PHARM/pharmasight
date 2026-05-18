"""
Authoritative GL posting engine (M1).

Materializes balanced journals from operational documents — never from projections.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.accounting.constants import BALANCE_TOLERANCE
from app.accounting.fiscal_period_service import ensure_company_accounting_ready
from app.accounting.posting.types import PostingLineSpec, PostingResult
from app.models.accounting import GlJournalEntry, GlJournalLine, GlPostingFailure

logger = logging.getLogger("pharmasight.accounting.posting")

Q2 = Decimal("0.01")
TOLERANCE = Decimal(BALANCE_TOLERANCE)


def _q(v: Decimal) -> Decimal:
    return v.quantize(Q2, rounding=ROUND_HALF_UP)


def build_idempotency_key(source_type: str, source_id: UUID, posting_kind: str) -> str:
    return f"{source_type}:{source_id}:{posting_kind}"


def _validate_balanced(lines: List[PostingLineSpec]) -> None:
    if not lines:
        raise ValueError("Journal must have at least one line")
    td = sum((_q(Decimal(str(l.debit))) for l in lines), Decimal("0"))
    tc = sum((_q(Decimal(str(l.credit))) for l in lines), Decimal("0"))
    if abs(td - tc) > TOLERANCE:
        raise ValueError(f"Unbalanced journal: debit={td} credit={tc}")
    for ln in lines:
        d, c = _q(Decimal(str(ln.debit))), _q(Decimal(str(ln.credit)))
        if d > 0 and c > 0:
            raise ValueError("Line cannot have both debit and credit")
        if d == 0 and c == 0:
            raise ValueError("Line must have debit or credit")


def _next_journal_number(db: Session, company_id: UUID) -> str:
    n = db.query(GlJournalEntry).filter(GlJournalEntry.company_id == company_id).count()
    return f"JE-{n + 1:06d}"


def record_posting_failure(
    db: Session,
    *,
    company_id: UUID,
    branch_id: Optional[UUID],
    source_type: str,
    source_id: UUID,
    posting_kind: str,
    error_message: str,
) -> None:
    key = build_idempotency_key(source_type, source_id, posting_kind)
    existing = (
        db.query(GlPostingFailure)
        .filter(
            GlPostingFailure.company_id == company_id,
            GlPostingFailure.idempotency_key == key,
            GlPostingFailure.resolved_at.is_(None),
        )
        .first()
    )
    if existing:
        existing.error_message = (error_message or "")[:4000]
        return
    db.add(
        GlPostingFailure(
            company_id=company_id,
            branch_id=branch_id,
            source_type=source_type,
            source_id=source_id,
            posting_kind=posting_kind,
            idempotency_key=key,
            error_message=(error_message or "unknown")[:4000],
        )
    )
    db.flush()


def post_journal(
    db: Session,
    *,
    company_id: UUID,
    branch_id: UUID,
    posting_date: date,
    source_type: str,
    source_id: UUID,
    posting_kind: str,
    lines: List[PostingLineSpec],
    posted_by: Optional[UUID],
    description: str,
    metadata: Optional[dict] = None,
    reversal_of_entry_id: Optional[UUID] = None,
) -> PostingResult:
    idem = build_idempotency_key(source_type, source_id, posting_kind)
    existing = (
        db.query(GlJournalEntry.id)
        .filter(
            GlJournalEntry.company_id == company_id,
            GlJournalEntry.idempotency_key == idem,
            GlJournalEntry.status == "POSTED",
        )
        .first()
    )
    if existing:
        return PostingResult(False, existing[0], "duplicate", skipped_duplicate=True)

    _validate_balanced(lines)
    period = ensure_company_accounting_ready(db, company_id, posting_date)

    try:
        with db.begin_nested():
            entry = GlJournalEntry(
                company_id=company_id,
                branch_id=branch_id,
                fiscal_period_id=period.id,
                journal_number=_next_journal_number(db, company_id),
                posting_date=posting_date,
                description=description,
                status="POSTED",
                source_type=source_type,
                source_id=source_id,
                posting_kind=posting_kind,
                idempotency_key=idem,
                reversal_of_entry_id=reversal_of_entry_id,
                posted_by=posted_by,
                posted_at=datetime.now(timezone.utc),
                metadata_json=metadata or {},
            )
            db.add(entry)
            db.flush()

            for i, spec in enumerate(lines, start=1):
                db.add(
                    GlJournalLine(
                        journal_entry_id=entry.id,
                        line_order=i,
                        account_id=spec.account_id,
                        branch_id=branch_id,
                        debit=_q(Decimal(str(spec.debit))),
                        credit=_q(Decimal(str(spec.credit))),
                        description=spec.description,
                    )
                )
            db.flush()
    except IntegrityError as e:
        dup = (
            db.query(GlJournalEntry.id)
            .filter(GlJournalEntry.company_id == company_id, GlJournalEntry.idempotency_key == idem)
            .first()
        )
        if dup:
            return PostingResult(False, dup[0], "duplicate_race", skipped_duplicate=True)
        raise ValueError(f"GL post failed integrity check: {e}") from e

    return PostingResult(True, entry.id, "posted")


def post_journal_for_operation(
    db: Session,
    *,
    company_id: UUID,
    branch_id: UUID,
    posting_date: date,
    source_type: str,
    source_id: UUID,
    posting_kind: str,
    lines: List[PostingLineSpec],
    posted_by: Optional[UUID],
    description: str,
    metadata: Optional[dict] = None,
) -> PostingResult:
    """
    Post using company accounting_posting_mode: soft → post_journal_safe; hard → post_journal (propagates errors).
    """
    from app.accounting.company_settings import accounting_posting_is_hard

    if accounting_posting_is_hard(db, company_id):
        return post_journal(
            db,
            company_id=company_id,
            branch_id=branch_id,
            posting_date=posting_date,
            source_type=source_type,
            source_id=source_id,
            posting_kind=posting_kind,
            lines=lines,
            posted_by=posted_by,
            description=description,
            metadata=metadata,
        )
    return post_journal_safe(
        db,
        company_id=company_id,
        branch_id=branch_id,
        posting_date=posting_date,
        source_type=source_type,
        source_id=source_id,
        posting_kind=posting_kind,
        lines=lines,
        posted_by=posted_by,
        description=description,
        metadata=metadata,
    )


def post_journal_safe(
    db: Session,
    *,
    company_id: UUID,
    branch_id: UUID,
    posting_date: date,
    source_type: str,
    source_id: UUID,
    posting_kind: str,
    lines: List[PostingLineSpec],
    posted_by: Optional[UUID],
    description: str,
    metadata: Optional[dict] = None,
) -> PostingResult:
    """Post or record failure without raising (operational batch continues)."""
    try:
        return post_journal(
            db,
            company_id=company_id,
            branch_id=branch_id,
            posting_date=posting_date,
            source_type=source_type,
            source_id=source_id,
            posting_kind=posting_kind,
            lines=lines,
            posted_by=posted_by,
            description=description,
            metadata=metadata,
        )
    except Exception as e:
        logger.exception(
            "GL post failed source_type=%s source_id=%s posting_kind=%s",
            source_type,
            source_id,
            posting_kind,
        )
        try:
            record_posting_failure(
                db,
                company_id=company_id,
                branch_id=branch_id,
                source_type=source_type,
                source_id=source_id,
                posting_kind=posting_kind,
                error_message=str(e),
            )
        except Exception:
            logger.exception("Failed to record gl_posting_failure")
        return PostingResult(False, None, str(e))
