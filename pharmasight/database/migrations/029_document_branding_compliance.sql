-- Document branding and compliance: users (signature, PPB, designation), purchase_orders (approval, pdf_path, is_official)
-- Multi-tenant: asset paths stored only (e.g. tenant-assets/{tenant_id}/...); no image binaries in DB.

-- Users: signature and PPB/compliance fields
ALTER TABLE users ADD COLUMN IF NOT EXISTS signature_path TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS ppb_number TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS designation TEXT;
COMMENT ON COLUMN users.signature_path IS 'Path in Supabase storage: tenant-assets/{tenant_id}/users/{user_id}/signature.png';
COMMENT ON COLUMN users.ppb_number IS 'Pharmacists and Poisons Board registration number (Kenyan compliance)';
COMMENT ON COLUMN users.designation IS 'Job title e.g. Superintendent Pharmacist';

-- Purchase orders: approval workflow and immutable PDF
ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS approved_by_user_id UUID REFERENCES users(id);
ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ;
ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS is_official BOOLEAN DEFAULT true;
ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS pdf_path TEXT;
COMMENT ON COLUMN purchase_orders.approved_by_user_id IS 'User who approved the PO (set when status becomes APPROVED)';
COMMENT ON COLUMN purchase_orders.approved_at IS 'When the PO was approved';
COMMENT ON COLUMN purchase_orders.is_official IS 'If true, apply stamp/signature rules for official PO';
COMMENT ON COLUMN purchase_orders.pdf_path IS 'Path in Supabase storage: tenant-assets/{tenant_id}/documents/purchase_orders/{po_id}.pdf';
