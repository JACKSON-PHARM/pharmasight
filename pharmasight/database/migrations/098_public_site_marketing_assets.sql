-- Marketing assets URLs for public site (singleton public_site_settings row).
-- Binary files live in Supabase Storage bucket `marketing-public`; DB stores public HTTPS URLs.

ALTER TABLE public_site_settings
    ADD COLUMN IF NOT EXISTS logo_url TEXT NULL,
    ADD COLUMN IF NOT EXISTS marketing_images JSONB NOT NULL DEFAULT '{}'::jsonb;
