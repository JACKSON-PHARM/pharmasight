"""
Operational hooks → financial_events (E3 emitters, E4/E5 policy + settlement).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional, Tuple
from uuid import UUID

from sqlalchemy.orm import Session

from app.finance.events.branch_policy import resolve_policy_pack_for_branch
from app.finance.events.correlation import (
    correlation_group_for_insurance_claim,
    correlation_group_for_insurance_settlement,
    correlation_group_for_invoice,
    correlation_group_for_payment,
    correlation_group_for_supplier_invoice,
    correlation_group_for_supplier_payment,
)
from app.finance.events.emitter import EmitFinancialEventRequest, EmitResult, emit_financial_event
from app.finance.events.policies import event_enabled_for_pack
from app.finance.events.settlement import (
    SETTLEMENT_CUSTOMER_PAYMENT,
    SETTLEMENT_INSURANCE,
    SETTLEMENT_SUPPLIER_PAYMENT,
    link_settlement_to_accruals,
    resolve_primary_caused_by_event_id,
)
from app.models.customer_financial import CustomerPayment, CustomerPaymentAllocation
from app.models.expense import Expense
from app.models.insurance_financial import InsuranceClaim, InsuranceSettlement
from app.models.purchase import SupplierInvoice
from app.models.sale import SalesInvoice
from app.models.supplier_financial import SupplierPayment, SupplierPaymentAllocation

logger = logging.getLogger(__name__)

_CLAIM_RECOGNITION_STATUSES = frozenset({"submitted", "approved", "partially_settled", "settled"})


def _safe_emit(
    db: Session, request: EmitFinancialEventRequest
) -> Tuple[EmitResult, Optional[UUID]]:
    try:
        return emit_financial_event(db, request)
    except Exception:
        logger.exception(
            "financial event hook unexpected error event_type=%s source=%s",
            request.event_type,
            request.source_entity_id,
        )
        return EmitResult.FAILED, None


def on_sales_invoice_batched_financial_event(db: Session, invoice: SalesInvoice) -> None:
    pack = resolve_policy_pack_for_branch(
        db, company_id=invoice.company_id, branch_id=invoice.branch_id, sales_type=invoice.sales_type
    )
    if event_enabled_for_pack(pack, "receivable_accrued") and invoice.customer_id:
        balance = Decimal(
            str(invoice.balance if invoice.balance is not None else invoice.total_inclusive or 0)
        )
        if balance > 0:
            occurred = datetime.combine(invoice.invoice_date, datetime.min.time(), tzinfo=timezone.utc)
            _safe_emit(
                db,
                EmitFinancialEventRequest(
                    event_type="receivable_accrued",
                    company_id=invoice.company_id,
                    branch_id=invoice.branch_id,
                    source_entity_id=invoice.id,
                    occurred_at=occurred,
                    amount=balance,
                    source_reference=invoice.invoice_no,
                    correlation_group=correlation_group_for_invoice(invoice.id),
                    payload={
                        "document_no": invoice.invoice_no,
                        "customer_id": str(invoice.customer_id),
                        "payment_status": invoice.payment_status,
                        "sales_type": invoice.sales_type,
                    },
                    governance_metadata={"emitter": "sales.batch", "policy_pack": pack.pack_id},
                ),
            )

    if event_enabled_for_pack(pack, "retail_cash_collected"):
        st = (invoice.sales_type or "").strip().upper()
        ps = (invoice.payment_status or "").strip().upper()
        if st == "RETAIL" and ps in ("PAID", "PARTIAL"):
            cash_amount = Decimal(str(invoice.total_inclusive or 0)) - Decimal(str(invoice.balance or 0))
            if cash_amount <= 0:
                cash_amount = Decimal(str(invoice.total_inclusive or 0))
            if cash_amount > 0:
                occurred = datetime.combine(invoice.invoice_date, datetime.min.time(), tzinfo=timezone.utc)
                _safe_emit(
                    db,
                    EmitFinancialEventRequest(
                        event_type="retail_cash_collected",
                        company_id=invoice.company_id,
                        branch_id=invoice.branch_id,
                        source_entity_id=invoice.id,
                        occurred_at=occurred,
                        amount=cash_amount,
                        source_reference=invoice.invoice_no,
                        correlation_group=correlation_group_for_invoice(invoice.id),
                        payload={
                            "document_no": invoice.invoice_no,
                            "payment_status": invoice.payment_status,
                            "sales_type": invoice.sales_type,
                        },
                        governance_metadata={"emitter": "sales.batch.retail_cash", "policy_pack": pack.pack_id},
                    ),
                )


def on_customer_payment_financial_event(db: Session, payment: CustomerPayment) -> None:
    pack = resolve_policy_pack_for_branch(
        db, company_id=payment.company_id, branch_id=payment.branch_id
    )
    if not event_enabled_for_pack(pack, "cash_received"):
        return
    occurred = datetime.combine(payment.payment_date, datetime.min.time(), tzinfo=timezone.utc)

    allocations: List[Tuple[UUID, str, Decimal]] = []
    for a in (
        db.query(CustomerPaymentAllocation)
        .filter(CustomerPaymentAllocation.customer_payment_id == payment.id)
        .all()
    ):
        allocations.append((a.sales_invoice_id, "sales_invoice", Decimal(str(a.allocated_amount or 0))))

    caused_by: Optional[UUID] = None
    if pack.settlement_linking_enabled and allocations:
        caused_by = resolve_primary_caused_by_event_id(
            db,
            company_id=payment.company_id,
            accrual_event_type="receivable_accrued",
            allocations=allocations,
        )

    result, event_id = _safe_emit(
        db,
        EmitFinancialEventRequest(
            event_type="cash_received",
            company_id=payment.company_id,
            branch_id=payment.branch_id,
            source_entity_id=payment.id,
            occurred_at=occurred,
            amount=Decimal(str(payment.amount or 0)),
            source_reference=payment.reference,
            caused_by_event_id=caused_by,
            correlation_group=correlation_group_for_payment(payment.id),
            payload={
                "customer_id": str(payment.customer_id),
                "method": payment.method,
                "is_allocated": bool(payment.is_allocated),
                "allocated_invoice_count": len(allocations),
            },
            governance_metadata={"emitter": "customers.payment", "policy_pack": pack.pack_id},
        ),
    )
    if pack.settlement_linking_enabled and event_id and result == EmitResult.CREATED and allocations:
        from app.models.financial_event import FinancialEvent

        settlement = db.query(FinancialEvent).filter(FinancialEvent.id == event_id).first()
        if settlement:
            link_settlement_to_accruals(
                db,
                company_id=payment.company_id,
                settlement_event=settlement,
                accrual_event_type="receivable_accrued",
                allocations=allocations,
                settlement_semantic=SETTLEMENT_CUSTOMER_PAYMENT,
            )


def on_supplier_invoice_batched_financial_event(db: Session, invoice: SupplierInvoice) -> None:
    pack = resolve_policy_pack_for_branch(
        db, company_id=invoice.company_id, branch_id=invoice.branch_id
    )
    if not event_enabled_for_pack(pack, "payable_recognized"):
        return
    amount = Decimal(str(invoice.total_inclusive or 0))
    if amount <= 0:
        return
    occurred = datetime.combine(invoice.invoice_date, datetime.min.time(), tzinfo=timezone.utc)
    _safe_emit(
        db,
        EmitFinancialEventRequest(
            event_type="payable_recognized",
            company_id=invoice.company_id,
            branch_id=invoice.branch_id,
            source_entity_id=invoice.id,
            occurred_at=occurred,
            amount=amount,
            source_reference=invoice.invoice_number,
            correlation_group=correlation_group_for_supplier_invoice(invoice.id),
            payload={
                "document_no": invoice.invoice_number,
                "supplier_id": str(invoice.supplier_id),
            },
            governance_metadata={"emitter": "purchases.batch_supplier_invoice", "policy_pack": pack.pack_id},
        ),
    )


def on_supplier_payment_financial_event(db: Session, payment: SupplierPayment) -> None:
    pack = resolve_policy_pack_for_branch(
        db, company_id=payment.company_id, branch_id=payment.branch_id
    )
    if not event_enabled_for_pack(pack, "cash_paid"):
        return
    occurred = datetime.combine(payment.payment_date, datetime.min.time(), tzinfo=timezone.utc)

    allocations: List[Tuple[UUID, str, Decimal]] = []
    for a in (
        db.query(SupplierPaymentAllocation)
        .filter(SupplierPaymentAllocation.supplier_payment_id == payment.id)
        .all()
    ):
        allocations.append(
            (a.supplier_invoice_id, "supplier_invoice", Decimal(str(a.allocated_amount or 0)))
        )

    caused_by = None
    if pack.settlement_linking_enabled and allocations:
        caused_by = resolve_primary_caused_by_event_id(
            db,
            company_id=payment.company_id,
            accrual_event_type="payable_recognized",
            allocations=allocations,
        )

    result, event_id = _safe_emit(
        db,
        EmitFinancialEventRequest(
            event_type="cash_paid",
            company_id=payment.company_id,
            branch_id=payment.branch_id,
            source_entity_id=payment.id,
            occurred_at=occurred,
            amount=Decimal(str(payment.amount or 0)),
            source_reference=payment.reference,
            caused_by_event_id=caused_by,
            correlation_group=correlation_group_for_supplier_payment(payment.id),
            payload={
                "supplier_id": str(payment.supplier_id),
                "method": payment.method,
                "is_allocated": bool(payment.is_allocated),
            },
            governance_metadata={"emitter": "suppliers.payment", "policy_pack": pack.pack_id},
        ),
    )
    if pack.settlement_linking_enabled and event_id and result == EmitResult.CREATED and allocations:
        from app.models.financial_event import FinancialEvent

        settlement = db.query(FinancialEvent).filter(FinancialEvent.id == event_id).first()
        if settlement:
            link_settlement_to_accruals(
                db,
                company_id=payment.company_id,
                settlement_event=settlement,
                accrual_event_type="payable_recognized",
                allocations=allocations,
                settlement_semantic=SETTLEMENT_SUPPLIER_PAYMENT,
            )


def on_insurance_claim_financial_event(
    db: Session,
    claim: InsuranceClaim,
    *,
    lifecycle_status: Optional[str] = None,
) -> None:
    pack = resolve_policy_pack_for_branch(
        db, company_id=claim.company_id, branch_id=claim.branch_id
    )
    if not event_enabled_for_pack(pack, "insurance_claim_recognized"):
        return
    status = (lifecycle_status or claim.status or "").strip().lower()
    if status not in _CLAIM_RECOGNITION_STATUSES:
        return
    amount = Decimal(str(claim.approved_amount or 0))
    if amount <= 0:
        amount = Decimal(str(claim.billed_amount or 0))
    if amount <= 0:
        return
    occurred = claim.submitted_at or datetime.now(timezone.utc)
    if occurred.tzinfo is None:
        occurred = occurred.replace(tzinfo=timezone.utc)
    _safe_emit(
        db,
        EmitFinancialEventRequest(
            event_type="insurance_claim_recognized",
            company_id=claim.company_id,
            branch_id=claim.branch_id,
            source_entity_id=claim.id,
            occurred_at=occurred,
            amount=amount,
            source_reference=claim.claim_number,
            correlation_group=correlation_group_for_insurance_claim(claim.id),
            payload={
                "claim_number": claim.claim_number,
                "claim_status": status,
                "insurance_provider_id": str(claim.insurance_provider_id),
                "sales_invoice_id": str(claim.sales_invoice_id),
                "lifecycle": "claim_recognition",
            },
            governance_metadata={"emitter": "insurance.claim", "policy_pack": pack.pack_id},
        ),
    )


def on_insurance_settlement_financial_event(db: Session, settlement: InsuranceSettlement) -> None:
    pack = resolve_policy_pack_for_branch(
        db, company_id=settlement.company_id, branch_id=settlement.branch_id
    )
    if not event_enabled_for_pack(pack, "insurance_settlement_received"):
        return
    occurred = datetime.combine(settlement.settlement_date, datetime.min.time(), tzinfo=timezone.utc)

    allocations: List[Tuple[UUID, str, Decimal]] = []
    for a in settlement.allocations or []:
        claim_id = getattr(a, "insurance_claim_id", None) or getattr(a, "claim_id", None)
        if claim_id:
            allocations.append(
                (claim_id, "insurance_claim", Decimal(str(a.allocated_amount or 0)))
            )

    caused_by = None
    if pack.settlement_linking_enabled and allocations:
        caused_by = resolve_primary_caused_by_event_id(
            db,
            company_id=settlement.company_id,
            accrual_event_type="insurance_claim_recognized",
            allocations=allocations,
        )

    result, event_id = _safe_emit(
        db,
        EmitFinancialEventRequest(
            event_type="insurance_settlement_received",
            company_id=settlement.company_id,
            branch_id=settlement.branch_id,
            source_entity_id=settlement.id,
            occurred_at=occurred,
            amount=Decimal(str(settlement.amount or 0)),
            source_reference=settlement.settlement_number,
            caused_by_event_id=caused_by,
            correlation_group=correlation_group_for_insurance_settlement(settlement.id),
            payload={
                "insurance_provider_id": str(settlement.insurance_provider_id),
                "method": settlement.method,
                "allocated_claim_count": len(allocations),
            },
            governance_metadata={"emitter": "insurance.settlement", "policy_pack": pack.pack_id},
        ),
    )
    if pack.settlement_linking_enabled and event_id and result == EmitResult.CREATED and allocations:
        from app.models.financial_event import FinancialEvent

        settlement_ev = db.query(FinancialEvent).filter(FinancialEvent.id == event_id).first()
        if settlement_ev:
            link_settlement_to_accruals(
                db,
                company_id=settlement.company_id,
                settlement_event=settlement_ev,
                accrual_event_type="insurance_claim_recognized",
                allocations=allocations,
                settlement_semantic=SETTLEMENT_INSURANCE,
            )


def on_expense_approved_financial_event(db: Session, expense: Expense) -> None:
    if expense.status != "approved":
        return
    pack = resolve_policy_pack_for_branch(
        db, company_id=expense.company_id, branch_id=expense.branch_id
    )
    if not event_enabled_for_pack(pack, "expense_recognized"):
        return
    occurred = datetime.combine(expense.expense_date, datetime.min.time(), tzinfo=timezone.utc)
    _safe_emit(
        db,
        EmitFinancialEventRequest(
            event_type="expense_recognized",
            company_id=expense.company_id,
            branch_id=expense.branch_id,
            source_entity_id=expense.id,
            occurred_at=occurred,
            amount=Decimal(str(expense.amount or 0)),
            source_reference=expense.reference_number,
            payload={
                "category_id": str(expense.category_id) if expense.category_id else None,
                "payment_mode": expense.payment_mode,
            },
            governance_metadata={"emitter": "expenses.approved", "policy_pack": pack.pack_id},
        ),
    )
