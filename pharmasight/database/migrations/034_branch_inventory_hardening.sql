-- Migration 034: Branch Inventory hardening (constraints, self-transfer prevention, status control)
-- Does NOT modify purchase, sales, costing, or inventory_ledger.

-- 1) quantity != 0 on branch_transfer_lines and branch_receipt_lines
ALTER TABLE branch_transfer_lines
  ADD CONSTRAINT chk_branch_transfer_lines_quantity_not_zero CHECK (quantity != 0);

ALTER TABLE branch_receipt_lines
  ADD CONSTRAINT chk_branch_receipt_lines_quantity_not_zero CHECK (quantity != 0);

-- 2) Prevent self-transfer: ordering_branch_id != supplying_branch_id (branch_orders)
ALTER TABLE branch_orders
  ADD CONSTRAINT chk_branch_orders_no_self_order CHECK (ordering_branch_id != supplying_branch_id);

-- Prevent self-transfer on branch_transfers
ALTER TABLE branch_transfers
  ADD CONSTRAINT chk_branch_transfers_no_self_transfer CHECK (supplying_branch_id != receiving_branch_id);

-- 3) Controlled status (branch_orders: DRAFT, BATCHED)
ALTER TABLE branch_orders
  ADD CONSTRAINT chk_branch_orders_status CHECK (status IN ('DRAFT', 'BATCHED'));

-- 4) Controlled status (branch_transfers: DRAFT, COMPLETED)
ALTER TABLE branch_transfers
  ADD CONSTRAINT chk_branch_transfers_status CHECK (status IN ('DRAFT', 'COMPLETED'));

-- 5) Controlled status (branch_receipts: PENDING, RECEIVED)
ALTER TABLE branch_receipts
  ADD CONSTRAINT chk_branch_receipts_status CHECK (status IN ('PENDING', 'RECEIVED'));

-- 6) Request audit: preserve requested quantities when replacing transfer lines on complete
ALTER TABLE branch_transfers
  ADD COLUMN IF NOT EXISTS request_audit JSONB;

COMMENT ON COLUMN branch_transfers.request_audit IS 'Snapshot of requested (item_id, quantity_base) before FEFO line replacement; audit trail.';
