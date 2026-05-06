-- Warn-only sustainable margin tracking
-- Logs sale lines whose margin (vs reference list cost) is below a company-wide threshold.

CREATE TABLE IF NOT EXISTS below_margin_sales_lines (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    sales_invoice_id UUID NOT NULL REFERENCES sales_invoices(id) ON DELETE CASCADE,
    sales_invoice_item_id UUID NOT NULL REFERENCES sales_invoice_items(id) ON DELETE CASCADE,
    invoice_no VARCHAR(100) NOT NULL,
    invoice_date DATE NOT NULL,
    payment_mode VARCHAR(50) NULL,
    customer_name VARCHAR(255) NULL,

    item_id UUID NOT NULL REFERENCES items(id),
    item_name VARCHAR(255) NULL,
    unit_name VARCHAR(50) NOT NULL,
    quantity_sale_unit NUMERIC(20,4) NOT NULL,
    quantity_base_unit NUMERIC(20,4) NOT NULL,
    unit_price_exclusive NUMERIC(20,4) NOT NULL,

    reference_unit_cost_base NUMERIC(20,4) NULL,
    sustainable_min_margin_pct NUMERIC(10,2) NOT NULL,
    computed_margin_pct NUMERIC(10,2) NULL,

    created_by UUID NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_below_margin_sales_lines_branch_date
    ON below_margin_sales_lines(branch_id, invoice_date);

CREATE INDEX IF NOT EXISTS ix_below_margin_sales_lines_invoice
    ON below_margin_sales_lines(sales_invoice_id);

CREATE INDEX IF NOT EXISTS ix_below_margin_sales_lines_item
    ON below_margin_sales_lines(item_id);

