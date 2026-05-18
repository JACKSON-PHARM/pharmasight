# Finance E5 — Governed Projections & Treasury Dimension

Operational-financial infrastructure only. **Not accounting.**

## Architectural doctrines (enforced)

| Doctrine | Meaning |
|----------|---------|
| Treasury ≠ GL | `cashbook_accounts` are routing dimensions (till, M-Pesa, bank, pools) |
| Projections are derived | Rebuildable from `financial_events` + links; never authoritative |
| No mutable balances | Period movement snapshots only; no cumulative balance columns |
| Backfill preserves history | Same `occurred_at`, idempotency, policy pack; `emission_channel=backfill` via hooks |
| Governance on reads | Every projection declares permission, classification, scope |
| Correlation taxonomy | Formal `CorrelationKind` prefixes — no ad-hoc groups |
| Insurance lineage first | `insurance_claim_recognized` before any insurance GL |

## Schema (migration 139)

- `cashbook_accounts` — treasury routing (classification-aware)
- `branches.finance_policy_pack` — optional `RETAIL_SIMPLE` \| `WHOLESALE_AR` \| `HOSPITAL_INSURANCE`
- `cashbook_entries.cashbook_account_id` — optional link to routing bucket
- `finance_backfill_runs` — audit trail for controlled reconstruction

## New event types

| Event | When |
|-------|------|
| `retail_cash_collected` | Retail invoice batch (cash-first, no AR accrual) |
| `insurance_claim_recognized` | Claim submitted / status recognition |
| `insurance_settlement_received` | Now links to claim accruals via settlement links |

## Packages

```
app/finance/treasury/     — doctrine, account provisioning
app/finance/projections/  — registry + engine (derived views)
app/finance/events/
  correlation.py          — taxonomy
  branch_policy.py        — DB-backed policy pack resolution
  backfill.py             — controlled reconstruction
```

## APIs

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/finance/projections/registry` | Projection + correlation catalog |
| GET | `/api/finance/projections/{id}` | Execute derived projection |
| GET | `/api/finance/treasury/accounts` | List routing accounts |
| POST | `/api/finance/treasury/accounts` | Create routing account |
| POST | `/api/finance/treasury/branches/{id}/provision-defaults` | Till/M-Pesa/bank defaults |
| POST | `/api/finance/backfill/runs` | Controlled backfill for date range |

## Projections (registry)

- `branch_cash_movement` — period inflow/outflow from events
- `ar_recognized_vs_collected` — wholesale AR lineage summary
- `insurance_claim_exposure` — claim accrual vs settlement inflow
- `lineage_integrity_summary` — integrity findings aggregate
- `treasury_routing_snapshot` — movement by routing type (not balance)

Each response includes `derived: true`, `authoritative: false`, and an explicit disclaimer.

## Still forbidden

GL, journals, debit/credit, trial balance, period close, posting engines, accounting reconciliation.

## Apply migration

Run `139_financial_event_e5_projections_treasury.sql` on startup (after 138).
