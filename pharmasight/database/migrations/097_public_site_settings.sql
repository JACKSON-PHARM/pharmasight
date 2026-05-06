-- Public marketing site settings (single shared config row)
-- Platform-level (NOT per company): used by /marketing/* for contact details.

CREATE TABLE IF NOT EXISTS public_site_settings (
    id INTEGER PRIMARY KEY,
    support_email TEXT NULL,
    sales_email TEXT NULL,
    phone TEXT NULL,
    whatsapp TEXT NULL,
    address TEXT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT public_site_settings_singleton CHECK (id = 1)
);

-- Ensure singleton row exists
INSERT INTO public_site_settings (id)
SELECT 1
WHERE NOT EXISTS (SELECT 1 FROM public_site_settings WHERE id = 1);

