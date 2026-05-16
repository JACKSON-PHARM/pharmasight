"""
Commercial transaction state vocabulary — single source of truth (Layer 2).

Maps to constitutional Transaction State Transition Constitution.
Do not duplicate these string values elsewhere; import from here.
"""
from __future__ import annotations

from enum import Enum
from typing import Dict, FrozenSet, Set


class TransactionState(str, Enum):
  DRAFT = "DRAFT"
  OPERATIONALLY_COMPLETE = "OPERATIONALLY_COMPLETE"
  COMMERCIALLY_COMPLETE = "COMMERCIALLY_COMPLETE"
  BILLING_ACCEPTED = "BILLING_ACCEPTED"
  FISCAL_READY = "FISCAL_READY"
  FISCAL_EXTERNALIZED = "FISCAL_EXTERNALIZED"
  SETTLEMENT_ACTIVE = "SETTLEMENT_ACTIVE"
  SETTLEMENT_CLOSED = "SETTLEMENT_CLOSED"
  DISPUTE_FROZEN = "DISPUTE_FROZEN"
  EXCEPTION_HOLD = "EXCEPTION_HOLD"
  REVERSED = "REVERSED"
  AMENDED = "AMENDED"


SPINE_STATES: FrozenSet[TransactionState] = frozenset(
  {
    TransactionState.DRAFT,
    TransactionState.OPERATIONALLY_COMPLETE,
    TransactionState.COMMERCIALLY_COMPLETE,
    TransactionState.BILLING_ACCEPTED,
    TransactionState.FISCAL_READY,
    TransactionState.FISCAL_EXTERNALIZED,
  }
)

TERMINAL_STATES: FrozenSet[TransactionState] = frozenset(
  {
    TransactionState.REVERSED,
    TransactionState.AMENDED,
    TransactionState.SETTLEMENT_CLOSED,
  }
)

_PRE_EXTERNALIZATION: FrozenSet[TransactionState] = frozenset(
  {
    TransactionState.DRAFT,
    TransactionState.OPERATIONALLY_COMPLETE,
    TransactionState.COMMERCIALLY_COMPLETE,
    TransactionState.BILLING_ACCEPTED,
    TransactionState.FISCAL_READY,
  }
)


def _parse_state(value: TransactionState | str) -> TransactionState:
  if isinstance(value, TransactionState):
    return value
  raw = str(value).strip().upper()
  try:
    return TransactionState(raw)
  except ValueError as e:
    raise ValueError(f"Unknown transaction state: {value!r}") from e


def build_allowed_transition_map() -> Dict[TransactionState, FrozenSet[TransactionState]]:
  """
  Constitutional lawful transitions (Transaction State Transition Constitution).
  """
  allowed: Dict[TransactionState, Set[TransactionState]] = {s: set() for s in TransactionState}

  # Primary spine
  allowed[TransactionState.DRAFT].add(TransactionState.OPERATIONALLY_COMPLETE)
  allowed[TransactionState.OPERATIONALLY_COMPLETE].add(TransactionState.COMMERCIALLY_COMPLETE)
  allowed[TransactionState.COMMERCIALLY_COMPLETE].add(TransactionState.BILLING_ACCEPTED)
  allowed[TransactionState.BILLING_ACCEPTED].add(TransactionState.FISCAL_READY)
  allowed[TransactionState.FISCAL_READY].add(TransactionState.FISCAL_EXTERNALIZED)

  # Parallel settlement (non-blocking spine)
  allowed[TransactionState.BILLING_ACCEPTED].add(TransactionState.SETTLEMENT_ACTIVE)
  allowed[TransactionState.FISCAL_EXTERNALIZED].add(TransactionState.SETTLEMENT_ACTIVE)
  allowed[TransactionState.SETTLEMENT_ACTIVE].add(TransactionState.SETTLEMENT_CLOSED)

  # Correction paths
  allowed[TransactionState.BILLING_ACCEPTED].update(
    {TransactionState.REVERSED, TransactionState.AMENDED}
  )
  allowed[TransactionState.FISCAL_READY].update(
    {TransactionState.REVERSED, TransactionState.AMENDED}
  )
  allowed[TransactionState.FISCAL_EXTERNALIZED].add(TransactionState.REVERSED)

  # Overlays — enter from pre-externalization spine
  for src in _PRE_EXTERNALIZATION:
    allowed[src].add(TransactionState.DISPUTE_FROZEN)
    allowed[src].add(TransactionState.EXCEPTION_HOLD)

  # Overlay exit: resume_state validated in engine via frozen_resume_state
  for resume in _PRE_EXTERNALIZATION:
    allowed[TransactionState.DISPUTE_FROZEN].add(resume)
    allowed[TransactionState.EXCEPTION_HOLD].add(resume)

  return {k: frozenset(v) for k, v in allowed.items()}


LAWFUL_TRANSITIONS: Dict[TransactionState, FrozenSet[TransactionState]] = build_allowed_transition_map()

# Explicitly forbidden shortcuts (constitutional prohibitions) for clear error messages.
FORBIDDEN_TRANSITIONS: FrozenSet[tuple[TransactionState, TransactionState]] = frozenset(
  {
    (TransactionState.DRAFT, TransactionState.BILLING_ACCEPTED),
    (TransactionState.DRAFT, TransactionState.FISCAL_EXTERNALIZED),
    (TransactionState.DRAFT, TransactionState.FISCAL_READY),
    (TransactionState.OPERATIONALLY_COMPLETE, TransactionState.BILLING_ACCEPTED),
    (TransactionState.OPERATIONALLY_COMPLETE, TransactionState.FISCAL_EXTERNALIZED),
    (TransactionState.COMMERCIALLY_COMPLETE, TransactionState.FISCAL_EXTERNALIZED),
    (TransactionState.COMMERCIALLY_COMPLETE, TransactionState.FISCAL_READY),
    (TransactionState.BILLING_ACCEPTED, TransactionState.FISCAL_EXTERNALIZED),
    (TransactionState.SETTLEMENT_ACTIVE, TransactionState.FISCAL_EXTERNALIZED),
    (TransactionState.FISCAL_EXTERNALIZED, TransactionState.AMENDED),
  }
)


def is_lawful_transition(
  from_state: TransactionState | str,
  to_state: TransactionState | str,
) -> bool:
  src = _parse_state(from_state)
  dst = _parse_state(to_state)
  if (src, dst) in FORBIDDEN_TRANSITIONS:
    return False
  return dst in LAWFUL_TRANSITIONS.get(src, frozenset())


def is_spine_forward_transition(
  from_state: TransactionState | str,
  to_state: TransactionState | str,
) -> bool:
  """True for single-step primary spine forward moves."""
  order = [
    TransactionState.DRAFT,
    TransactionState.OPERATIONALLY_COMPLETE,
    TransactionState.COMMERCIALLY_COMPLETE,
    TransactionState.BILLING_ACCEPTED,
    TransactionState.FISCAL_READY,
    TransactionState.FISCAL_EXTERNALIZED,
  ]
  src = _parse_state(from_state)
  dst = _parse_state(to_state)
  try:
    i = order.index(src)
    return order[i + 1] == dst
  except (ValueError, IndexError):
    return False
