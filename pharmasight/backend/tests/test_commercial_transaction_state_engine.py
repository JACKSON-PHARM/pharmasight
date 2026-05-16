"""
Layer 2 — Commercial Transaction State Engine unit tests (no DB, no HTTP).
"""
from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

import pytest

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.domain.commercial_transaction_state import (
  TransactionState,
  is_lawful_transition,
)
from app.models.commercial_transaction import CommercialTransaction
from app.services.transaction_state_engine import (
  ActorAuthorityError,
  IllegalTransitionError,
  SkippedStateError,
  TerminalStateError,
  TransitionActor,
  TransitionContext,
  TransitionFrozenError,
  current_state,
  transition_transaction,
  validate_transition,
)


def _tx(state: TransactionState = TransactionState.DRAFT) -> CommercialTransaction:
  return CommercialTransaction(
    id=uuid4(),
    company_id=uuid4(),
    branch_id=uuid4(),
    constitutional_state=state.value,
  )


class _FakeSession:
  """Minimal session for transition_transaction flush/add."""

  def __init__(self) -> None:
    self.added: list = []

  def add(self, obj) -> None:
    self.added.append(obj)

  def flush(self) -> None:
    pass


def test_lawful_spine_transitions():
  spine = [
    TransactionState.DRAFT,
    TransactionState.OPERATIONALLY_COMPLETE,
    TransactionState.COMMERCIALLY_COMPLETE,
    TransactionState.BILLING_ACCEPTED,
    TransactionState.FISCAL_READY,
    TransactionState.FISCAL_EXTERNALIZED,
  ]
  for a, b in zip(spine, spine[1:]):
    assert is_lawful_transition(a, b)


def test_skipped_transitions_rejected():
  tx = _tx(TransactionState.DRAFT)
  with pytest.raises(SkippedStateError):
    validate_transition(tx, TransactionState.BILLING_ACCEPTED, TransitionActor(uuid4(), "billing"))
  with pytest.raises(SkippedStateError):
    validate_transition(tx, TransactionState.FISCAL_EXTERNALIZED, TransitionActor(uuid4(), "billing"))


def test_settlement_parallel_from_billing_accepted():
  tx = _tx(TransactionState.BILLING_ACCEPTED)
  validate_transition(tx, TransactionState.SETTLEMENT_ACTIVE, TransitionActor(uuid4(), "cashier"))


def test_reversal_from_billing_accepted():
  tx = _tx(TransactionState.BILLING_ACCEPTED)
  validate_transition(tx, TransactionState.REVERSED, TransitionActor(uuid4(), "billing"))


def test_amended_not_allowed_from_fiscal_externalized():
  tx = _tx(TransactionState.FISCAL_EXTERNALIZED)
  with pytest.raises(SkippedStateError):
    validate_transition(tx, TransactionState.AMENDED, TransitionActor(uuid4(), "billing"))


def test_dispute_freeze_and_resume():
  tx = _tx(TransactionState.COMMERCIALLY_COMPLETE)
  validate_transition(tx, TransactionState.DISPUTE_FROZEN, TransitionActor(uuid4(), "billing"))
  tx.frozen_resume_state = TransactionState.COMMERCIALLY_COMPLETE.value
  tx.constitutional_state = TransactionState.DISPUTE_FROZEN.value
  validate_transition(
    tx,
    TransactionState.COMMERCIALLY_COMPLETE,
    TransitionActor(uuid4(), "billing"),
  )


def test_dispute_resume_wrong_target_rejected():
  tx = _tx(TransactionState.DISPUTE_FROZEN)
  tx.frozen_resume_state = TransactionState.COMMERCIALLY_COMPLETE.value
  with pytest.raises(IllegalTransitionError):
    validate_transition(tx, TransactionState.BILLING_ACCEPTED, TransitionActor(uuid4(), "billing"))


def test_exception_hold_blocks_fiscal_externalization():
  tx = _tx(TransactionState.EXCEPTION_HOLD)
  tx.frozen_resume_state = TransactionState.FISCAL_READY.value
  with pytest.raises(TransitionFrozenError):
    validate_transition(
      tx,
      TransactionState.FISCAL_EXTERNALIZED,
      TransitionActor(uuid4(), "fiscal_submitter"),
    )


def test_exception_hold_flag_on_fiscal_ready_blocks_externalization():
  tx = _tx(TransactionState.FISCAL_READY)
  with pytest.raises(TransitionFrozenError):
    validate_transition(
      tx,
      TransactionState.FISCAL_EXTERNALIZED,
      TransitionActor(uuid4(), "fiscal_submitter"),
      TransitionContext(
        exception_blocks_fiscal_externalization=True,
        extra={"exception_hold_active": True},
      ),
    )


def test_terminal_state_blocks_forward():
  tx = _tx(TransactionState.REVERSED)
  with pytest.raises(TerminalStateError):
    validate_transition(tx, TransactionState.DRAFT, TransitionActor(uuid4(), "billing"))


def test_cashier_cannot_fiscal_externalize():
  tx = _tx(TransactionState.FISCAL_READY)
  with pytest.raises(ActorAuthorityError):
    validate_transition(tx, TransactionState.FISCAL_EXTERNALIZED, TransitionActor(uuid4(), "cashier_only"))


def test_transition_transaction_appends_audit_and_updates_state():
  tx = _tx(TransactionState.DRAFT)
  db = _FakeSession()
  actor = TransitionActor(user_id=uuid4(), role="billing")
  row = transition_transaction(
    db,
    tx,
    TransactionState.OPERATIONALLY_COMPLETE,
    actor,
    TransitionContext(basis="unit_test"),
  )
  assert current_state(tx) == TransactionState.OPERATIONALLY_COMPLETE
  assert row.from_state == TransactionState.DRAFT.value
  assert row.to_state == TransactionState.OPERATIONALLY_COMPLETE.value
  assert len(db.added) == 1


def test_full_spine_via_engine():
  tx = _tx()
  db = _FakeSession()
  actor = TransitionActor(user_id=uuid4(), role="billing")
  for target in [
    TransactionState.OPERATIONALLY_COMPLETE,
    TransactionState.COMMERCIALLY_COMPLETE,
    TransactionState.BILLING_ACCEPTED,
    TransactionState.FISCAL_READY,
    TransactionState.FISCAL_EXTERNALIZED,
  ]:
    transition_transaction(db, tx, target, actor)
  assert current_state(tx) == TransactionState.FISCAL_EXTERNALIZED
