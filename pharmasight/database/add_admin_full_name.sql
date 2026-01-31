-- Add admin_full_name column to tenants table for username generation
ALTER TABLE tenants
ADD COLUMN IF NOT EXISTS admin_full_name VARCHAR(255);

COMMENT ON COLUMN tenants.admin_full_name IS 'Admin user full name for username generation (e.g., "Dr. Jackson" -> "D-JACKSON")';
