"""
Transaction State Engine — enforces constitutional state transitions (Layer 2).

Pure business logic: no HTTP, no UI, no KRA integration.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.domain.commercial_transaction_state import (
  FORBIDDEN_TRANSITIONS,
  TERMINAL_STATES,
  TransactionState,
  is_lawful_transition,
)
from app.models.commercial_transaction import (
  CommercialTransaction,
  CommercialTransactionTransition,
)
from app.services.transaction_state_evidence import run_evidence_for_target_state


class TransactionStateError(Exception):
  """Base class for unlawful transitions."""


class IllegalTransitionError(TransactionStateError):
  def __init__(self, from_state: str, to_state: str, detail: str = "") -> None:
    self.from_state = from_state
    self.to_state = to_state
    msg = f"Illegal transition {from_state} -> {to_state}"
    if detail:
      msg = f"{msg}: {detail}"
    super().__init__(msg)


class SkippedStateError(TransactionStateError):
  """Constitutional shortcut (e.g. DRAFT -> BILLING_ACCEPTED)."""


class TransitionFrozenError(TransactionStateError):
  """Dispute freeze or exception hold blocks progression."""


class TerminalStateError(TransactionStateError):
  """No forward transitions from terminal correction/settlement states."""


class ActorAuthorityError(TransactionStateError):
  """Actor lacks authority for target transition (stub; extended later)."""


class EvidenceRejectedError(TransactionStateError):
  def __init__(self, code: str, message: str = "") -> None:
    self.code = code
    super().__init__(message or code)


@dataclass(frozen=True)
class TransitionActor:
  user_id: Optional[UUID]
  role: str = "system"


@dataclass
class TransitionContext:
  basis: Optional[str] = None
  supersedes_transition_id: Optional[UUID] = None
  resume_state: Optional[TransactionState | str] = None
  exception_blocks_fiscal_externalization: bool = True
  extra: Optional[dict[str, Any]] = None


def current_state(transaction: CommercialTransaction) -> TransactionState:
  return TransactionState(str(transaction.constitutional_state).strip().upper())


def _parse_target(value: TransactionState | str) -> TransactionState:
  if isinstance(value, TransactionState):
    return value
  return TransactionState(str(value).strip().upper())


def validate_actor_authority(
  *,
  actor: TransitionActor,
  from_state: TransactionState,
  to_state: TransactionState,
) -> None:
  """
  Stub: future branch doctrine + role matrix (Evidence Authority Constitution).
  """
  _ = (actor, from_state, to_state)
  if to_state == TransactionState.FISCAL_EXTERNALIZED and actor.role == "cashier_only":
    raise ActorAuthorityError("Cashier-only role may not trigger fiscal externalization")


def _validate_overlay_exit(
  transaction: CommercialTransaction,
  from_state: TransactionState,
  to_state: TransactionState,
) -> None:
  if from_state not in (TransactionState.DISPUTE_FROZEN, TransactionState.EXCEPTION_HOLD):
    return
  resume_raw = transaction.frozen_resume_state
  if not resume_raw:
    raise IllegalTransitionError(
      from_state.value,
      to_state.value,
      "overlay exit requires frozen_resume_state on transaction",
    )
  expected = TransactionState(str(resume_raw).strip().upper())
  if to_state != expected:
    raise IllegalTransitionError(
      from_state.value,
      to_state.value,
      f"overlay exit must resume to {expected.value}, not {to_state.value}",
    )


def _validate_overlay_enter(
  transaction: CommercialTransaction,
  from_state: TransactionState,
  to_state: TransactionState,
) -> None:
  if to_state not in (TransactionState.DISPUTE_FROZEN, TransactionState.EXCEPTION_HOLD):
    return
  transaction.frozen_resume_state = from_state.value


def _validate_freeze_blocks(
  transaction: CommercialTransaction,
  from_state: TransactionState,
  to_state: TransactionState,
  context: TransitionContext,
) -> None:
  if from_state == TransactionState.DISPUTE_FROZEN:
    return
  if from_state == TransactionState.EXCEPTION_HOLD:
    if to_state == TransactionState.FISCAL_EXTERNALIZED:
      raise TransitionFrozenError(
        "Exception hold blocks transition to FISCAL_EXTERNALIZED until cleared"
      )
    return
  if (
    from_state == TransactionState.FISCAL_READY
    and context.exception_blocks_fiscal_externalization
    and to_state == TransactionState.FISCAL_EXTERNALIZED
    and context.extra
    and context.extra.get("exception_hold_active")
  ):
    raise TransitionFrozenError(
      "Active exception hold blocks transition to FISCAL_EXTERNALIZED until cleared"
    )


def validate_transition(
  transaction: CommercialTransaction,
  target_state: TransactionState | str,
  actor: TransitionActor,
  context: Optional[TransitionContext] = None,
) -> TransactionState:
  """
  Validate a proposed transition without mutating state. Returns parsed target state.
  """
  ctx = context or TransitionContext()
  src = current_state(transaction)
  dst = _parse_target(target_state)

  if src in TERMINAL_STATES and dst != src:
    raise TerminalStateError(f"Cannot leave terminal state {src.value}")

  if (src, dst) in FORBIDDEN_TRANSITIONS:
    raise SkippedStateError(f"Forbidden shortcut {src.value} -> {dst.value}")

  _validate_freeze_blocks(transaction, src, dst, ctx)

  if not is_lawful_transition(src, dst):
    raise IllegalTransitionError(src.value, dst.value, "not in lawful transition matrix")

  _validate_overlay_exit(transaction, src, dst)
  validate_actor_authority(actor=actor, from_state=src, to_state=dst)

  evidence = run_evidence_for_target_state(
    target_state=dst,
    transaction_id=transaction.id,
    company_id=transaction.company_id,
    branch_id=transaction.branch_id,
    context=ctx.extra,
  )
  if not evidence.ok:
    raise EvidenceRejectedError(evidence.code, evidence.message)

  return dst


def transition_transaction(
  db: Session,
  transaction: CommercialTransaction,
  target_state: TransactionState | str,
  actor: TransitionActor,
  context: Optional[TransitionContext] = None,
) -> CommercialTransactionTransition:
  """
  Validate and apply a constitutional state transition; append audit record.
  """
  ctx = context or TransitionContext()
  src = current_state(transaction)
  dst = validate_transition(transaction, target_state, actor, ctx)

  if dst in (TransactionState.DISPUTE_FROZEN, TransactionState.EXCEPTION_HOLD):
    _validate_overlay_enter(transaction, src, dst)

  if src in (TransactionState.DISPUTE_FROZEN, TransactionState.EXCEPTION_HOLD):
    transaction.frozen_resume_state = None

  row = CommercialTransactionTransition(
    commercial_transaction_id=transaction.id,
    from_state=src.value,
    to_state=dst.value,
    actor_id=actor.user_id,
    basis=ctx.basis,
    supersedes_transition_id=ctx.supersedes_transition_id,
  )
  transaction.constitutional_state = dst.value
  transaction.updated_at = datetime.now(timezone.utc)

  db.add(row)
  db.flush()
  return row


def create_commercial_transaction(
  db: Session,
  *,
  company_id: UUID,
  branch_id: UUID,
  sales_invoice_id: Optional[UUID] = None,
  actor: Optional[TransitionActor] = None,
) -> CommercialTransaction:
  """Create a new commercial transaction in DRAFT with initial audit row."""
  tx = CommercialTransaction(
    company_id=company_id,
    branch_id=branch_id,
    constitutional_state=TransactionState.DRAFT.value,
    sales_invoice_id=sales_invoice_id,
  )
  db.add(tx)
  db.flush()
  act = actor or TransitionActor(user_id=None, role="system")
  row = CommercialTransactionTransition(
    commercial_transaction_id=tx.id,
    from_state=TransactionState.DRAFT.value,
    to_state=TransactionState.DRAFT.value,
    actor_id=act.user_id,
    basis="commercial_transaction_created",
  )
  db.add(row)
  db.flush()
  return tx
