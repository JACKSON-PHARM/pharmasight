# Finance E6.5 — Economic Semantics & Orchestration Boundary

Doctrine-heavy stabilization before E7 (accounting orchestration). **No GL, journals, or posting.**

## Scope delivered

| Area | Module | Purpose |
|------|--------|---------|
| Economic position | `doctrine/economic_position.py`, `semantics/exposure.py` | Derived open/partial/closed/reversed/stale exposure |
| Causal lineage | `doctrine/causal_lineage.py` | Deterministic replay ordering |
| Projection freshness | `doctrine/projection_freshness.py` | Staleness classes, replay invalidation |
| Event evolution | `doctrine/event_evolution.py` | Schema compatibility matrix |
| Orchestration boundary | `doctrine/orchestration_boundary.py` | E3–E6 vs E7 rules |
| Settlement prevention | `doctrine/settlement.py` | Cycle check **before** link insert |
| Treasury UI semantics | `doctrine/treasury.py` | Movement vs holdings language |

## APIs

| Method | Path |
|--------|------|
| GET | `/api/finance/doctrine` — full bundle including E6.5 sections |
| GET | `/api/finance/semantics/exposure/{accrual_event_id}` — derived exposure state |

## Economic position states (derived only)

- `open_exposure`
- `partially_settled`
- `fully_settled` / `exhausted_claim` (insurance)
- `reversed_exposure`
- `stale_exposure` (temporal, not accounting)
- `disputed_exposure` (from payload signals)

**Never stored.** Operational invoices/payments/claims remain authoritative.

## Orchestration boundary (pre-E7)

`financial_events` are **evidence**, not accounting truth.

E7 may consume lineage read-only; E7 must never UPDATE/DELETE events or settlement links.

## Projection freshness

All projections: `cacheable=False` in E6.5.

Replay/backfill marks lineage-derived projections as potentially stale via `freshness` envelope on projection responses.

## Next phase (E7, not started)

Journal **proposals** as separate artifacts — posting orchestration consumes lineage, never mutates it.
