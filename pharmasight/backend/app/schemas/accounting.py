"""Schemas for M1 GL reporting."""
from datetime import date
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel


class TrialBalanceLine(BaseModel):
    account_id: str
    code: str
    name: str
    category: str
    normal_balance: str
    debit: Decimal
    credit: Decimal
    net_balance: Decimal


class TrialBalanceTotals(BaseModel):
    debit: Decimal
    credit: Decimal
    delta: Decimal


class TrialBalanceResponse(BaseModel):
    company_id: str
    branch_id: Optional[str] = None
    as_of_date: str
    doctrine: str
    lines: List[TrialBalanceLine]
    totals: TrialBalanceTotals
    balanced: bool


class ChartOfAccountResponse(BaseModel):
    id: UUID
    code: str
    name: str
    category: str
    control_role: Optional[str] = None
    is_control_account: bool
    normal_balance: str
    is_active: bool

    class Config:
        from_attributes = True


class ControlReconciliationRow(BaseModel):
    control_role: str
    label: str
    subledger_balance: Decimal
    gl_balance: Decimal
    delta: Decimal
    status: str
    warnings: List[str] = []


class ControlReconciliationResponse(BaseModel):
    company_id: str
    branch_id: Optional[str] = None
    as_of_date: str
    doctrine: str
    tolerance: str
    overall_status: str
    controls: List[ControlReconciliationRow]


class ProfitAndLossResponse(BaseModel):
    company_id: str
    branch_id: Optional[str] = None
    from_date: str
    to_date: str
    doctrine: str
    revenue: Decimal
    cost_of_sales: Decimal
    gross_profit: Decimal
    operating_expenses: Decimal
    net_income: Decimal


class BalanceSheetSection(BaseModel):
    label: str
    amount: Decimal


class BalanceSheetResponse(BaseModel):
    company_id: str
    branch_id: Optional[str] = None
    as_of_date: str
    doctrine: str
    assets: Decimal
    liabilities: Decimal
    equity_per_gl: Decimal
    current_year_net_income: Decimal
    retained_equity_computed: Decimal
    liabilities_and_equity: Decimal
    balance_delta: Decimal
    balanced: bool
    sections: List[BalanceSheetSection]


class GlPostingFailureItem(BaseModel):
    id: str
    company_id: str
    branch_id: Optional[str] = None
    source_type: str
    source_id: str
    posting_kind: str
    idempotency_key: str
    error_message: str
    resolved_at: Optional[str] = None
    created_at: Optional[str] = None


class GlPostingFailureListResponse(BaseModel):
    company_id: str
    branch_id: Optional[str] = None
    unresolved_only: bool
    total_matching: int
    unresolved_count: int
    limit: int
    offset: int
    items: List[GlPostingFailureItem]


class GlPostingFailureResolveResponse(BaseModel):
    id: str
    resolved_at: str
    message: str = "resolved"


class VatReconciliationDifference(BaseModel):
    document_type: str
    document_id: str
    document_number: Optional[str] = None
    vat_amount: str
    reason: str
    submission_status: Optional[str] = None


class VatReconciliationResponse(BaseModel):
    company_id: str
    branch_id: Optional[str] = None
    from_date: str
    to_date: str
    doctrine: str
    kra_enabled: bool
    tolerance: str
    status: str
    gl_operational_status: Optional[str] = None
    kra_submission_status: Optional[str] = None
    message: Optional[str] = None
    gl_vat_output: Optional[Decimal] = None
    gl_vat_input: Optional[Decimal] = None
    operational_vat_output_sales: Optional[Decimal] = None
    operational_vat_output_credit_notes: Optional[Decimal] = None
    operational_vat_output_net: Optional[Decimal] = None
    operational_vat_input: Optional[Decimal] = None
    etims_submitted_vat_output: Optional[Decimal] = None
    delta_output_gl_vs_operational: Optional[Decimal] = None
    delta_input_gl_vs_operational: Optional[Decimal] = None
    delta_etims_vs_operational_sales: Optional[Decimal] = None
    differences: List[VatReconciliationDifference] = []
    difference_count: int = 0
