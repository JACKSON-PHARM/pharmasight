"""Domain vocabulary and rules (constitutional semantics, no I/O)."""

from app.domain.commercial_transaction_state import (
    SPINE_STATES,
    TERMINAL_STATES,
    TransactionState,
    build_allowed_transition_map,
    is_lawful_transition,
    is_spine_forward_transition,
)

__all__ = [
    "TransactionState",
    "SPINE_STATES",
    "TERMINAL_STATES",
    "build_allowed_transition_map",
    "is_lawful_transition",
    "is_spine_forward_transition",
]
