"""Hospital Economic Kernel H1 — registry, correlation, charge idempotency semantics."""
from decimal import Decimal
from uuid import uuid4

from app.finance.events.correlation import (
    CorrelationKind,
    correlation_group_for_patient_financial_journey,
)
from app.finance.events.policies import HOSPITAL_INSURANCE, event_enabled_for_pack
from app.finance.events.registry import get_event_spec


def test_care_value_events_registered():
    spec = get_event_spec("care_value_accrued")
    assert spec.operational_domain == "hospital"
    assert spec.source_entity_type == "care_charge"
    assert spec.economic_direction == "accrual"
    rev = get_event_spec("care_value_reversed")
    assert rev.compensating_event_type is None
    assert get_event_spec("care_value_accrued").compensating_event_type == "care_value_reversed"


def test_pfj_correlation_group_governance():
    pfj_id = uuid4()
    group = correlation_group_for_patient_financial_journey(pfj_id)
    assert group == f"{CorrelationKind.PATIENT_FINANCIAL_JOURNEY.value}:{pfj_id}"


def test_hospital_policy_pack_enables_care_value():
    assert event_enabled_for_pack(HOSPITAL_INSURANCE, "care_value_accrued")
    assert event_enabled_for_pack(HOSPITAL_INSURANCE, "care_value_reversed")
    assert event_enabled_for_pack(HOSPITAL_INSURANCE, "insurance_claim_recognized")


def test_accrue_charge_request_amounts():
    from app.hospital.economic.charge_engine import AccrueChargeRequest

    req = AccrueChargeRequest(
        company_id=uuid4(),
        branch_id=uuid4(),
        pfj_id=uuid4(),
        encounter_id=uuid4(),
        charge_kind="consultation",
        clinical_trigger="performed",
        source_entity_type="sales_invoice_item",
        source_entity_id=uuid4(),
        description="Consultation",
        amount_exclusive=Decimal("100"),
        vat_amount=Decimal("16"),
        amount_inclusive=Decimal("116"),
    )
    assert req.amount_inclusive == Decimal("116")
