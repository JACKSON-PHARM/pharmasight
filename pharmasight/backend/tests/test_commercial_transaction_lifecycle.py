"""
Phase B — commercial transaction lifecycle wiring (unit tests, no DB).
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.domain.commercial_transaction_state import TransactionState
from app.models.commercial_transaction import CommercialTransaction
from app.models.sale import SalesInvoice
from app.services.commercial_transaction_lifecycle import (
    on_sales_invoice_batched,
)
from app.services.transaction_state_engine import current_state


class _FakeSession:
    def __init__(self) -> None:
        self.added: list = []
        self._tx_by_invoice: dict = {}

    def add(self, obj) -> None:
        self.added.append(obj)

    def flush(self) -> None:
        pass

    def query(self, model):
        return _FakeQuery(self, model)


class _FakeQuery:
    def __init__(self, db: _FakeSession, model) -> None:
        self._db = db
        self._model = model

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        if self._model.__name__ == "CommercialTransaction":
            return None
        return None


def _invoice() -> SalesInvoice:
    return SalesInvoice(
        id=uuid4(),
        company_id=uuid4(),
        branch_id=uuid4(),
        invoice_no="SD-T-001",
        invoice_date=__import__("datetime").date.today(),
        payment_mode="cash",
        created_by=uuid4(),
        status="DRAFT",
    )


@patch("app.services.commercial_transaction_lifecycle.get_invoice_workflow_type_for_branch")
@patch("app.services.commercial_transaction_lifecycle.get_or_create_for_sales_invoice")
def test_retail_batch_advances_to_billing_accepted(mock_get_tx, mock_wf):
    mock_wf.return_value = "RETAIL_COUNTER"
    tx = CommercialTransaction(
        id=uuid4(),
        company_id=uuid4(),
        branch_id=uuid4(),
        constitutional_state=TransactionState.DRAFT.value,
    )
    mock_get_tx.return_value = tx
    db = _FakeSession()

    on_sales_invoice_batched(db, _invoice(), batched_by=uuid4())

    assert current_state(tx) == TransactionState.BILLING_ACCEPTED


@patch("app.services.commercial_transaction_lifecycle.get_invoice_workflow_type_for_branch")
@patch("app.services.commercial_transaction_lifecycle.get_or_create_for_sales_invoice")
def test_encounter_batch_stops_at_operationally_complete(mock_get_tx, mock_wf):
    mock_wf.return_value = "ENCOUNTER_CONSOLIDATED"
    tx = CommercialTransaction(
        id=uuid4(),
        company_id=uuid4(),
        branch_id=uuid4(),
        constitutional_state=TransactionState.DRAFT.value,
    )
    mock_get_tx.return_value = tx
    db = _FakeSession()

    on_sales_invoice_batched(db, _invoice(), batched_by=uuid4())

    assert current_state(tx) == TransactionState.OPERATIONALLY_COMPLETE
