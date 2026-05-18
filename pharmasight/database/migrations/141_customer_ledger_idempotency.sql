-- Idempotent customer AR ledger posting (opening_balance, credit_note, invoice, payment).

CREATE UNIQUE INDEX IF NOT EXISTS uq_customer_ledger_entry_ref
    ON customer_ledger_entries (company_id, customer_id, entry_type, reference_id)
    WHERE reference_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_customer_ledger_opening_balance
    ON customer_ledger_entries (company_id, customer_id)
    WHERE entry_type = 'opening_balance';
