-- Department mini-stores within a branch (triage, inpatient, consultation, lab...)
-- Stock is issued from branch pharmacy and consumed at department level.

CREATE TABLE IF NOT EXISTS department_stores (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_by UUID NULL REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_department_store_company_branch_code UNIQUE (company_id, branch_id, code)
);

CREATE INDEX IF NOT EXISTS ix_department_stores_company_branch ON department_stores(company_id, branch_id);

CREATE TABLE IF NOT EXISTS department_store_stock (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    store_id UUID NOT NULL REFERENCES department_stores(id) ON DELETE CASCADE,
    item_id UUID NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    quantity_base NUMERIC(20,4) NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_department_store_stock_store_item UNIQUE (store_id, item_id)
);

CREATE INDEX IF NOT EXISTS ix_department_store_stock_store ON department_store_stock(store_id);
CREATE INDEX IF NOT EXISTS ix_department_store_stock_item ON department_store_stock(item_id);

CREATE TABLE IF NOT EXISTS department_store_movements (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    store_id UUID NOT NULL REFERENCES department_stores(id) ON DELETE CASCADE,
    item_id UUID NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    movement_type VARCHAR(30) NOT NULL,
    quantity_delta_base NUMERIC(20,4) NOT NULL,
    reference_type TEXT NULL,
    reference_id UUID NULL,
    notes TEXT NULL,
    created_by UUID NULL REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_department_store_movement_delta_not_zero CHECK (quantity_delta_base != 0),
    CONSTRAINT ck_department_store_movement_type CHECK (movement_type IN ('ISSUE_IN','CONSUME_OUT','ADJUSTMENT','RECONCILE','RETURN_TO_PHARMACY'))
);

CREATE INDEX IF NOT EXISTS ix_department_store_movements_store_item ON department_store_movements(store_id, item_id, created_at DESC);
