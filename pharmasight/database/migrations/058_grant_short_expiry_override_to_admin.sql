-- Migration 058: Grant inventory.short_expiry_override to Admin and Super Admin
-- So admins can batch short-expiry invoices without seeing "ask a manager" when they are the manager.
-- Permission was added in 057 but not assigned to any role; 019 only grants permissions that existed at run time.

DO $$
DECLARE
    perm_id UUID;
    r RECORD;
BEGIN
    SELECT id INTO perm_id FROM permissions WHERE name = 'inventory.short_expiry_override' LIMIT 1;
    IF perm_id IS NOT NULL THEN
        FOR r IN SELECT id FROM user_roles WHERE LOWER(role_name) IN ('super admin', 'admin')
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
