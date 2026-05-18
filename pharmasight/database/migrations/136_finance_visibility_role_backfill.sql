-- Migration 136: Backfill finance_visibility_scope and max_finance_classification by role template (E2)

-- Platform / company admins: company-wide visibility, executive classification
UPDATE user_branch_roles ubr
SET finance_visibility_scope = 'COMPANY',
    max_finance_classification = 'executive'
FROM user_roles ur
WHERE ubr.role_id = ur.id
  AND lower(trim(ur.role_name)) IN ('super admin', 'admin', 'owner', 'platform admin');

-- Cashier / till: till scope, operational reports only
UPDATE user_branch_roles ubr
SET finance_visibility_scope = 'TILL',
    max_finance_classification = 'operational'
FROM user_roles ur
WHERE ubr.role_id = ur.id
  AND lower(trim(ur.role_name)) IN ('cashier', 'till operator', 'sales assistant');

-- Procurement / viewer with reports: branch scope, management ceiling (defaults already BRANCH/management)
UPDATE user_branch_roles ubr
SET finance_visibility_scope = 'BRANCH',
    max_finance_classification = 'management'
FROM user_roles ur
WHERE ubr.role_id = ur.id
  AND lower(trim(ur.role_name)) IN ('pharmacist', 'viewer', 'procurement');

-- Roles with audit_read permission: AUDIT_READ scope (read-all branches), audit classification floor
UPDATE user_branch_roles ubr
SET finance_visibility_scope = 'AUDIT_READ',
    max_finance_classification = CASE
        WHEN ubr.max_finance_classification IN ('executive', 'audit') THEN ubr.max_finance_classification
        ELSE 'audit'
    END
WHERE EXISTS (
    SELECT 1
    FROM role_permissions rp
    JOIN permissions p ON p.id = rp.permission_id
    WHERE rp.role_id = ubr.role_id
      AND rp.branch_id IS NULL
      AND p.name = 'finance.reports.audit_read'
);

-- Company cashbook / VAT company viewers: elevate scope when not already COMPANY/AUDIT_READ
UPDATE user_branch_roles ubr
SET finance_visibility_scope = 'COMPANY'
WHERE finance_visibility_scope NOT IN ('COMPANY', 'AUDIT_READ')
  AND EXISTS (
    SELECT 1
    FROM role_permissions rp
    JOIN permissions p ON p.id = rp.permission_id
    WHERE rp.role_id = ubr.role_id
      AND rp.branch_id IS NULL
      AND p.name IN ('finance.cashbook.view_company', 'finance.vat.view_company', 'finance.reports.executive')
  );
