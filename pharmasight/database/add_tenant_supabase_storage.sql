-- Add per-tenant Supabase Storage credentials (master DB).
-- When set, storage (logos, stamps, PO PDFs, signed URLs) uses this tenant's Supabase project
-- instead of the global SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY.
-- Leave NULL to use the single shared storage (tenant-assets bucket on master project).

ALTER TABLE tenants
    ADD COLUMN IF NOT EXISTS supabase_storage_url TEXT,
    ADD COLUMN IF NOT EXISTS supabase_storage_service_role_key TEXT;

COMMENT ON COLUMN tenants.supabase_storage_url IS 'Optional: Supabase project URL for this tenant''s storage. When set, logos/PDFs/signed URLs use this project.';
COMMENT ON COLUMN tenants.supabase_storage_service_role_key IS 'Optional: Service role key for tenant''s Supabase storage. Store securely; consider encryption at rest.';
