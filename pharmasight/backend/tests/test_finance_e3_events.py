"""
E3 financial_events architectural tests.
"""
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.finance.events.emitter import EmitFinancialEventRequest, EmitResult, emit_financial_event
from app.finance.events.payload import validate_event_payload
from app.finance.events.registry import FINANCIAL_EVENT_REGISTRY, build_idempotency_key, get_event_spec

_BACKEND = Path(__file__).resolve().parent.parent
_API_ROOT = _BACKEND / "app" / "api"


def test_payload_rejects_invoice_clone():
    with pytest.raises(ValueError, match="forbidden"):
        validate_event_payload({"invoice": {"lines": [1, 2]}})


def test_payload_allows_lineage_context():
    validate_event_payload(
        {
            "document_no": "SD-001",
            "customer_id": str(uuid4()),
            "method": "mpesa",
        }
    )


def test_registry_has_initial_emitter_types():
    required = {
        "receivable_accrued",
        "cash_received",
        "payable_recognized",
        "cash_paid",
        "insurance_settlement_received",
        "expense_recognized",
    }
    assert required.issubset(FINANCIAL_EVENT_REGISTRY.keys())


def test_idempotency_key_template():
    spec = get_event_spec("receivable_accrued")
    key = build_idempotency_key(spec, source_entity_id=str(uuid4()))
    assert "sales_invoice:" in key
    assert "receivable_accrued" in key


def test_operational_modules_use_hooks_not_direct_insert():
    modules = (
        "sales.py",
        "customer_management.py",
        "purchases.py",
        "supplier_management.py",
        "insurance_management.py",
        "expenses.py",
    )
    offenders = []
    for rel in modules:
        text = (_API_ROOT / rel).read_text(encoding="utf-8")
        if "FinancialEvent(" in text or "db.add(FinancialEvent" in text:
            offenders.append(f"{rel}: direct FinancialEvent insert")
        if "finance.events.hooks" not in text:
            offenders.append(f"{rel}: missing finance.events.hooks")
    assert not offenders


def test_emit_financial_event_returns_failed_not_raises():
    """Emitter swallows errors — callers must not depend on exceptions."""

    class _BrokenSession:
        def add(self, *_a, **_k):
            raise RuntimeError("db down")

        def commit(self):
            raise RuntimeError("db down")

        def rollback(self):
            pass

        def query(self, *_a, **_k):
            raise RuntimeError("db down")

    req = EmitFinancialEventRequest(
        event_type="cash_received",
        company_id=uuid4(),
        branch_id=uuid4(),
        source_entity_id=uuid4(),
        occurred_at=datetime.now(timezone.utc),
        amount=Decimal("10"),
        payload={"method": "cash"},
    )
    result, _event_id = emit_financial_event(_BrokenSession(), req)
    assert result == EmitResult.FAILED


def test_emit_invalid_payload_returns_failed():
    class _Session:
        def add(self, *_a, **_k):
            pass

        def commit(self):
            pass

        def rollback(self):
            pass

        def query(self, *_a, **_k):
            class _Q:
                def filter(self, *_a, **_k):
                    return self

                def first(self):
                    return None

            return _Q()

    req = EmitFinancialEventRequest(
        event_type="cash_received",
        company_id=uuid4(),
        branch_id=uuid4(),
        source_entity_id=uuid4(),
        occurred_at=datetime.now(timezone.utc),
        amount=Decimal("10"),
        payload={"invoice": {}},
    )
    result, _ = emit_financial_event(_Session(), req)
    assert result == EmitResult.FAILED
