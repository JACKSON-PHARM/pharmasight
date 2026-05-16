"""
Constitutional evidence validation hooks (stubs — Layer 2).

Wire real evidence/attestation checks in later phases.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional
from uuid import UUID

from app.domain.commercial_transaction_state import TransactionState


@dataclass(frozen=True)
class EvidenceValidationResult:
  ok: bool
  code: str
  message: str = ""


def validate_operational_evidence(
  *,
  transaction_id: UUID,
  company_id: UUID,
  branch_id: UUID,
  context: Optional[dict[str, Any]] = None,
) -> EvidenceValidationResult:
  # TODO(ENCOUNTER_CONSOLIDATED): department attestations, inventory reconciliation.
  _ = (transaction_id, company_id, branch_id, context)
  return EvidenceValidationResult(ok=True, code="stub_operational_ok")


def validate_commercial_evidence(
  *,
  transaction_id: UUID,
  company_id: UUID,
  branch_id: UUID,
  context: Optional[dict[str, Any]] = None,
) -> EvidenceValidationResult:
  # TODO: commercial completeness, scope, charge closure.
  _ = (transaction_id, company_id, branch_id, context)
  return EvidenceValidationResult(ok=True, code="stub_commercial_ok")


def validate_billing_acceptance(
  *,
  transaction_id: UUID,
  company_id: UUID,
  branch_id: UUID,
  context: Optional[dict[str, Any]] = None,
) -> EvidenceValidationResult:
  # TODO: all mandatory evidence classes + attestor chain (Billing Acceptance Event).
  _ = (transaction_id, company_id, branch_id, context)
  return EvidenceValidationResult(ok=True, code="stub_billing_acceptance_ok")


def validate_fiscal_ready(
  *,
  transaction_id: UUID,
  company_id: UUID,
  branch_id: UUID,
  context: Optional[dict[str, Any]] = None,
) -> EvidenceValidationResult:
  # TODO: fiscal preparedness, snapshot freeze, no open disputes.
  _ = (transaction_id, company_id, branch_id, context)
  return EvidenceValidationResult(ok=True, code="stub_fiscal_ready_ok")


def validate_fiscal_externalization(
  *,
  transaction_id: UUID,
  company_id: UUID,
  branch_id: UUID,
  context: Optional[dict[str, Any]] = None,
) -> EvidenceValidationResult:
  # TODO: Fiscal Externalization Evidence Doctrine — regulator acknowledgment, snapshot match.
  _ = (transaction_id, company_id, branch_id, context)
  return EvidenceValidationResult(ok=True, code="stub_fiscal_externalization_ok")


def run_evidence_for_target_state(
  *,
  target_state: TransactionState,
  transaction_id: UUID,
  company_id: UUID,
  branch_id: UUID,
  context: Optional[dict[str, Any]] = None,
) -> EvidenceValidationResult:
  """Invoke stub hooks required for the target constitutional state."""
  if target_state == TransactionState.OPERATIONALLY_COMPLETE:
    return validate_operational_evidence(
      transaction_id=transaction_id,
      company_id=company_id,
      branch_id=branch_id,
      context=context,
    )
  if target_state == TransactionState.COMMERCIALLY_COMPLETE:
    return validate_commercial_evidence(
      transaction_id=transaction_id,
      company_id=company_id,
      branch_id=branch_id,
      context=context,
    )
  if target_state == TransactionState.BILLING_ACCEPTED:
    return validate_billing_acceptance(
      transaction_id=transaction_id,
      company_id=company_id,
      branch_id=branch_id,
      context=context,
    )
  if target_state == TransactionState.FISCAL_READY:
    return validate_fiscal_ready(
      transaction_id=transaction_id,
      company_id=company_id,
      branch_id=branch_id,
      context=context,
    )
  if target_state == TransactionState.FISCAL_EXTERNALIZED:
    return validate_fiscal_externalization(
      transaction_id=transaction_id,
      company_id=company_id,
      branch_id=branch_id,
      context=context,
    )
  return EvidenceValidationResult(ok=True, code="no_evidence_gate")
