-- Migration 130: Customer / wholesale RBAC permissions

INSERT INTO permissions (name, module, action, description) VALUES
    ('customers.view', 'Customers', 'view', 'View wholesale customers'),
    ('customers.create', 'Customers', 'create', 'Create wholesale customers'),
    ('customers.edit', 'Customers', 'edit', 'Edit wholesale customers'),
    ('customers.delete', 'Customers', 'delete', 'Delete wholesale customers'),
    ('customers.record_payment', 'Customers', 'record_payment', 'Record customer payments and allocations'),
    ('customers.manage_credit', 'Customers', 'manage_credit', 'Manage customer credit limits and terms'),
    ('customers.manage_activities', 'Customers', 'manage_activities', 'Manage CRM activities and follow-ups')
ON CONFLICT (name) DO NOTHING;

DO $$
DECLARE
    p RECORD;
    r RECORD;
BEGIN
    FOR p IN SELECT id FROM permissions WHERE name LIKE 'customers.%'
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
