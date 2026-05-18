-- Migration 134: Backfill finance permissions onto existing roles (E1 compatibility)
-- Super Admin / admin / owner: all finance permissions (global).
-- Legacy reports.view holders: operational cashbook branch view (not executive/reconcile by default).
-- Legacy customers.* / sales.* mappings for wholesale and hospital namespaces.

-- 1) Grant all new finance permissions to platform admin roles (global branch_id NULL)
DO $$
DECLARE
    p RECORD;
    r RECORD;
BEGIN
    FOR r IN SELECT id FROM user_roles WHERE lower(trim(role_name)) IN ('super admin', 'admin', 'owner', 'platform admin')
    LOOP
        FOR p IN SELECT id FROM permissions WHERE name LIKE 'finance.%' OR name LIKE 'wholesale.ar.%' OR name LIKE 'hospital.%' OR name LIKE 'retail.till.%'
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

-- 2) reports.view -> finance.cashbook.view_branch + finance.reports.operational (+ management for pharmacist/admin-like)
DO $$
DECLARE
    perm_reports UUID;
    perm_cashbook_branch UUID;
    perm_operational UUID;
    perm_management UUID;
    r RECORD;
BEGIN
    SELECT id INTO perm_reports FROM permissions WHERE name = 'reports.view' LIMIT 1;
    SELECT id INTO perm_cashbook_branch FROM permissions WHERE name = 'finance.cashbook.view_branch' LIMIT 1;
    SELECT id INTO perm_operational FROM permissions WHERE name = 'finance.reports.operational' LIMIT 1;
    SELECT id INTO perm_management FROM permissions WHERE name = 'finance.reports.management' LIMIT 1;

    IF perm_reports IS NULL THEN
        RETURN;
    END IF;

    FOR r IN
        SELECT DISTINCT rp.role_id
        FROM role_permissions rp
        WHERE rp.permission_id = perm_reports AND rp.branch_id IS NULL
    LOOP
        IF perm_cashbook_branch IS NOT NULL THEN
            INSERT INTO role_permissions (role_id, permission_id, branch_id)
            SELECT r.role_id, perm_cashbook_branch, NULL
            WHERE NOT EXISTS (
                SELECT 1 FROM role_permissions x
                WHERE x.role_id = r.role_id AND x.permission_id = perm_cashbook_branch AND x.branch_id IS NULL
            );
        END IF;
        IF perm_operational IS NOT NULL THEN
            INSERT INTO role_permissions (role_id, permission_id, branch_id)
            SELECT r.role_id, perm_operational, NULL
            WHERE NOT EXISTS (
                SELECT 1 FROM role_permissions x
                WHERE x.role_id = r.role_id AND x.permission_id = perm_operational AND x.branch_id IS NULL
            );
        END IF;
        -- pharmacist / admin / viewer with reports: management reports (P&L) — not cashier
        IF perm_management IS NOT NULL THEN
            INSERT INTO role_permissions (role_id, permission_id, branch_id)
            SELECT r.role_id, perm_management, NULL
            FROM user_roles ur
            WHERE ur.id = r.role_id
              AND lower(trim(ur.role_name)) IN ('pharmacist', 'admin', 'viewer', 'procurement', 'super admin')
              AND NOT EXISTS (
                SELECT 1 FROM role_permissions x
                WHERE x.role_id = r.role_id AND x.permission_id = perm_management AND x.branch_id IS NULL
            );
        END IF;
    END LOOP;
END $$;

-- 3) settings.edit -> finance.cashbook.reconcile_branch + retail.till.reconcile (administrative finance ops)
DO $$
DECLARE
    perm_settings UUID;
    perm_reconcile UUID;
    perm_till_recon UUID;
    r RECORD;
BEGIN
    SELECT id INTO perm_settings FROM permissions WHERE name = 'settings.edit' LIMIT 1;
    SELECT id INTO perm_reconcile FROM permissions WHERE name = 'finance.cashbook.reconcile_branch' LIMIT 1;
    SELECT id INTO perm_till_recon FROM permissions WHERE name = 'retail.till.reconcile' LIMIT 1;
    IF perm_settings IS NULL THEN
        RETURN;
    END IF;
    FOR r IN SELECT DISTINCT role_id FROM role_permissions WHERE permission_id = perm_settings AND branch_id IS NULL
    LOOP
        IF perm_reconcile IS NOT NULL THEN
            INSERT INTO role_permissions (role_id, permission_id, branch_id)
            SELECT r.role_id, perm_reconcile, NULL
            WHERE NOT EXISTS (
                SELECT 1 FROM role_permissions x
                WHERE x.role_id = r.role_id AND x.permission_id = perm_reconcile AND x.branch_id IS NULL
            );
        END IF;
        IF perm_till_recon IS NOT NULL THEN
            INSERT INTO role_permissions (role_id, permission_id, branch_id)
            SELECT r.role_id, perm_till_recon, NULL
            WHERE NOT EXISTS (
                SELECT 1 FROM role_permissions x
                WHERE x.role_id = r.role_id AND x.permission_id = perm_till_recon AND x.branch_id IS NULL
            );
        END IF;
    END LOOP;
END $$;

-- 4) customers.* -> wholesale.ar.* (preserve wholesale finance access)
DO $$
DECLARE
    mapping RECORD;
    r RECORD;
BEGIN
    FOR mapping IN
        SELECT * FROM (VALUES
            ('customers.view', 'wholesale.ar.view'),
            ('customers.record_payment', 'wholesale.ar.collect'),
            ('customers.manage_credit', 'wholesale.ar.credit_control')
        ) AS t(legacy_name, finance_name)
    LOOP
        FOR r IN
            SELECT DISTINCT rp.role_id
            FROM role_permissions rp
            JOIN permissions p ON p.id = rp.permission_id
            WHERE p.name = mapping.legacy_name AND rp.branch_id IS NULL
        LOOP
            INSERT INTO role_permissions (role_id, permission_id, branch_id)
            SELECT r.role_id, p_new.id, NULL
            FROM permissions p_new
            WHERE p_new.name = mapping.finance_name
              AND NOT EXISTS (
                SELECT 1 FROM role_permissions x
                WHERE x.role_id = r.role_id AND x.permission_id = p_new.id AND x.branch_id IS NULL
            );
        END LOOP;
    END LOOP;
END $$;

-- 5) sales.view / sales.edit / sales.create -> hospital.insurance + hospital.billing (compat for clinic finance APIs)
DO $$
DECLARE
    r RECORD;
    p_view UUID;
    p_settle UUID;
    p_providers UUID;
    p_bill_view UUID;
    p_bill_create UUID;
    p_bill_adjust UUID;
BEGIN
    SELECT id INTO p_view FROM permissions WHERE name = 'hospital.insurance.view' LIMIT 1;
    SELECT id INTO p_settle FROM permissions WHERE name = 'hospital.insurance.settle' LIMIT 1;
    SELECT id INTO p_providers FROM permissions WHERE name = 'hospital.insurance.manage_providers' LIMIT 1;
    SELECT id INTO p_bill_view FROM permissions WHERE name = 'hospital.billing.view' LIMIT 1;
    SELECT id INTO p_bill_create FROM permissions WHERE name = 'hospital.billing.create' LIMIT 1;
    SELECT id INTO p_bill_adjust FROM permissions WHERE name = 'hospital.billing.adjust' LIMIT 1;

    FOR r IN
        SELECT DISTINCT rp.role_id
        FROM role_permissions rp
        JOIN permissions p ON p.id = rp.permission_id
        WHERE p.name = 'sales.view' AND rp.branch_id IS NULL
    LOOP
        IF p_view IS NOT NULL THEN
            INSERT INTO role_permissions (role_id, permission_id, branch_id)
            SELECT r.role_id, p_view, NULL
            WHERE NOT EXISTS (SELECT 1 FROM role_permissions x WHERE x.role_id = r.role_id AND x.permission_id = p_view AND x.branch_id IS NULL);
        END IF;
        IF p_bill_view IS NOT NULL THEN
            INSERT INTO role_permissions (role_id, permission_id, branch_id)
            SELECT r.role_id, p_bill_view, NULL
            WHERE NOT EXISTS (SELECT 1 FROM role_permissions x WHERE x.role_id = r.role_id AND x.permission_id = p_bill_view AND x.branch_id IS NULL);
        END IF;
    END LOOP;

    FOR r IN
        SELECT DISTINCT rp.role_id
        FROM role_permissions rp
        JOIN permissions p ON p.id = rp.permission_id
        WHERE p.name = 'sales.edit' AND rp.branch_id IS NULL
    LOOP
        IF p_settle IS NOT NULL THEN
            INSERT INTO role_permissions (role_id, permission_id, branch_id)
            SELECT r.role_id, p_settle, NULL
            WHERE NOT EXISTS (SELECT 1 FROM role_permissions x WHERE x.role_id = r.role_id AND x.permission_id = p_settle AND x.branch_id IS NULL);
        END IF;
        IF p_bill_adjust IS NOT NULL THEN
            INSERT INTO role_permissions (role_id, permission_id, branch_id)
            SELECT r.role_id, p_bill_adjust, NULL
            WHERE NOT EXISTS (SELECT 1 FROM role_permissions x WHERE x.role_id = r.role_id AND x.permission_id = p_bill_adjust AND x.branch_id IS NULL);
        END IF;
    END LOOP;

    FOR r IN
        SELECT DISTINCT rp.role_id
        FROM role_permissions rp
        JOIN permissions p ON p.id = rp.permission_id
        WHERE p.name = 'sales.create' AND rp.branch_id IS NULL
    LOOP
        IF p_bill_create IS NOT NULL THEN
            INSERT INTO role_permissions (role_id, permission_id, branch_id)
            SELECT r.role_id, p_bill_create, NULL
            WHERE NOT EXISTS (SELECT 1 FROM role_permissions x WHERE x.role_id = r.role_id AND x.permission_id = p_bill_create AND x.branch_id IS NULL);
        END IF;
    END LOOP;
END $$;

-- 6) sales.create -> retail.till.operate for cashier/pharmacist roles
DO $$
DECLARE
    perm_create UUID;
    perm_till UUID;
    r RECORD;
BEGIN
    SELECT id INTO perm_create FROM permissions WHERE name = 'sales.create' LIMIT 1;
    SELECT id INTO perm_till FROM permissions WHERE name = 'retail.till.operate' LIMIT 1;
    IF perm_create IS NULL OR perm_till IS NULL THEN
        RETURN;
    END IF;
    FOR r IN SELECT DISTINCT role_id FROM role_permissions WHERE permission_id = perm_create AND branch_id IS NULL
    LOOP
        INSERT INTO role_permissions (role_id, permission_id, branch_id)
        SELECT r.role_id, perm_till, NULL
        WHERE NOT EXISTS (
            SELECT 1 FROM role_permissions x
            WHERE x.role_id = r.role_id AND x.permission_id = perm_till AND x.branch_id IS NULL
        );
    END LOOP;
END $$;

-- 7) settings.edit -> hospital.insurance.manage_providers (provider master)
DO $$
DECLARE
    perm_settings UUID;
    perm_providers UUID;
    r RECORD;
BEGIN
    SELECT id INTO perm_settings FROM permissions WHERE name = 'settings.edit' LIMIT 1;
    SELECT id INTO perm_providers FROM permissions WHERE name = 'hospital.insurance.manage_providers' LIMIT 1;
    IF perm_settings IS NULL OR perm_providers IS NULL THEN
        RETURN;
    END IF;
    FOR r IN SELECT DISTINCT role_id FROM role_permissions WHERE permission_id = perm_settings AND branch_id IS NULL
    LOOP
        INSERT INTO role_permissions (role_id, permission_id, branch_id)
        SELECT r.role_id, perm_providers, NULL
        WHERE NOT EXISTS (
            SELECT 1 FROM role_permissions x
            WHERE x.role_id = r.role_id AND x.permission_id = perm_providers AND x.branch_id IS NULL
        );
    END LOOP;
END $$;
