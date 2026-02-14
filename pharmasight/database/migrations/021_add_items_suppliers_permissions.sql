-- Migration 021: Add Items and Suppliers permissions (HQ-only for create)
-- Items and Suppliers creation is restricted to HQ branch.

INSERT INTO permissions (name, module, action, description) VALUES
('items.view', 'Items', 'view', 'View items catalog'),
('items.create', 'Items', 'create', 'Create new items (HQ only)'),
('items.edit', 'Items', 'edit', 'Edit items'),
('items.delete', 'Items', 'delete', 'Delete items'),
('suppliers.view', 'Suppliers', 'view', 'View suppliers'),
('suppliers.create', 'Suppliers', 'create', 'Create suppliers (HQ only)'),
('suppliers.edit', 'Suppliers', 'edit', 'Edit suppliers'),
('suppliers.delete', 'Suppliers', 'delete', 'Delete suppliers')
ON CONFLICT (name) DO NOTHING;
