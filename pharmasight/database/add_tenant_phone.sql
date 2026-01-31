-- Add phone number column to tenants table
ALTER TABLE tenants
ADD COLUMN IF NOT EXISTS phone VARCHAR(50);

CREATE INDEX IF NOT EXISTS idx_tenants_phone ON tenants(phone);

COMMENT ON COLUMN tenants.phone IS 'Contact phone number for the tenant';
