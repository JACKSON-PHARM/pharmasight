"""VAT reconciliation status logic and KRA gate (no DB)."""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.accounting.reconciliation.vat import (
    RECON_TOLERANCE,
    compute_gl_operational_status,
    compute_kra_submission_status,
    compute_overall_vat_status,
)


def test_gl_operational_pass():
    assert (
        compute_gl_operational_status(
            gl_output=Decimal("160.00"),
            gl_input=Decimal("80.00"),
            operational_output_net=Decimal("160.00"),
            operational_input=Decimal("80.00"),
        )
        == "PASS"
    )


def test_gl_operational_fail_output():
    assert (
        compute_gl_operational_status(
            gl_output=Decimal("100.00"),
            gl_input=Decimal("80.00"),
            operational_output_net=Decimal("160.00"),
            operational_input=Decimal("80.00"),
        )
        == "FAIL"
    )


def test_kra_submission_not_applicable_when_kra_off():
    assert (
        compute_kra_submission_status(
            kra_enabled=False,
            gl_operational_status="PASS",
            etims_submitted_output=Decimal("0"),
            operational_sales_output=Decimal("160.00"),
        )
        == "NOT_APPLICABLE"
    )


def test_kra_submission_warn_when_submitted_differs():
    assert (
        compute_kra_submission_status(
            kra_enabled=True,
            gl_operational_status="PASS",
            etims_submitted_output=Decimal("100.00"),
            operational_sales_output=Decimal("160.00"),
        )
        == "WARN"
    )


def test_overall_pass_kra_off_uses_gl_only():
    assert compute_overall_vat_status("PASS", "NOT_APPLICABLE") == "PASS"


def test_overall_warn_when_kra_warn():
    assert compute_overall_vat_status("PASS", "WARN") == "WARN"


def test_recon_tolerance_constant():
    assert RECON_TOLERANCE == Decimal("0.05")


def test_kra_disabled_still_computes_gl_operational():
    """KRA off: GL vs operational runs; eTIMS leg NOT_APPLICABLE."""
    from datetime import date
    from unittest.mock import MagicMock, patch

    from app.accounting.reconciliation.vat import build_vat_reconciliation

    db = MagicMock()
    company_id = uuid4()

    class _Q:
        def filter(self, *a, **k):
            return self

        def join(self, *a, **k):
            return self

        def group_by(self, *a, **k):
            return self

        def order_by(self, *a, **k):
            return self

        def offset(self, *a, **k):
            return self

        def limit(self, *a, **k):
            return self

        def all(self):
            return []

        def first(self):
            return (0, 0)

        def scalar(self):
            return 0

        def count(self):
            return 0

    db.query.return_value = _Q()

    with patch(
        "app.accounting.reconciliation.vat.company_kra_execution_enabled",
        return_value=False,
    ), patch(
        "app.accounting.reconciliation.vat.control_account_map",
        return_value={},
    ):
        out = build_vat_reconciliation(
            db,
            company_id=company_id,
            from_date=date(2026, 1, 1),
            to_date=date(2026, 1, 31),
        )
    assert out["kra_enabled"] is False
    assert out["kra_submission_status"] == "NOT_APPLICABLE"
    assert out["gl_operational_status"] == "PASS"
    assert out["etims_submitted_vat_output"] is None
    assert not any(d.get("reason") == "Not submitted to eTIMS" for d in out["differences"])
