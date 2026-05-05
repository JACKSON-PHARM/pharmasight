-- Customer portal: WhatsApp for upgrades/support (per company). Falls back to server default when NULL.
ALTER TABLE companies
    ADD COLUMN IF NOT EXISTS portal_upgrade_whatsapp VARCHAR(32) NULL;

COMMENT ON COLUMN companies.portal_upgrade_whatsapp IS 'Optional digits/local WhatsApp for marketing portal Contact button; wa.me uses normalized E.164';
