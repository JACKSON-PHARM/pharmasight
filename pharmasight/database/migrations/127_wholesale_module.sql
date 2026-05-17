-- Migration 127: Wholesale business module (B2B customer management)

INSERT INTO modules (name, category, is_core, is_clinical, is_billable) VALUES
    ('wholesale', 'business', FALSE, FALSE, TRUE)
ON CONFLICT (name) DO NOTHING;

INSERT INTO permissions (name, module, action, description) VALUES
    ('modules.wholesale', 'Module · Wholesale', 'view', 'Show Wholesale in the module switcher (requires company license).')
ON CONFLICT (name) DO NOTHING;

DO $$
DECLARE
    p RECORD;
    r RECORD;
BEGIN
    FOR p IN SELECT id FROM permissions WHERE name = 'modules.wholesale'
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
