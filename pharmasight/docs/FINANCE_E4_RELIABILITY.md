# Finance E4 — Event Reliability & Settlement Semantics

Bridge between immutable `financial_events` (E3) and future accounting orchestration. **Not GL, not journals, not reconciliation engines.**

## 1. Replay architecture

| Component | Role |
|-----------|------|
| `financial_event_emission_failures` | Captures failed emits with full replay payload |
| `replay_emission_failure()` | Re-emits with same `idempotency_key` + `occurred_at` |
| `financial_event_replay_log` | Append-only audit of replay attempts |
| CLI `scripts/replay_financial_event_failures.py` | Batch replay without workers |

Replay rules:

- `emission_channel=replay`, `operational_status=replayed`
- `replay_source_failure_id` links to failure row
- `CREATED` or `DUPLICATE` resolves failure (idempotent)
- Governed API: `POST /api/finance/events/failures/{id}/replay` (`finance.reports.audit_read`)

## 2. Settlement linkage semantics

Append-only `financial_event_settlement_links`:

| Semantic | Settlement event | Settles event |
|----------|------------------|---------------|
| `customer_payment_settles_receivable` | `cash_received` | `receivable_accrued` |
| `supplier_payment_settles_payable` | `cash_paid` | `payable_recognized` |

- `caused_by_event_id` set **at emit time** (immutable) when primary accrual is known
- Multi-invoice payments use link rows per allocation
- No UPDATE to `financial_events` after insert

## 3. Integrity verification model

`verify_company_lineage()` — read-only gap detection:

- `missing_receivable_accrued`, `missing_cash_received`, etc.
- `orphan_reversal` when parent event missing

API: `GET /api/finance/events/integrity`

No automatic mutation repair — use replay tooling.

## 4. Event operational lifecycle

| Status | Meaning |
|--------|---------|
| `emitted` | Normal first-time persist |
| `replayed` | Succeeded via failure replay |
| `compensated` | Compensating/reversal event |
| `duplicate_ignored` | Telemetry-only for duplicate skip |

| Channel | Meaning |
|---------|---------|
| `original` | Operational hook |
| `replay` | Failure replay |
| `backfill` | Reserved controlled backfill |

## 5. Policy pack catalog

| Pack | Use |
|------|-----|
| `RETAIL_SIMPLE` | Cash-first; skips `receivable_accrued` |
| `WHOLESALE_AR` | Full AR/AP + settlement links |
| `HOSPITAL_INSURANCE` | Insurance + core AP |

Resolved from `sales_type` / branch workflow hints.

## 6. Correlation grouping

`correlation_group` on events, e.g. `wholesale:{invoice_id}`, `payment:{payment_id}`.

List filter: `GET /api/finance/events?correlation_group=...`

## 7. Enhanced lineage API

`GET /api/finance/events/{id}` returns:

- reversals, caused_by, settles (children via `caused_by_event_id`)
- settlement link rows
- replay logs
- correlated events in same group

## 8. Migration

`138_financial_event_e4_reliability.sql` — apply on startup after 137.

## 9. Unresolved accounting boundaries

- No debit/credit, CoA, journals, TB, period close
- No reconciliation engine or balance derivation
- No async workers (replay is sync CLI/API)
- `caused_by_event_id` graph orchestration partial (settlement links + primary caused_by)
- Insurance claim accrual events not yet emitted (settlement links TBD)

## Review gates

- [x] Append-only events preserved
- [x] Replay idempotent
- [x] Settlement via links + emit-time caused_by only
- [x] Integrity read-only
- [x] Governance on replay/integrity endpoints
- [x] No accounting terminology in `economic_direction`
