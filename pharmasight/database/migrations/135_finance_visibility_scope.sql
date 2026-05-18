-- Migration 135: E2 finance visibility scope + classification on branch assignments
-- Governance only: no GL, financial_events, or cashbook_accounts.

ALTER TABLE user_branch_roles
    ADD COLUMN IF NOT EXISTS finance_visibility_scope VARCHAR(20) NOT NULL DEFAULT 'BRANCH',
    ADD COLUMN IF NOT EXISTS max_finance_classification VARCHAR(20) NOT NULL DEFAULT 'management',
    ADD COLUMN IF NOT EXISTS department_store_id UUID NULL REFERENCES department_stores(id) ON DELETE SET NULL;

COMMENT ON COLUMN user_branch_roles.finance_visibility_scope IS
    'E2: SELF|TILL|DEPARTMENT|BRANCH|MULTI_BRANCH|COMPANY|AUDIT_READ — widest wins across assignments';
COMMENT ON COLUMN user_branch_roles.max_finance_classification IS
    'E2: operational|branch_finance|management|confidential|executive|audit — highest wins';
COMMENT ON COLUMN user_branch_roles.department_store_id IS
    'E2: optional department store when scope is DEPARTMENT';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'chk_user_branch_roles_finance_visibility_scope'
    ) THEN
        ALTER TABLE user_branch_roles
            ADD CONSTRAINT chk_user_branch_roles_finance_visibility_scope
            CHECK (finance_visibility_scope IN (
                'SELF', 'TILL', 'DEPARTMENT', 'BRANCH', 'MULTI_BRANCH', 'COMPANY', 'AUDIT_READ'
            ));
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'chk_user_branch_roles_max_finance_classification'
    ) THEN
        ALTER TABLE user_branch_roles
            ADD CONSTRAINT chk_user_branch_roles_max_finance_classification
            CHECK (max_finance_classification IN (
                'operational', 'branch_finance', 'management', 'confidential', 'executive', 'audit'
            ));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_user_branch_roles_department_store
    ON user_branch_roles(department_store_id)
    WHERE department_store_id IS NOT NULL;
