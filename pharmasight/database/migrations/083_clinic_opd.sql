-- OPD / Clinic foundation: patients, encounters, notes, clinic orders (single shared DB, company_id scoped).

-- Patients
CREATE TABLE IF NOT EXISTS patients (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    first_name TEXT NOT NULL DEFAULT '',
    last_name TEXT NOT NULL DEFAULT '',
    phone TEXT,
    gender TEXT,
    date_of_birth DATE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_patients_company_id ON patients(company_id);

-- Encounters (visits): link to draft billing via sales_invoice_id after invoice is created
CREATE TABLE IF NOT EXISTS encounters (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    patient_id UUID NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    status VARCHAR(30) NOT NULL DEFAULT 'waiting'
        CHECK (status IN ('waiting', 'in_consultation', 'completed')),
    sales_invoice_id UUID NULL REFERENCES sales_invoices(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    closed_at TIMESTAMPTZ NULL
);
CREATE INDEX IF NOT EXISTS ix_encounters_company_id ON encounters(company_id);
CREATE INDEX IF NOT EXISTS ix_encounters_branch_id ON encounters(branch_id);
CREATE INDEX IF NOT EXISTS ix_encounters_patient_id ON encounters(patient_id);
CREATE INDEX IF NOT EXISTS ix_encounters_status ON encounters(company_id, status);

-- Clinical notes per encounter
CREATE TABLE IF NOT EXISTS encounter_notes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    encounter_id UUID NOT NULL REFERENCES encounters(id) ON DELETE CASCADE,
    notes TEXT,
    diagnosis TEXT,
    created_by UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_encounter_notes_encounter_id ON encounter_notes(encounter_id);

-- Clinic orders (prescription / lab / procedure) — not purchase orders
CREATE TABLE IF NOT EXISTS clinic_orders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    encounter_id UUID NOT NULL REFERENCES encounters(id) ON DELETE CASCADE,
    order_type VARCHAR(30) NOT NULL
        CHECK (order_type IN ('prescription', 'lab', 'procedure')),
    status VARCHAR(30) NOT NULL DEFAULT 'requested'
        CHECK (status IN ('requested', 'in_progress', 'completed')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_clinic_orders_company_id ON clinic_orders(company_id);
CREATE INDEX IF NOT EXISTS ix_clinic_orders_encounter_id ON clinic_orders(encounter_id);

CREATE TABLE IF NOT EXISTS clinic_order_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id UUID NOT NULL REFERENCES clinic_orders(id) ON DELETE CASCADE,
    reference_type VARCHAR(20) NOT NULL
        CHECK (reference_type IN ('item', 'service')),
    reference_id UUID NOT NULL,
    quantity NUMERIC(20, 4) NOT NULL DEFAULT 1,
    notes TEXT
);
CREATE INDEX IF NOT EXISTS ix_clinic_order_items_order_id ON clinic_order_items(order_id);

-- Link sales invoices to encounters (nullable; one invoice per encounter when billed via OPD)
ALTER TABLE sales_invoices
    ADD COLUMN IF NOT EXISTS encounter_id UUID NULL REFERENCES encounters(id) ON DELETE SET NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_sales_invoices_encounter_id
    ON sales_invoices(encounter_id)
    WHERE encounter_id IS NOT NULL;
