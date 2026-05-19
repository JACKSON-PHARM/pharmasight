-- Migration 145: Sanitize duplicate roles, seed modules.* permissions, apply canonical templates.
-- Merges "Super Admin" / "super admin" into super_admin; keeps platform_super_admin separate.

-- ---------------------------------------------------------------------------
-- 1) Module switcher permissions for all licenseable slugs
-- ---------------------------------------------------------------------------
INSERT INTO permissions (name, module, action, description) VALUES
    ('modules.pharmacy', 'Module · Pharmacy', 'view', 'Show Pharmacy in the module switcher.'),
    ('modules.inventory', 'Module · Inventory', 'view', 'Show Inventory in the module switcher.'),
    ('modules.finance', 'Module · Finance', 'view', 'Show Finance in the module switcher.'),
    ('modules.procurement', 'Module · Procurement', 'view', 'Show Procurement in the module switcher.'),
    ('modules.pos', 'Module · POS', 'view', 'Show POS in the module switcher.'),
    ('modules.billing', 'Module · Billing', 'view', 'Show Billing in the module switcher.'),
    ('modules.wholesale', 'Module · Wholesale', 'view', 'Show Wholesale in the module switcher.'),
    ('modules.clinic', 'Module · Clinic', 'view', 'Show Clinic in the module switcher.'),
    ('modules.patients', 'Module · Patients', 'view', 'Show Patients in the module switcher.'),
    ('modules.opd', 'Module · OPD', 'view', 'Show OPD / consultation in the module switcher.'),
    ('modules.prescriptions', 'Module · Prescriptions', 'view', 'Show Prescriptions in the module switcher.'),
    ('modules.lab', 'Module · Lab', 'view', 'Show Lab in the module switcher.'),
    ('modules.radiology', 'Module · Radiology', 'view', 'Show Radiology in the module switcher.'),
    ('modules.ipd', 'Module · IPD', 'view', 'Show IPD in the module switcher.'),
    ('modules.emr', 'Module · EMR', 'view', 'Show EMR in the module switcher.'),
    ('modules.management', 'Module · Management', 'view', 'Show Management in the module switcher.')
ON CONFLICT (name) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 2) Merge duplicate super-admin roles into super_admin
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    keeper_id UUID;
    loser RECORD;
    norm TEXT;
BEGIN
    -- Pick keeper: most assignments, prefer slug super_admin
    SELECT ur.id INTO keeper_id
    FROM user_roles ur
    LEFT JOIN (
        SELECT role_id, COUNT(*) AS c FROM user_branch_roles GROUP BY role_id
    ) u ON u.role_id = ur.id
    WHERE lower(replace(trim(ur.role_name), ' ', '_')) IN ('super_admin', 'superadmin')
       OR lower(trim(ur.role_name)) IN ('super admin', 'super admin')
       OR trim(ur.role_name) = 'Super Admin'
    ORDER BY u.c DESC NULLS LAST,
             CASE WHEN lower(replace(trim(ur.role_name), ' ', '_')) = 'super_admin' THEN 0 ELSE 1 END
    LIMIT 1;

    IF keeper_id IS NULL THEN
        INSERT INTO user_roles (role_name, description)
        VALUES (
            'super_admin',
            'Full access: all modules and all actions (create, edit, delete).'
        )
        ON CONFLICT (role_name) DO NOTHING
        RETURNING id INTO keeper_id;
        IF keeper_id IS NULL THEN
            SELECT id INTO keeper_id FROM user_roles WHERE role_name = 'super_admin' LIMIT 1;
        END IF;
    END IF;

    FOR loser IN
        SELECT ur.id
        FROM user_roles ur
        WHERE (
            lower(replace(trim(ur.role_name), ' ', '_')) IN ('super_admin', 'superadmin')
            OR lower(trim(ur.role_name)) IN ('super admin', 'super admin')
            OR trim(ur.role_name) = 'Super Admin'
        )
        AND ur.id <> keeper_id
    LOOP
        UPDATE user_branch_roles ubr
        SET role_id = keeper_id
        WHERE ubr.role_id = loser.id
          AND NOT EXISTS (
              SELECT 1 FROM user_branch_roles x
              WHERE x.user_id = ubr.user_id AND x.branch_id = ubr.branch_id AND x.role_id = keeper_id
          );
        DELETE FROM user_branch_roles WHERE role_id = loser.id;
        DELETE FROM role_permissions WHERE role_id = loser.id;
        DELETE FROM user_roles WHERE id = loser.id;
    END LOOP;

    UPDATE user_roles
    SET role_name = 'super_admin',
        description = 'Full access: all modules and all actions (create, edit, delete).'
    WHERE id = keeper_id;
END $$;

-- Normalize admin description
UPDATE user_roles
SET description = 'All modules; can view and update but not create new records.'
WHERE lower(trim(role_name)) = 'admin';

-- Ensure platform_super_admin description is clear
UPDATE user_roles
SET description = 'SightOps internal — cross-company platform console (not for company staff).'
WHERE lower(trim(role_name)) = 'platform_super_admin';

-- ---------------------------------------------------------------------------
-- 3) Re-apply super_admin + admin permission templates (global role_permissions)
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    p RECORD;
    super_id UUID;
    admin_id UUID;
BEGIN
    SELECT id INTO super_id FROM user_roles WHERE role_name = 'super_admin' LIMIT 1;
    SELECT id INTO admin_id FROM user_roles WHERE role_name = 'admin' LIMIT 1;

    IF super_id IS NOT NULL THEN
        DELETE FROM role_permissions WHERE role_id = super_id AND branch_id IS NULL;
        FOR p IN SELECT id FROM permissions
        LOOP
            INSERT INTO role_permissions (role_id, permission_id, branch_id)
            SELECT super_id, p.id, NULL
            WHERE NOT EXISTS (
                SELECT 1 FROM role_permissions rp
                WHERE rp.role_id = super_id AND rp.permission_id = p.id AND rp.branch_id IS NULL
            );
        END LOOP;
    END IF;

    IF admin_id IS NOT NULL THEN
        DELETE FROM role_permissions WHERE role_id = admin_id AND branch_id IS NULL;
        FOR p IN SELECT id, name, action FROM permissions
        LOOP
            IF p.name LIKE 'modules.%' THEN
                INSERT INTO role_permissions (role_id, permission_id, branch_id)
                VALUES (admin_id, p.id, NULL)
                ON CONFLICT DO NOTHING;
                CONTINUE;
            END IF;
            IF p.action = 'create' OR p.name LIKE '%.create' THEN
                CONTINUE;
            END IF;
            INSERT INTO role_permissions (role_id, permission_id, branch_id)
            SELECT admin_id, p.id, NULL
            WHERE NOT EXISTS (
                SELECT 1 FROM role_permissions rp
                WHERE rp.role_id = admin_id AND rp.permission_id = p.id AND rp.branch_id IS NULL
            );
        END LOOP;
    END IF;
END $$;
