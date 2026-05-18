-- Migration 133: Finance REBAC permission foundations (E1)
-- Namespaced finance.*, wholesale.ar.*, hospital.*, retail.till.*
-- reports.view remains for compatibility; new endpoints must use explicit finance permissions.

INSERT INTO permissions (name, module, action, description) VALUES
    ('finance.cashbook.view_branch', 'finance', 'cashbook_view_branch', 'View cashbook entries and branch cashbook summary'),
    ('finance.cashbook.view_company', 'finance', 'cashbook_view_company', 'View consolidated cashbook across branches (company scope)'),
    ('finance.cashbook.reconcile_branch', 'finance', 'cashbook_reconcile_branch', 'Reconcile cashbook and run branch cashbook maintenance (e.g. backfill)'),
    ('finance.reports.operational', 'finance', 'reports_operational', 'Operational finance and inventory movement reports'),
    ('finance.reports.management', 'finance', 'reports_management', 'Management P&L, margins, and branch financial summaries'),
    ('finance.reports.executive', 'finance', 'reports_executive', 'Executive consolidated company financial reports'),
    ('finance.reports.audit_read', 'finance', 'reports_audit_read', 'Read-only audit finance reports and trails'),
    ('finance.vat.view_branch', 'finance', 'vat_view_branch', 'View branch VAT reports'),
    ('finance.vat.view_company', 'finance', 'vat_view_company', 'View company VAT reports'),
    ('finance.vat.export', 'finance', 'vat_export', 'Export VAT compliance reports'),
    ('wholesale.ar.view', 'wholesale', 'ar_view', 'View wholesale receivables, aging, and statements'),
    ('wholesale.ar.collect', 'wholesale', 'ar_collect', 'Record customer payments and allocations'),
    ('wholesale.ar.credit_control', 'wholesale', 'ar_credit_control', 'Credit limits, terms, and credit-control reports'),
    ('hospital.billing.view', 'hospital', 'billing_view', 'View hospital billing and patient invoices'),
    ('hospital.billing.create', 'hospital', 'billing_create', 'Create hospital billing documents'),
    ('hospital.billing.adjust', 'hospital', 'billing_adjust', 'Adjust hospital billing'),
    ('hospital.insurance.view', 'hospital', 'insurance_view', 'View insurance providers, claims, and insurer reports'),
    ('hospital.insurance.settle', 'hospital', 'insurance_settle', 'Update claims and record insurance settlements'),
    ('hospital.insurance.manage_providers', 'hospital', 'insurance_manage_providers', 'Manage insurance provider master data'),
    ('retail.till.operate', 'retail', 'till_operate', 'Operate retail till (sales and receipts)'),
    ('retail.till.reconcile', 'retail', 'till_reconcile', 'Reconcile retail till and daily closure'),
    ('finance.gl.view', 'finance', 'gl_view', 'View general ledger (reserved; not enforced until GL epic)'),
    ('finance.gl.post', 'finance', 'gl_post', 'Post journal entries (reserved)'),
    ('finance.gl.period_close', 'finance', 'gl_period_close', 'Close financial periods (reserved)')
ON CONFLICT (name) DO NOTHING;

COMMENT ON TABLE permissions IS 'Includes finance REBAC names (migration 133). reports.view is deprecated for finance; use finance.* permissions.';
