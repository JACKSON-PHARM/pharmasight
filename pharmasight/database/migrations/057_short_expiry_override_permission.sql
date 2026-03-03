-- Migration 057: Short expiry override permission
-- Allows Manager/Pharmacist to accept batches with expiry within min_expiry_days when batching supplier invoices.
-- Assign this permission to Manager and Pharmacist roles so they can use "Override & Batch" in the UI.

INSERT INTO permissions (name, module, action, description) VALUES
('inventory.short_expiry_override', 'inventory', 'short_expiry_override', 'Accept short-expiry batches when batching supplier invoices (e.g. Manager or Pharmacist)')
ON CONFLICT (name) DO NOTHING;
