# Finance E6.7 & E7 — Authority Governance & Accounting Orchestration

## E6.7 — Authority & transition governance

Defines **who** may transition economic/commercial state and **when** accounting interpretation is allowed.

- Bridges `commercial_transactions` constitutional spine with `financial_events` lineage
- `POSTING_ELIGIBLE_COMMERCIAL_STATES`: BILLING_ACCEPTED, FISCAL_READY, FISCAL_EXTERNALIZED, SETTLEMENT_*
- Blocks: DRAFT, EXCEPTION_HOLD, DISPUTE_FROZEN, REVERSED
- Mutation windows, reversibility types, fiscal externalization boundaries documented in code

Introspection: `GET /api/finance/doctrine` → `authority` section

## E7 — Accounting orchestration (NOT GL)

Journal **proposals** are derived interpretations of immutable `financial_events`.

### What E7 is

| Yes | No |
|-----|-----|
| `journal_proposals` + lines + evidence links | General ledger balances |
| Semantic accounts (`accounts_receivable`, `revenue`) | CoA as authoritative truth |
| draft → approved → posted workflow | UPDATE financial_events |
| Reversal via new proposal | Edit posted proposals |
| `accounting_posting_records` audit | Operational invoice mutation |

### Workflow

1. `POST /api/finance/accounting/proposals/generate` — from `financial_event_id`
2. `POST .../proposals/{id}/approve` — requires `finance.gl.post`
3. `POST .../proposals/{id}/post` — commits interpretation record
4. `POST .../proposals/{id}/reverse` — creates compensating draft proposal

### Eligibility

`GET /api/finance/accounting/eligibility/{financial_event_id}`

Checks permission, lineage reversal state, commercial transaction state (when linked to sales invoice).

### Migration

`140_finance_e67_e7_accounting_orchestration.sql`

### Permissions

- `finance.gl.view` — generate, list, doctrine
- `finance.gl.post` — approve, post, reverse

## Constitutional rule

> E7 consumes governed lineage. E7 never creates or mutates authoritative economic truth.

## Future (not E7)

- Full chart of accounts
- Trial balance / period close engines
- Subledger synchronization as authoritative

Those require separate phases that continue to treat `financial_events` as evidence only.
