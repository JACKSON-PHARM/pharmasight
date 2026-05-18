"""
Operational Financial Command Center — aggregate GL + subledgers for executive UI.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.accounting.reconciliation.control_accounts import (
    ap_subledger_balance,
    ar_subledger_balance,
    build_control_reconciliation,
    cashbook_derived_balance,
)
from app.accounting.reports.profit_and_loss import build_profit_and_loss
from app.models.accounting import GlPostingFailure
from app.models.company import Branch
from app.models.customer import Customer
from app.models.purchase import SupplierInvoice
from app.models.supplier import Supplier
from app.models.sale import SalesInvoice
from app.services.etims.kra_company_activation import company_kra_execution_enabled

Q2 = Decimal("0.01")


def _q(v: Decimal) -> Decimal:
    return v.quantize(Q2, rounding=ROUND_HALF_UP)


def _f(v) -> float:
    return float(_q(Decimal(str(v or 0))))


def _cash_health_from_recon(controls: List[Dict[str, Any]]) -> str:
    for c in controls:
        if c.get("control_role") == "CASH":
            st = c.get("status") or ""
            if st == "FAIL":
                return "critical"
            if st == "PASS_WITH_WARNINGS":
                return "warning"
            return "healthy"
    return "unknown"


def _profit_health(revenue: Decimal, profit: Decimal, expenses: Decimal) -> str:
    if revenue <= 0:
        return "no_revenue"
    if profit < 0:
        return "loss"
    if expenses > revenue:
        return "overspending"
    return "healthy"


def build_command_center_overview(
    db: Session,
    *,
    company_id: UUID,
    branch_id: Optional[UUID],
    from_date: date,
    to_date: date,
) -> Dict[str, Any]:
    as_of = to_date
    kra_enabled = company_kra_execution_enabled(db, company_id)

    recon = build_control_reconciliation(
        db, company_id=company_id, branch_id=branch_id, as_of_date=as_of
    )
    controls = {c["control_role"]: c for c in recon.get("controls") or []}

    cash_sub = Decimal("0")
    if branch_id:
        cash_sub = cashbook_derived_balance(db, company_id=company_id, branch_id=branch_id, as_of_date=as_of)
    elif controls.get("CASH"):
        cash_sub = Decimal(str(controls["CASH"].get("subledger_balance") or 0))

    ar_sub = ar_subledger_balance(db, company_id=company_id, branch_id=branch_id, as_of_date=as_of)
    ap_sub = ap_subledger_balance(db, company_id=company_id, branch_id=branch_id, as_of_date=as_of)

    pnl = build_profit_and_loss(
        db,
        company_id=company_id,
        from_date=from_date,
        to_date=to_date,
        branch_id=branch_id,
    )
    revenue = Decimal(str(pnl["revenue"]))
    expenses = Decimal(str(pnl["operating_expenses"]))
    profit = Decimal(str(pnl["net_income"]))

    cash_gl = Decimal(str(controls.get("CASH", {}).get("gl_balance") or 0)) if controls.get("CASH") else cash_sub
    net_position = _q(cash_sub + ar_sub - ap_sub)

    failures_unresolved = (
        db.query(func.count(GlPostingFailure.id))
        .filter(
            GlPostingFailure.company_id == company_id,
            GlPostingFailure.resolved_at.is_(None),
        )
        .scalar()
        or 0
    )

    top_receivables = _top_customer_receivables(db, company_id=company_id, branch_id=branch_id, limit=10)
    top_payables = _top_supplier_payables(db, company_id=company_id, branch_id=branch_id, limit=10)
    branch_rows = _branch_performance_table(
        db,
        company_id=company_id,
        from_date=from_date,
        to_date=to_date,
        as_of=as_of,
        branch_id=branch_id,
    )

    return {
        "company_id": str(company_id),
        "branch_id": str(branch_id) if branch_id else None,
        "from_date": str(from_date),
        "to_date": str(to_date),
        "as_of_date": str(as_of),
        "kra_enabled": kra_enabled,
        "doctrine": "operational_command_center_m1",
        "position_strip": {
            "cash_available": _f(cash_sub),
            "cash_gl": _f(cash_gl),
            "customer_receivables": _f(ar_sub),
            "supplier_payables": _f(ap_sub),
            "net_liquidity_position": _f(net_position),
            "profit_this_period": _f(profit),
            "revenue_this_period": _f(revenue),
            "expense_burn_this_period": _f(expenses),
            "cash_health": _cash_health_from_recon(recon.get("controls") or []),
            "profit_health": _profit_health(revenue, profit, expenses),
        },
        "control_reconciliation": {
            "overall_status": recon.get("overall_status"),
            "controls": recon.get("controls"),
        },
        "branch_performance": branch_rows,
        "top_receivables": top_receivables,
        "top_payables": top_payables,
        "posting_failures_unresolved": int(failures_unresolved),
        "alerts": _build_alerts(
            recon_overall=recon.get("overall_status"),
            failures_unresolved=int(failures_unresolved),
            profit=profit,
            ap_sub=ap_sub,
            ar_sub=ar_sub,
        ),
    }


def _build_alerts(
    *,
    recon_overall: str,
    failures_unresolved: int,
    profit: Decimal,
    ap_sub: Decimal,
    ar_sub: Decimal,
) -> List[Dict[str, str]]:
    alerts: List[Dict[str, str]] = []
    if recon_overall == "FAIL":
        alerts.append({"level": "critical", "message": "Control accounts do not reconcile — review before period close."})
    if failures_unresolved > 0:
        alerts.append(
            {
                "level": "warning",
                "message": f"{failures_unresolved} GL posting failure(s) need attention.",
            }
        )
    if profit < 0:
        alerts.append({"level": "warning", "message": "Period shows a net loss."})
    if ap_sub > ar_sub and ar_sub > 0:
        alerts.append({"level": "info", "message": "Payables exceed receivables — monitor cash outflows."})
    return alerts


def _top_customer_receivables(
    db: Session,
    *,
    company_id: UUID,
    branch_id: Optional[UUID],
    limit: int,
) -> List[Dict[str, Any]]:
    q = (
        db.query(
            Customer.id,
            Customer.name,
            func.coalesce(func.sum(SalesInvoice.balance), 0).label("outstanding"),
        )
        .outerjoin(
            SalesInvoice,
            (SalesInvoice.customer_id == Customer.id)
            & (SalesInvoice.company_id == company_id)
            & (SalesInvoice.status.in_(("BATCHED", "PAID")))
            & (SalesInvoice.balance > 0),
        )
        .filter(Customer.company_id == company_id, Customer.is_active.is_(True))
    )
    if branch_id:
        q = q.filter(SalesInvoice.branch_id == branch_id)
    rows = (
        q.group_by(Customer.id, Customer.name)
        .having(func.coalesce(func.sum(SalesInvoice.balance), 0) > 0)
        .order_by(func.sum(SalesInvoice.balance).desc())
        .limit(limit)
        .all()
    )
    out = []
    for r in rows:
        bal = Decimal(str(r.outstanding or 0))
        risk = "high" if bal >= 500000 else "moderate" if bal >= 100000 else "low"
        out.append(
            {
                "customer_id": str(r.id),
                "customer_name": r.name or "—",
                "outstanding": _f(bal),
                "risk": risk,
            }
        )
    return out


def _top_supplier_payables(
    db: Session,
    *,
    company_id: UUID,
    branch_id: Optional[UUID],
    limit: int,
) -> List[Dict[str, Any]]:
    q = (
        db.query(
            Supplier.id,
            Supplier.name,
            func.coalesce(func.sum(SupplierInvoice.balance), 0).label("outstanding"),
        )
        .join(SupplierInvoice, SupplierInvoice.supplier_id == Supplier.id)
        .filter(
            Supplier.company_id == company_id,
            SupplierInvoice.company_id == company_id,
            SupplierInvoice.status == "BATCHED",
            SupplierInvoice.balance > 0,
        )
    )
    if branch_id:
        q = q.filter(SupplierInvoice.branch_id == branch_id)
    rows = (
        q.group_by(Supplier.id, Supplier.name)
        .order_by(func.sum(SupplierInvoice.balance).desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "supplier_id": str(r.id),
            "supplier_name": r.name or "—",
            "outstanding": _f(Decimal(str(r.outstanding or 0))),
        }
        for r in rows
    ]


def _branch_performance_table(
    db: Session,
    *,
    company_id: UUID,
    from_date: date,
    to_date: date,
    as_of: date,
    branch_id: Optional[UUID] = None,
) -> List[Dict[str, Any]]:
    from app.accounting.inventory_valuation import branch_inventory_valuation

    q = db.query(Branch).filter(Branch.company_id == company_id, Branch.is_active.is_(True))
    if branch_id:
        q = q.filter(Branch.id == branch_id)
    branches = q.order_by(Branch.name.asc()).limit(25 if not branch_id else 1).all()

    rows: List[Dict[str, Any]] = []
    for b in branches:
        pnl = build_profit_and_loss(
            db, company_id=company_id, from_date=from_date, to_date=to_date, branch_id=b.id
        )
        rev = Decimal(str(pnl["revenue"]))
        exp = Decimal(str(pnl["operating_expenses"]))
        prof = Decimal(str(pnl["net_income"]))
        # One full recon at top level; per-branch cash health from cashbook only (avoids N slow reconciliations).
        try:
            cash_sub = cashbook_derived_balance(db, company_id=company_id, branch_id=b.id, as_of_date=as_of)
            cash_health = "healthy" if cash_sub >= 0 else "warning"
        except Exception:
            cash_health = "unknown"
        stock_val = branch_inventory_valuation(db, company_id=company_id, branch_id=b.id, as_of_date=as_of)
        profit_h = _profit_health(rev, prof, exp)
        stock_risk = "high" if stock_val >= 1000000 and prof < 0 else "medium" if stock_val >= 500000 else "low"
        rows.append(
            {
                "branch_id": str(b.id),
                "branch_name": b.name or "—",
                "is_hq": bool(getattr(b, "is_hq", False)),
                "revenue": _f(rev),
                "profit": _f(prof),
                "expenses": _f(exp),
                "stock_value": _f(stock_val),
                "stock_risk": stock_risk,
                "cash_health": cash_health,
                "profit_health": profit_h,
                "reconciliation_status": "SKIPPED",
            }
        )
    rows.sort(key=lambda x: (-x["profit"], x["branch_name"]))
    return rows
