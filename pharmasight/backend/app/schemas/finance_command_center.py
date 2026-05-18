"""Schemas for operational financial command center."""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class PositionStrip(BaseModel):
    cash_available: float
    cash_gl: float
    customer_receivables: float
    supplier_payables: float
    net_liquidity_position: float
    profit_this_period: float
    revenue_this_period: float
    expense_burn_this_period: float
    cash_health: str
    profit_health: str


class CommandCenterAlert(BaseModel):
    level: str
    message: str


class TopReceivableRow(BaseModel):
    customer_id: str
    customer_name: str
    outstanding: float
    risk: str


class TopPayableRow(BaseModel):
    supplier_id: str
    supplier_name: str
    outstanding: float


class BranchPerformanceRow(BaseModel):
    branch_id: str
    branch_name: str
    is_hq: bool
    revenue: float
    profit: float
    expenses: float
    stock_value: float
    stock_risk: str
    cash_health: str
    profit_health: str
    reconciliation_status: str


class CommandCenterOverviewResponse(BaseModel):
    company_id: str
    branch_id: Optional[str] = None
    from_date: str
    to_date: str
    as_of_date: str
    kra_enabled: bool
    doctrine: str
    position_strip: PositionStrip
    control_reconciliation: Dict[str, Any]
    branch_performance: List[BranchPerformanceRow]
    top_receivables: List[TopReceivableRow]
    top_payables: List[TopPayableRow]
    posting_failures_unresolved: int
    alerts: List[CommandCenterAlert]
