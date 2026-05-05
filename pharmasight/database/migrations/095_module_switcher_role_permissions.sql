-- Row-level control over top-bar module switcher pills (UI visibility).
-- Still intersected with company licensing in GET /api/modules/me.

INSERT INTO permissions (name, module, action, description) VALUES
    ('modules.pharmacy', 'Module · Pharmacy', 'view', 'Show Pharmacy in the module switcher (requires company license).'),
    ('modules.clinic', 'Module · Clinic', 'view', 'Show Clinic in the module switcher (requires company license).'),
    ('modules.lab', 'Module · Lab', 'view', 'Show Lab in the module switcher (requires company license).'),
    ('modules.billing', 'Module · Billing', 'view', 'Show Billing in the module switcher (requires company license).'),
    ('modules.finance', 'Module · Finance', 'view', 'Show Finance in the module switcher (requires company license).'),
    ('modules.management', 'Module · Management', 'view', 'Show Management in the module switcher.')
ON CONFLICT (name) DO NOTHING;

-- Grant new module-switcher permissions to company-admin-style roles (matches typical expectations).
DO $$
DECLARE
    p RECORD;
    r RECORD;
BEGIN
    FOR p IN SELECT id FROM permissions WHERE name LIKE 'modules.%'
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
