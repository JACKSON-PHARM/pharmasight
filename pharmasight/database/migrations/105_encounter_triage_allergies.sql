ALTER TABLE encounter_triage
    ADD COLUMN IF NOT EXISTS allergies TEXT NULL;
