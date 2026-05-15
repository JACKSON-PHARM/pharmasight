-- Forward-only repair: normalize malformed kra_sync_status on credit_notes and supplier_returns,
-- then recreate CHECK constraints using a normalized expression.
--
-- Runs AFTER 122_reversal_phase1_axes_and_sr_numbering.sql and BEFORE 123 (lexicographic order:
-- 122_z_* sorts after 122_reversal_* and before 123_*). Migration 123 stays frozen; this file carries
-- production-safe data repair so 123's ADD CONSTRAINT can succeed on dirty databases.
--
-- Idempotent: DROP IF EXISTS constraints, rewrite values, ADD constraints.

-- (A) Drop constraints first
ALTER TABLE credit_notes
    DROP CONSTRAINT IF EXISTS credit_notes_kra_sync_status_check;

ALTER TABLE supplier_returns
    DROP CONSTRAINT IF EXISTS supplier_returns_kra_sync_status_check;

-- (B) Normalize: lower, btrim, coalesce; strip BOM and zero-width space; strip control chars
--     (including U+0000) via POSIX class -- no chr(0) literal in this file.
UPDATE credit_notes
SET kra_sync_status = lower(btrim(coalesce(
    regexp_replace(
        replace(replace(coalesce(kra_sync_status, ''), chr(65279), ''), chr(8203), ''),
        '[[:cntrl:]]',
        '',
        'g'
    ),
    ''
)));

UPDATE supplier_returns
SET kra_sync_status = lower(btrim(coalesce(
    regexp_replace(
        replace(replace(coalesce(kra_sync_status, ''), chr(65279), ''), chr(8203), ''),
        '[[:cntrl:]]',
        '',
        'g'
    ),
    ''
)));

-- (C) Map legacy vocabulary (credit_notes)
UPDATE credit_notes
SET kra_sync_status = 'not_started'
WHERE kra_sync_status = '';

UPDATE credit_notes
SET kra_sync_status = 'not_started'
WHERE kra_sync_status IN ('unknown', 'pending');

UPDATE credit_notes
SET kra_sync_status = 'not_required'
WHERE kra_sync_status IN ('not_applicable');

UPDATE credit_notes
SET kra_sync_status = 'pending'
WHERE kra_sync_status IN ('syncing', 'in_progress', 'queued', 'queue');

UPDATE credit_notes
SET kra_sync_status = 'synced'
WHERE kra_sync_status IN ('done', 'completed', 'success', 'ok');

UPDATE credit_notes
SET kra_sync_status = 'not_started'
WHERE kra_sync_status IN ('not_synced');

UPDATE credit_notes
SET kra_sync_status = 'not_started'
WHERE kra_sync_status IN ('posted', 'submitted', 'draft', 'cancelled', 'not_posted');

-- (C) Map legacy vocabulary (supplier_returns)
UPDATE supplier_returns
SET kra_sync_status = 'not_required'
WHERE kra_sync_status = '';

UPDATE supplier_returns
SET kra_sync_status = 'not_required'
WHERE kra_sync_status IN ('unknown', 'not_applicable', 'pending');

UPDATE supplier_returns
SET kra_sync_status = 'pending'
WHERE kra_sync_status IN ('syncing', 'in_progress', 'queued', 'queue');

UPDATE supplier_returns
SET kra_sync_status = 'synced'
WHERE kra_sync_status IN ('done', 'completed', 'success', 'ok');

UPDATE supplier_returns
SET kra_sync_status = 'not_started'
WHERE kra_sync_status IN ('not_synced');

UPDATE supplier_returns
SET kra_sync_status = 'not_started'
WHERE kra_sync_status IN ('posted', 'submitted', 'draft', 'cancelled', 'not_posted');

-- (D) Final catch-all (NULL-safe: coalesce so NULL does not bypass NOT IN)
UPDATE credit_notes
SET kra_sync_status = 'not_started'
WHERE coalesce(kra_sync_status, '') NOT IN (
    'not_required', 'not_started', 'pending', 'retrying', 'synced', 'failed', 'partially_synced'
);

UPDATE supplier_returns
SET kra_sync_status = 'not_required'
WHERE coalesce(kra_sync_status, '') NOT IN (
    'not_required', 'not_started', 'pending', 'retrying', 'synced', 'failed', 'partially_synced'
);

UPDATE credit_notes
SET kra_sync_status = 'not_started'
WHERE kra_sync_status = 'pending';

-- (E) Recreate CHECK constraints on normalized expression (defense in depth; 123 will replace with plain IN)
ALTER TABLE credit_notes ADD CONSTRAINT credit_notes_kra_sync_status_check
    CHECK (
        lower(btrim(coalesce(kra_sync_status, ''))) IN (
            'not_required', 'not_started', 'pending', 'retrying', 'synced', 'failed', 'partially_synced'
        )
    );

ALTER TABLE supplier_returns ADD CONSTRAINT supplier_returns_kra_sync_status_check
    CHECK (
        lower(btrim(coalesce(kra_sync_status, ''))) IN (
            'not_required', 'not_started', 'pending', 'retrying', 'synced', 'failed', 'partially_synced'
        )
    );

-- (F) Diagnostic queries (run manually in SQL editor when debugging bad rows; keep commented)
-- SELECT id, credit_note_no, kra_sync_status, length(kra_sync_status) AS len,
--        encode(convert_to(kra_sync_status, 'UTF8'), 'hex') AS kra_hex
-- FROM credit_notes;
--
-- SELECT id, return_document_no, kra_sync_status, length(kra_sync_status) AS len,
--        encode(convert_to(kra_sync_status, 'UTF8'), 'hex') AS kra_hex
-- FROM supplier_returns;
