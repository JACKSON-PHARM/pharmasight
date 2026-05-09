-- Company-scoped shared clinical services catalog
-- Available across all branches of the same company.

CREATE TABLE IF NOT EXISTS clinical_services (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    code TEXT NULL,
    department TEXT NULL,
    allowed_departments JSONB NULL,
    strict_department_only BOOLEAN NOT NULL DEFAULT FALSE,
    description TEXT NULL,
    fee NUMERIC(20,4) NOT NULL DEFAULT 0,
    billing_item_id UUID NULL REFERENCES items(id) ON DELETE SET NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_by UUID NULL REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_clinical_services_company_id ON clinical_services(company_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_clinical_services_company_name_ci ON clinical_services(company_id, lower(name));
CREATE UNIQUE INDEX IF NOT EXISTS uq_clinical_services_company_code_ci
    ON clinical_services(company_id, lower(code))
    WHERE code IS NOT NULL AND length(trim(code)) > 0;

CREATE TABLE IF NOT EXISTS clinical_service_components (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    service_id UUID NOT NULL REFERENCES clinical_services(id) ON DELETE CASCADE,
    item_id UUID NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    item_unit_name TEXT NULL,
    quantity_per_service NUMERIC(20,4) NOT NULL DEFAULT 1,
    is_optional BOOLEAN NOT NULL DEFAULT FALSE,
    deduction_policy VARCHAR(20) NOT NULL DEFAULT 'immediate',
    accumulator_threshold_qty NUMERIC(20,4) NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    notes TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_service_component_qty_positive CHECK (quantity_per_service > 0),
    CONSTRAINT ck_service_component_policy CHECK (deduction_policy IN ('immediate','accumulator')),
    CONSTRAINT ck_service_component_threshold_positive CHECK (accumulator_threshold_qty IS NULL OR accumulator_threshold_qty > 0),
    CONSTRAINT uq_service_component_service_item UNIQUE (service_id, item_id)
);

CREATE INDEX IF NOT EXISTS ix_service_components_service_id ON clinical_service_components(service_id);
CREATE INDEX IF NOT EXISTS ix_service_components_item_id ON clinical_service_components(item_id);

CREATE TABLE IF NOT EXISTS clinical_service_accumulators (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    service_component_id UUID NOT NULL REFERENCES clinical_service_components(id) ON DELETE CASCADE,
    accumulated_qty_base NUMERIC(20,4) NOT NULL DEFAULT 0,
    last_deducted_at TIMESTAMPTZ NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_service_accumulator_company_branch_component UNIQUE (company_id, branch_id, service_component_id)
);

CREATE INDEX IF NOT EXISTS ix_service_acc_company_branch ON clinical_service_accumulators(company_id, branch_id);

CREATE TABLE IF NOT EXISTS encounter_service_executions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    encounter_id UUID NOT NULL REFERENCES encounters(id) ON DELETE CASCADE,
    service_id UUID NOT NULL REFERENCES clinical_services(id) ON DELETE CASCADE,
    quantity NUMERIC(20,4) NOT NULL DEFAULT 1,
    billed_amount NUMERIC(20,4) NOT NULL DEFAULT 0,
    notes TEXT NULL,
    performed_by UUID NULL REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_service_execution_qty_positive CHECK (quantity > 0)
);

CREATE INDEX IF NOT EXISTS ix_service_exec_company_branch ON encounter_service_executions(company_id, branch_id);
CREATE INDEX IF NOT EXISTS ix_service_exec_encounter ON encounter_service_executions(encounter_id);

CREATE TABLE IF NOT EXISTS encounter_service_execution_lines (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    execution_id UUID NOT NULL REFERENCES encounter_service_executions(id) ON DELETE CASCADE,
    service_component_id UUID NULL REFERENCES clinical_service_components(id) ON DELETE SET NULL,
    item_id UUID NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    policy VARCHAR(20) NOT NULL DEFAULT 'immediate',
    selected BOOLEAN NOT NULL DEFAULT TRUE,
    requested_qty NUMERIC(20,4) NOT NULL DEFAULT 0,
    deducted_qty NUMERIC(20,4) NOT NULL DEFAULT 0,
    item_unit_name TEXT NULL,
    requested_qty_base NUMERIC(20,4) NOT NULL DEFAULT 0,
    deducted_qty_base NUMERIC(20,4) NOT NULL DEFAULT 0,
    accumulator_before_base NUMERIC(20,4) NULL,
    accumulator_after_base NUMERIC(20,4) NULL,
    CONSTRAINT ck_service_exec_line_policy CHECK (policy IN ('immediate','accumulator'))
);

CREATE INDEX IF NOT EXISTS ix_service_exec_lines_execution ON encounter_service_execution_lines(execution_id);
CREATE INDEX IF NOT EXISTS ix_service_exec_lines_item ON encounter_service_execution_lines(item_id);
