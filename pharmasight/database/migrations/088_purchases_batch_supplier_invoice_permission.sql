-- Post supplier invoice to inventory (batch / receive stock) — separate from draft edit (purchases.edit).
-- Backfill: grant to every role that already has purchases.edit so existing tenants keep current behavior.
-- Admins can then remove this permission from roles that may create/edit drafts but must not post stock.

INSERT INTO permissions (name, module, action, description) VALUES
(
    'purchases.batch_supplier_invoice',
    'Purchases',
    'batch_supplier_invoice',
    'Post supplier invoice to inventory (batch / receive stock)'
)
ON CONFLICT (name) DO NOTHING;

INSERT INTO role_permissions (role_id, permission_id, branch_id)
SELECT DISTINCT rp.role_id, p_new.id, NULL::uuid
FROM role_permissions rp
JOIN permissions p_old ON p_old.id = rp.permission_id
CROSS JOIN (SELECT id FROM permissions WHERE name = 'purchases.batch_supplier_invoice' LIMIT 1) p_new(id)
WHERE p_old.name = 'purchases.edit'
AND NOT EXISTS (
    SELECT 1 FROM role_permissions x
    WHERE x.role_id = rp.role_id
    AND x.permission_id = p_new.id
    AND x.branch_id IS NULL
);
