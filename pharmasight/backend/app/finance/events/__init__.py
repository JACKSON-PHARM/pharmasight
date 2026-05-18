"""
Financial events — immutable economic lineage (E3).
"""

from app.finance.events.emitter import EmitResult, emit_financial_event, emit_reversal_event
from app.finance.events.registry import (
    FINANCIAL_EVENT_REGISTRY,
    FinancialEventSpec,
    get_event_spec,
    introspect_event_registry,
)
from app.finance.events.replay import replay_emission_failure, replay_unresolved_failures
from app.finance.events.integrity import verify_company_lineage

__all__ = [
    "EmitResult",
    "FINANCIAL_EVENT_REGISTRY",
    "FinancialEventSpec",
    "emit_financial_event",
    "emit_reversal_event",
    "get_event_spec",
    "introspect_event_registry",
    "replay_emission_failure",
    "replay_unresolved_failures",
    "verify_company_lineage",
]
