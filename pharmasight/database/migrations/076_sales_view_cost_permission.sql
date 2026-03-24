-- Migration 076: Dedicated Sales cost visibility permission
-- Adds sales.view_cost to control visibility of cost in Sales Invoice / Quotation item search.
-- Default behavior remains visible by granting this permission to all existing roles.

INSERT INTO permissions (name, module, action, description) VALUES
('sales.view_cost', 'sales', 'view_cost', 'View item cost price in Sales Invoice and Quotation item search')
ON CONFLICT (name) DO NOTHING;

DO $$
DECLARE
    perm_id UUID;
    r RECORD;
BEGIN
    SELECT id INTO perm_id FROM permissions WHERE name = 'sales.view_cost' LIMIT 1;
    IF perm_id IS NOT NULL THEN
        FOR r IN SELECT id FROM user_roles
        LOOP
            INSERT INTO role_permissions (role_id, permission_id, branch_id)
            SELECT r.id, perm_id, NULL
            WHERE NOT EXISTS (
                SELECT 1 FROM role_permissions rp
                WHERE rp.role_id = r.id AND rp.permission_id = perm_id AND rp.branch_id IS NULL
            );
        END LOOP;
    END IF;
END $$;

