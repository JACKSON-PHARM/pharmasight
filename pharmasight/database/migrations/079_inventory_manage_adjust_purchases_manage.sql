-- Aggregate permissions used by pharmacy API enforcement (items/sales/inventory/purchase orders).
-- Backfill: grant to roles that already have overlapping capabilities so existing tenants keep access.

INSERT INTO permissions (name, module, action, description) VALUES
('inventory.manage', 'Inventory', 'manage', 'Manage item catalog and inventory records (create/update/delete items, branch stock views)'),
('inventory.adjust', 'Inventory', 'adjust', 'Adjust stock quantities (manual adjustments)'),
('purchases.manage', 'Purchases', 'manage', 'Create and update purchase orders')
ON CONFLICT (name) DO NOTHING;

-- inventory.manage: roles with item or inventory document permissions
INSERT INTO role_permissions (role_id, permission_id, branch_id)
SELECT DISTINCT rp.role_id, pm.id, NULL::uuid
FROM role_permissions rp
JOIN permissions p_old ON p_old.id = rp.permission_id
CROSS JOIN (SELECT id FROM permissions WHERE name = 'inventory.manage' LIMIT 1) pm(id)
WHERE p_old.name IN (
    'items.create', 'items.edit', 'items.delete',
    'inventory.create', 'inventory.edit', 'inventory.delete'
)
AND NOT EXISTS (
    SELECT 1 FROM role_permissions x
    WHERE x.role_id = rp.role_id
    AND x.permission_id = pm.id
    AND x.branch_id IS NULL
);

-- inventory.adjust: roles that could already adjust stock via inventory.edit
INSERT INTO role_permissions (role_id, permission_id, branch_id)
SELECT DISTINCT rp.role_id, pa.id, NULL::uuid
FROM role_permissions rp
JOIN permissions p_old ON p_old.id = rp.permission_id
CROSS JOIN (SELECT id FROM permissions WHERE name = 'inventory.adjust' LIMIT 1) pa(id)
WHERE p_old.name IN ('inventory.edit', 'inventory.create', 'inventory.delete')
AND NOT EXISTS (
    SELECT 1 FROM role_permissions x
    WHERE x.role_id = rp.role_id
    AND x.permission_id = pa.id
    AND x.branch_id IS NULL
);

-- purchases.manage: roles with any purchase write permission
INSERT INTO role_permissions (role_id, permission_id, branch_id)
SELECT DISTINCT rp.role_id, po.id, NULL::uuid
FROM role_permissions rp
JOIN permissions p_old ON p_old.id = rp.permission_id
CROSS JOIN (SELECT id FROM permissions WHERE name = 'purchases.manage' LIMIT 1) po(id)
WHERE p_old.name IN ('purchases.create', 'purchases.edit', 'purchases.delete')
AND NOT EXISTS (
    SELECT 1 FROM role_permissions x
    WHERE x.role_id = rp.role_id
    AND x.permission_id = po.id
    AND x.branch_id IS NULL
);
