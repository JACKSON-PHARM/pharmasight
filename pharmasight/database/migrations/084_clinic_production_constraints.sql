-- Production OPD: one non-completed encounter per patient per company; encounter audit column.

-- Fail fast if duplicates exist (resolve manually before applying):
-- SELECT company_id, patient_id, COUNT(*) FROM encounters WHERE status <> 'completed' GROUP BY 1,2 HAVING COUNT(*) > 1;

CREATE UNIQUE INDEX IF NOT EXISTS uq_encounters_active_patient_company
    ON encounters (company_id, patient_id)
    WHERE status <> 'completed';

ALTER TABLE encounters
    ADD COLUMN IF NOT EXISTS created_by UUID NULL REFERENCES users(id);

CREATE INDEX IF NOT EXISTS ix_encounters_created_by ON encounters(created_by);
