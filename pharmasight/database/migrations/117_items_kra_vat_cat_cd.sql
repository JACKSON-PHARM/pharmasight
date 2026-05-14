-- KRA selectItemList row may include vatCatCd alongside taxTyCd; persist for invoice snapshots / sendSales.
ALTER TABLE items ADD COLUMN IF NOT EXISTS kra_vat_cat_cd VARCHAR(20);
