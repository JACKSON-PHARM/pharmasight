"""
Revenue Recovery & Exposure Intelligence — operational AR and payer exposure.

Answers business questions (who owes us, aging risk, insurer delay) from operational
records and lineage projections. Causally explainable via source entities and events.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.finance.projections.engine import execute_projection
from app.models.company import Branch
from app.models.insurance_financial import InsuranceClaim, InsuranceProvider
from app.models.sale import SalesInvoice
from app.services.invoice_workflow_policy import (
    ENCOUNTER_CONSOLIDATED,
    RETAIL_COUNTER,
    WHOLESALE_DISTRIBUTION,
    doctrine_label,
    get_invoice_workflow_type,
)


def _decimal(v) -> Decimal:
    return Decimal(str(v or 0))


def _aging_bucket(invoice_date: date, as_of: date) -> str:
    days = (as_of - invoice_date).days
    if days <= 30:
        return "0_30"
    if days <= 60:
        return "31_60"
    if days <= 90:
        return "61_90"
    return "90_plus"


def build_recovery_exposure_intelligence(
    db: Session,
    *,
    company_id: UUID,
    branch_id: UUID,
    since: date,
    until: date,
    as_of: Optional[date] = None,
    exposure_limit: int = 100,
) -> Dict[str, Any]:
    as_of = as_of or until
    since_dt = datetime.combine(since, datetime.min.time(), tzinfo=timezone.utc)
    until_dt = datetime.combine(until, datetime.max.time(), tzinfo=timezone.utc)

    open_invoices = (
        db.query(SalesInvoice)
        .filter(
            SalesInvoice.company_id == company_id,
            SalesInvoice.branch_id == branch_id,
            SalesInvoice.balance > 0,
            SalesInvoice.status.in_(("BATCHED", "PAID")),
        )
        .order_by(SalesInvoice.invoice_date.asc())
        .limit(exposure_limit)
        .all()
    )

    aging: Dict[str, Decimal] = {"0_30": Decimal("0"), "31_60": Decimal("0"), "61_90": Decimal("0"), "90_plus": Decimal("0")}
    wholesale_rows: List[dict] = []
    retail_credit_rows: List[dict] = []
    retail_open_count = 0

    for inv in open_invoices:
        bal = _decimal(inv.balance)
        inv_date = inv.invoice_date or as_of
        bucket = _aging_bucket(inv_date, as_of)
        aging[bucket] += bal
        st = (inv.sales_type or "").strip().upper()
        if st == "RETAIL":
            retail_open_count += 1
            retail_credit_rows.append(
                {
                    "sales_invoice_id": str(inv.id),
                    "document_no": inv.invoice_no,
                    "customer_name": inv.customer_name or "Walk-in / retail",
                    "invoice_date": str(inv.invoice_date) if inv.invoice_date else None,
                    "balance": str(bal),
                    "aging_bucket": bucket,
                    "payment_status": inv.payment_status,
                }
            )
            continue
        wholesale_rows.append(
            {
                "sales_invoice_id": str(inv.id),
                "document_no": inv.invoice_no,
                "customer_name": inv.customer_name or "—",
                "invoice_date": str(inv.invoice_date) if inv.invoice_date else None,
                "due_date": str(inv.due_date) if inv.due_date else None,
                "balance": str(bal),
                "aging_bucket": bucket,
                "payment_status": inv.payment_status,
                "explainability": {
                    "source_entity_type": "sales_invoice",
                    "source_entity_id": str(inv.id),
                    "lineage_event_types": ["receivable_accrued", "cash_received", "retail_cash_collected"],
                },
            }
        )

    claims = (
        db.query(InsuranceClaim, InsuranceProvider.name)
        .outerjoin(InsuranceProvider, InsuranceClaim.insurance_provider_id == InsuranceProvider.id)
        .filter(
            InsuranceClaim.company_id == company_id,
            InsuranceClaim.branch_id == branch_id,
            InsuranceClaim.outstanding_amount > 0,
        )
        .order_by(InsuranceClaim.submitted_at.asc().nullslast())
        .limit(exposure_limit)
        .all()
    )

    payer_rows: List[dict] = []
    payer_totals: Dict[str, Decimal] = {}
    for claim, provider_name in claims:
        out = _decimal(claim.outstanding_amount)
        pname = provider_name or "Unknown payer"
        payer_totals[pname] = payer_totals.get(pname, Decimal("0")) + out
        payer_rows.append(
            {
                "insurance_claim_id": str(claim.id),
                "claim_number": claim.claim_number,
                "payer_name": pname,
                "status": claim.status,
                "outstanding_amount": str(out),
                "billed_amount": str(claim.billed_amount or 0),
                "submitted_at": claim.submitted_at.isoformat() if claim.submitted_at else None,
                "explainability": {
                    "source_entity_type": "insurance_claim",
                    "source_entity_id": str(claim.id),
                    "lineage_event_types": [
                        "insurance_claim_recognized",
                        "insurance_settlement_received",
                    ],
                },
            }
        )

    ar_projection = execute_projection(
        db,
        projection_id="ar_recognized_vs_collected",
        company_id=company_id,
        branch_id=branch_id,
        since=since,
        until=until,
    )
    insurance_projection = execute_projection(
        db,
        projection_id="insurance_claim_exposure",
        company_id=company_id,
        branch_id=branch_id,
        since=since,
        until=until,
    )

    branch = (
        db.query(Branch)
        .filter(Branch.id == branch_id, Branch.company_id == company_id)
        .first()
    )
    branch_doctrine = get_invoice_workflow_type(branch)
    branch_doctrine_label = doctrine_label(branch_doctrine)

    total_open = sum(aging.values(), Decimal("0"))
    total_insurance = sum(payer_totals.values(), Decimal("0"))
    wholesale_open = sum(_decimal(r["balance"]) for r in wholesale_rows)
    retail_credit_open = sum(_decimal(r["balance"]) for r in retail_credit_rows)

    deteriorating = [r for r in wholesale_rows if r["aging_bucket"] in ("61_90", "90_plus")]
    retail_at_risk = [r for r in retail_credit_rows if r["aging_bucket"] in ("61_90", "90_plus")]

    interpretation = (
        "retail_cash_first"
        if branch_doctrine == RETAIL_COUNTER
        else "wholesale_credit"
        if branch_doctrine == WHOLESALE_DISTRIBUTION
        else "encounter_insurance"
        if branch_doctrine == ENCOUNTER_CONSOLIDATED
        else "mixed"
    )
    slow_payers = sorted(
        [{"payer_name": k, "outstanding": str(v)} for k, v in payer_totals.items()],
        key=lambda x: _decimal(x["outstanding"]),
        reverse=True,
    )[:10]

    return {
        "phase": "revenue_recovery_exposure_intelligence",
        "branch_id": str(branch_id),
        "since": str(since),
        "until": str(until),
        "as_of": str(as_of),
        "branch_doctrine": {
            "invoice_workflow_type": branch_doctrine,
            "label": branch_doctrine_label,
            "interpretation": interpretation,
        },
        "headline": {
            "total_outstanding_receivables": str(total_open),
            "wholesale_credit_outstanding": str(wholesale_open),
            "retail_credit_outstanding": str(retail_credit_open),
            "total_insurance_exposure": str(total_insurance),
            "wholesale_open_invoices": len(wholesale_rows),
            "retail_credit_invoices": len(retail_credit_rows),
            "deteriorating_wholesale_count": len(deteriorating),
            "deteriorating_retail_credit_count": len(retail_at_risk),
            "active_payer_count": len(payer_totals),
        },
        "questions": {
            "who_owes_us": {
                "wholesale_invoices": wholesale_rows[:50],
                "retail_credit_invoices": retail_credit_rows[:50],
                "insurance_claims": payer_rows[:50],
            },
            "what_is_at_risk": {
                "aging_buckets": {k: str(v) for k, v in aging.items()},
                "deteriorating_wholesale": deteriorating[:25],
            },
            "which_insurers_delay": slow_payers,
        },
        "lineage_period_summary": {
            "ar_recognized_vs_collected": {
                "recognized_accrual": ar_projection.get("recognized_accrual"),
                "collected_inflow": ar_projection.get("collected_inflow"),
                "derived": True,
                "authoritative": False,
                "disclaimer": ar_projection.get("disclaimer"),
            },
            "insurance_claim_exposure": {
                "claim_accrual": insurance_projection.get("claim_accrual"),
                "settlement_inflow": insurance_projection.get("settlement_inflow"),
                "derived": True,
                "authoritative": False,
                "disclaimer": insurance_projection.get("disclaimer"),
            },
        },
        "doctrine": {
            "operational_records_authoritative_for_balances": True,
            "lineage_explains_economic_flow": True,
            "not_accounting_ledger": True,
        },
        "traceability": {
            "open_balances_source": "sales_invoices.balance",
            "insurance_exposure_source": "insurance_claims.outstanding_amount",
            "projections": [
                "ar_recognized_vs_collected",
                "insurance_claim_exposure",
            ],
        },
    }
