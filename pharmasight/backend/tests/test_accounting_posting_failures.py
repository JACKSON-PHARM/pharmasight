"""GL posting failures list/resolve service (no DB)."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.accounting.posting_failures_service import failure_to_dict, MAX_LIMIT, DEFAULT_LIMIT


class _Failure:
    def __init__(self):
        self.id = uuid4()
        self.company_id = uuid4()
        self.branch_id = uuid4()
        self.source_type = "sales_invoice"
        self.source_id = uuid4()
        self.posting_kind = "sale_revenue"
        self.idempotency_key = f"sales_invoice:{self.source_id}:sale_revenue"
        self.error_message = "Missing control account AR"
        self.resolved_at = None
        self.created_at = datetime.now(timezone.utc)


def test_failure_to_dict_shape():
    row = _Failure()
    d = failure_to_dict(row)
    assert d["source_type"] == "sales_invoice"
    assert d["posting_kind"] == "sale_revenue"
    assert d["resolved_at"] is None
    assert d["id"] == str(row.id)
    assert d["branch_id"] == str(row.branch_id)


def test_failure_to_dict_resolved():
    row = _Failure()
    row.resolved_at = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)
    d = failure_to_dict(row)
    assert d["resolved_at"] is not None
    assert "2026-01-15" in d["resolved_at"]


def test_failure_to_dict_null_branch():
    row = _Failure()
    row.branch_id = None
    d = failure_to_dict(row)
    assert d["branch_id"] is None


def test_limit_constants():
    assert DEFAULT_LIMIT == 100
    assert MAX_LIMIT == 500
