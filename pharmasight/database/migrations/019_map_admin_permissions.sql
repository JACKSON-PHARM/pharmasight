-- Migration 019: Grant all permissions to Super Admin and admin roles

DO $$
DECLARE
    p RECORD;
    admin_role_id UUID;
BEGIN
    SELECT id INTO admin_role_id FROM user_roles WHERE LOWER(role_name) IN ('super admin', 'admin') LIMIT 1;
    IF admin_role_id IS NOT NULL THEN
        FOR p IN SELECT id FROM permissions LOOP
            INSERT INTO role_permissions (role_id, permission_id, branch_id)
            SELECT admin_role_id, p.id, NULL
            WHERE NOT EXISTS (
                SELECT 1 FROM role_permissions rp
                WHERE rp.role_id = admin_role_id AND rp.permission_id = p.id AND rp.branch_id IS NULL
            );
        END LOOP;
    END IF;
END $$;
