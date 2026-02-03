-- Add default cost and default supplier to items (used only when no inventory_ledger history)
-- Phase 2: Default parameters for items with no transaction history

ALTER TABLE public.items
  ADD COLUMN IF NOT EXISTS default_cost_per_base numeric(20, 4) NULL,
  ADD COLUMN IF NOT EXISTS default_supplier_id uuid NULL REFERENCES suppliers(id) ON DELETE SET NULL;

COMMENT ON COLUMN public.items.default_cost_per_base IS 'Default cost per base (wholesale) unit; used only when item has no inventory_ledger records.';
COMMENT ON COLUMN public.items.default_supplier_id IS 'Default supplier; used only when item has no purchase history.';

CREATE INDEX IF NOT EXISTS idx_items_default_supplier ON public.items (default_supplier_id)
  WHERE default_supplier_id IS NOT NULL;
