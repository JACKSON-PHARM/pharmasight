-- Clinic register intake persistence fields
-- Adds basic biodata extensions and encounter intake metadata.

ALTER TABLE patients
    ADD COLUMN IF NOT EXISTS id_number TEXT NULL,
    ADD COLUMN IF NOT EXISTS residence TEXT NULL;

ALTER TABLE encounters
    ADD COLUMN IF NOT EXISTS scheduled_for TIMESTAMPTZ NULL,
    ADD COLUMN IF NOT EXISTS initial_destination VARCHAR(30) NULL,
    ADD COLUMN IF NOT EXISTS intake_payment_mode TEXT NULL,
    ADD COLUMN IF NOT EXISTS intake_insurance_scheme TEXT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_encounters_initial_destination'
    ) THEN
        ALTER TABLE encounters
            ADD CONSTRAINT ck_encounters_initial_destination
            CHECK (
                initial_destination IS NULL OR
                initial_destination IN ('triage','consultation','pharmacy','lab','radiology','procedure','referral')
            );
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_encounters_scheduled_for ON encounters(scheduled_for);
CREATE INDEX IF NOT EXISTS ix_encounters_initial_destination ON encounters(initial_destination);
