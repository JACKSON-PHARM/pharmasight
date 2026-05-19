"""H2 liability allocation — slice computation and registry."""
from decimal import Decimal
from uuid import uuid4

from app.finance.events.policies import HOSPITAL_INSURANCE, event_enabled_for_pack
from app.finance.events.registry import get_event_spec
from app.hospital.economic.liability_engine import ObligorSlice, compute_slices_from_coverage, _validate_slices
from app.models.hospital_economic import PfjCoverageProfile


def _profile(**kwargs) -> PfjCoverageProfile:
    p = PfjCoverageProfile(
        company_id=uuid4(),
        pfj_id=uuid4(),
        coverage_role="primary",
        obligor_route="self_pay",
        insurer_coverage_percent=Decimal("80"),
        is_active=True,
    )
    for k, v in kwargs.items():
        setattr(p, k, v)
    return p


def test_self_pay_100_percent_patient():
    slices = compute_slices_from_coverage(Decimal("1000"), _profile(obligor_route="self_pay"))
    assert len(slices) == 1
    assert slices[0].obligor_type == "patient"
    assert slices[0].amount_inclusive == Decimal("1000.0000")


def test_insurance_split_80_20():
    slices = compute_slices_from_coverage(
        Decimal("1000"),
        _profile(obligor_route="insurance", insurer_coverage_percent=Decimal("80")),
    )
    assert len(slices) == 2
    insurer = next(s for s in slices if s.obligor_type == "insurer")
    patient = next(s for s in slices if s.obligor_type == "patient")
    assert insurer.amount_inclusive == Decimal("800.0000")
    assert patient.amount_inclusive == Decimal("200.0000")
    _validate_slices(Decimal("1000"), slices)


def test_employer_route():
    slices = compute_slices_from_coverage(
        Decimal("500"),
        _profile(obligor_route="employer", employer_name="Acme Ltd"),
    )
    assert len(slices) == 1
    assert slices[0].obligor_type == "employer"
    assert slices[0].employer_ref == "Acme Ltd"


def test_liability_allocated_event_registered():
    spec = get_event_spec("liability_allocated")
    assert spec.source_entity_type == "liability_allocation_run"
    assert spec.economic_direction == "adjustment"
    assert event_enabled_for_pack(HOSPITAL_INSURANCE, "liability_allocated")


def test_validate_slices_rejects_mismatch():
    import pytest

    with pytest.raises(ValueError):
        _validate_slices(
            Decimal("100"),
            [ObligorSlice(obligor_type="patient", amount_inclusive=Decimal("99"))],
        )
