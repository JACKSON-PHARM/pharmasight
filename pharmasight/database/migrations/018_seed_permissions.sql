-- Migration 018: Seed permissions for Vyapar-style matrix (module × action)
-- Format: module.action e.g. sales.view, sales.create

INSERT INTO permissions (name, module, action, description) VALUES
-- Sales
('sales.view_own', 'sales', 'view_own', 'View own sales only'),
('sales.view_all', 'sales', 'view_all', 'View all sales'),
('sales.view', 'Sales', 'view', 'View sales and invoices'),
('sales.create', 'Sales', 'create', 'Create sales invoices'),
('sales.edit', 'Sales', 'edit', 'Edit draft invoices'),
('sales.delete', 'Sales', 'delete', 'Delete draft invoices'),
('sales.sell_below_min_margin', 'sales', 'sell_below_min_margin', 'Allow selling below minimum margin'),
-- Purchases
('purchases.view', 'Purchases', 'view', 'View purchases'),
('purchases.create', 'Purchases', 'create', 'Create GRNs and purchase invoices'),
('purchases.edit', 'Purchases', 'edit', 'Edit purchase documents'),
('purchases.delete', 'Purchases', 'delete', 'Delete purchase documents'),
-- Inventory
('inventory.view', 'Inventory', 'view', 'View inventory and stock'),
('inventory.view_cost', 'inventory', 'view_cost', 'View unit cost and purchase prices'),
('inventory.create', 'Inventory', 'create', 'Add stock (receiving)'),
('inventory.edit', 'Inventory', 'edit', 'Adjust stock'),
('inventory.delete', 'Inventory', 'delete', 'Write-off stock'),
-- Reports
('reports.view', 'Reports', 'view', 'View reports'),
('reports.create', 'Reports', 'create', 'Generate reports'),
('reports.edit', 'Reports', 'edit', 'Edit report settings'),
('reports.delete', 'Reports', 'delete', 'Delete saved reports'),
-- Orders (Order Book)
('orders.view', 'Orders', 'view', 'View order book'),
('orders.create', 'Orders', 'create', 'Place orders'),
('orders.edit', 'Orders', 'edit', 'Edit orders'),
('orders.delete', 'Orders', 'delete', 'Cancel orders'),
-- Expenses
('expenses.view', 'Expenses', 'view', 'View expenses'),
('expenses.create', 'Expenses', 'create', 'Record expenses'),
('expenses.edit', 'Expenses', 'edit', 'Edit expenses'),
('expenses.delete', 'Expenses', 'delete', 'Delete expenses'),
-- Settings
('settings.view', 'Settings', 'view', 'View company and branch settings'),
('settings.create', 'Settings', 'create', 'Create branches'),
('settings.edit', 'Settings', 'edit', 'Edit company and branch settings'),
('settings.delete', 'Settings', 'delete', 'Delete branches'),
-- Users & Roles
('users.view', 'Users & Roles', 'view', 'View users and roles'),
('users.create', 'Users & Roles', 'create', 'Create users'),
('users.edit', 'Users & Roles', 'edit', 'Edit users and role permissions'),
('users.delete', 'Users & Roles', 'delete', 'Delete users'),
-- Dashboard (widget-level permissions)
('dashboard.view_items', 'dashboard', 'view_items', 'View items count card'),
('dashboard.view_inventory', 'dashboard', 'view_inventory', 'View inventory cards'),
('dashboard.view_stock_value', 'dashboard', 'view_stock_value', 'View stock value card'),
('dashboard.view_sales', 'dashboard', 'view_sales', 'View sales card'),
('dashboard.view_expiring', 'dashboard', 'view_expiring', 'View expiring items card'),
('dashboard.view_order_book', 'dashboard', 'view_order_book', 'View order book card'),
-- Items
('items.view', 'items', 'view', 'View items'),
('items.view_cost', 'items', 'view_cost', 'View item unit cost and purchase prices')
ON CONFLICT (name) DO NOTHING;
