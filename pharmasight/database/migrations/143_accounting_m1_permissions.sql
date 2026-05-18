-- Migration 143: M1 accounting permissions (materialized GL)

INSERT INTO permissions (name, module, action, description) VALUES
    ('accounting.view', 'accounting', 'view', 'View chart of accounts and GL journals'),
    ('accounting.post', 'accounting', 'post', 'Materialize GL from operational documents'),
    ('accounting.reports', 'accounting', 'reports', 'Trial balance, P&L, and balance sheet from GL'),
    ('accounting.close_period', 'accounting', 'close_period', 'Close fiscal accounting periods')
ON CONFLICT (name) DO NOTHING;

DO $$
DECLARE
    p RECORD;
    r RECORD;
BEGIN
    FOR p IN SELECT id FROM permissions WHERE name LIKE 'accounting.%'
    LOOP
        FOR r IN SELECT id FROM user_roles WHERE lower(trim(role_name)) IN ('super admin', 'admin', 'owner')
        LOOP
            INSERT INTO role_permissions (role_id, permission_id, branch_id)
            SELECT r.id, p.id, NULL
            WHERE NOT EXISTS (
                SELECT 1 FROM role_permissions rp
                WHERE rp.role_id = r.id AND rp.permission_id = p.id AND rp.branch_id IS NULL
            );
        END LOOP;
    END LOOP;
END $$;
