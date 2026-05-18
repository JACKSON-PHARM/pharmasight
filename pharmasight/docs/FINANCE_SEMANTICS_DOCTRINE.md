# Finance Semantic Doctrine (E5.5 / E6 / E6.5)

Operational-financial infrastructure only. **Not accounting.**

Code enforcement lives in `app/finance/doctrine/`. Introspection: `GET /api/finance/doctrine`.

---

## 1. Projection Doctrine

| Invariant | Meaning |
|-----------|---------|
| Disposable | Projections can be deleted/rebuilt without data loss |
| Rebuildable | Recompute from `financial_events` + links |
| Never authoritative | `authoritative` is always `false` |
| No business state | Projections do not own entities |
| No operational mutation | Read-only execution |
| No balance truth | No cumulative stored balances |
| Lineage declared | `lineage_source` + `lineage_event_types` |
| Temporal declared | `temporal_basis`: occurred_at / emitted_at / as_of_query |
| No accounting terms | Registry validation rejects GL language |
| Governance required | `FinanceAccessContext` on every API |

**E6 contract fields:** `cacheable`, `consistency`, `scope_expectation`, `company_scoped`.

---

## 2. Correlation Governance

Correlation kinds are **semantically immutable**. Never overload a kind with new meaning — add a new kind.

| Kind | Purpose |
|------|---------|
| `invoice_lifecycle` | Customer invoice economic flow |
| `supplier_invoice` | Supplier payable chain |
| `payment` | Customer payment settlement |
| `supplier_payment` | Supplier disbursement |
| `insurance_claim` | Claim lifecycle |
| `insurance_settlement` | Insurer inflow |
| `settlement_group` | Multi-allocation group |
| `treasury_flow` | Routing movement stream |
| `backfill` / `replay` | Reconstruction / repair ops |
| `posting_candidate` | Reserved (E7+ staging, no GL in E6) |
| `audit_session` | Audit investigation |

**Forbidden:** policy-pack prefixes (`retail`, `wholesale`, `hospital`) — they overload commercial semantics.

Emitter validates `correlation_group` on every new event.

---

## 3. Settlement Semantics

| Rule | Value |
|------|-------|
| Links append-only | Yes |
| Cycles allowed | No |
| One payment → many accruals | Yes |
| Cross-branch settlement | No (rejected at link time) |
| Reversals | Compensate **events**, not links |
| Orphan links | Flagged by `settlement_graph_health` projection |

---

## 4. Treasury Doctrine

`cashbook_accounts` = **routing buckets** (till, mpesa, bank, pools).

**Not:** ledger accounts, balances, debit/credit, CoA.

Preferred language: routing bucket, treasury channel, movement stream.

---

## 5. Event Temporal Semantics

- `occurred_at` — economic time (projections, backfill chronology)
- `emitted_at` — system persistence (audit ordering)
- Backfill **must not** rewrite `occurred_at` on existing events
- No “smart recomputation” — hooks replay only

---

## 6. Backfill Doctrine

Controlled lineage reconstruction via idempotent hooks. Audited in `finance_backfill_runs`.

Forbidden: UPDATE/DELETE events, balance materialization, retroactive policy reinterpretation.

---

## E6 Additions

- `ProjectionContract` validated at registry load
- Projection responses include `contract` envelope
- `settlement_graph_health` projection
- Cross-branch settlement rejected on link create
- `GET /api/finance/doctrine` — full doctrine bundle

---

## E6.5 — Economic Semantics (see `FINANCE_E65_SEMANTICS.md`)

1. **Economic position** — derived exposure states; `GET /api/finance/semantics/exposure/{id}`
2. **Causal lineage** — deterministic replay order (`occurred_at`, `created_at`, `idempotency_key`)
3. **Projection freshness** — invalidation metadata on projections; no caching enabled
4. **Event evolution** — schema version matrix + projection compatibility
5. **Treasury UI** — movement vs holdings presentation rules
6. **Orchestration boundary** — formal E7 consumption/mutation limits
7. **Settlement prevention** — cycle check before link insert
