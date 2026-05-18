"""
E7 guards — accounting layer must never mutate lineage tables.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.financial_event import FinancialEvent, FinancialEventSettlementLink


class LineageMutationForbidden(Exception):
    """Raised when accounting code attempts to mutate immutable lineage."""


def assert_accounting_does_not_touch_lineage(session: Session, operation: str) -> None:
    forbidden = ("update", "delete", "merge", "bulk_update", "bulk_delete")
    op = (operation or "").lower()
    if any(f in op for f in forbidden):
        raise LineageMutationForbidden(
            f"Accounting orchestration cannot perform {operation} on lineage tables"
        )


def block_lineage_model_mutation(instance: Any) -> None:
    if isinstance(instance, (FinancialEvent, FinancialEventSettlementLink)):
        raise LineageMutationForbidden(
            "financial_events and settlement_links are immutable from accounting layer"
        )
