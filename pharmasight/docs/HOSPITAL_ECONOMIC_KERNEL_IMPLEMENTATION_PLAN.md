# Hospital Economic Kernel — Implementation Plan

**Doctrine:** [HOSPITAL_ECONOMIC_TOPOLOGY.md](./HOSPITAL_ECONOMIC_TOPOLOGY.md)  
**Status:** H1–H6 kernel + Patient Financial Journeys UI (E2E testing).

---

## Kernel areas

| Area | Module | Status |
|------|--------|--------|
| Care charge engine | `app/hospital/economic/charge_engine.py` | **H1 done** |
| PFJ correlation | `app/hospital/economic/pfj_service.py`, `finance/events/correlation.py` | **H1 done** |
| Financial event feed | `app/hospital/economic/financial_hooks.py` | **H1 done** (`care_value_accrued`) |
| PFJ timeline (read model) | `app/hospital/economic/timeline.py` | **H1 done** |
| Liability allocation | `app/hospital/economic/liability_engine.py` | **H2 done** |
| Coverage profiles | `app/hospital/economic/coverage_service.py` | **H2 done** |
| Authorization SM | `app/hospital/economic/authorization_engine.py` | **H3 done** |
| Recognition policies | `app/hospital/economic/recognition_engine.py` | **H4 done** |
| Claim line generation | `app/hospital/economic/claims_builder.py` | **H5 done** |
| Settlement orchestration | `app/hospital/economic/discharge_service.py` | **H6 done** |
| PFJ workspace UI | `frontend/js/pages/finance_hospital_journeys.js` | **done** |

---

## H1 delivered (this release)

### Schema (`146_hospital_economic_kernel_h1.sql`)

- `patient_financial_journeys` — economic root
- `care_charges` — accrued care value facts
- `encounters.pfj_id` — link clinical scope to PFJ

### API (kernel only, no UI)

| Method | Path |
|--------|------|
| GET | `/api/hospital/economic/pfj/{id}` |
| GET | `/api/hospital/economic/pfj/for-patient/{patient_id}/active` |
| GET | `/api/hospital/economic/pfj/{id}/timeline` |
| GET | `/api/hospital/economic/charges?pfj_id=&encounter_id=` |

### Financial kernel integration

- Event types: `care_value_accrued`, `care_value_reversed`
- Correlation: `patient_financial_journey:{pfj_id}`
- Enabled in `HOSPITAL_INSURANCE` policy pack (branches with `ENCOUNTER` / `HOSPITAL` workflow)

### Non-breaking clinic bridge

- `ensure_draft_invoice_for_encounter` **unchanged** as OPD presentation bridge
- After encounter create / service execute: **parallel** `care_charge` accrual (non-fatal on failure)
- Invoice FK on charge is `bridge_only` metadata — not authoritative

### Invariants enforced

- No PFJ balance column stored
- No liability on invoice
- Charge idempotency: one active accrual per `(source_entity_type, source_entity_id)`
- `care_value_accrued` is **not** `receivable_accrued` (no AR until H4 recognition)

---

## Implementation order (remaining)

### H2 delivered

**Migration:** `147_hospital_economic_kernel_h2.sql`

- `pfj_coverage_profiles` — primary/secondary coverage, obligor route, insurer % / copay
- `liability_allocation_runs` — versioned runs per charge (one active)
- `liability_allocation_lines` — patient / insurer / employer / guarantor slices

**Engine:** auto-allocate on charge accrue; manual `POST .../charges/{id}/reallocate`; `reallocate_after_denial` helper.

**Financial event:** `liability_allocated` (adjustment layer — not AR).

**API:**

| Method | Path |
|--------|------|
| GET | `/api/hospital/economic/pfj/{id}/coverage` |
| PUT | `/api/hospital/economic/pfj/{id}/coverage` |
| GET | `/api/hospital/economic/pfj/{id}/liability-summary` |
| GET | `/api/hospital/economic/charges/{id}/liability` |
| POST | `/api/hospital/economic/charges/{id}/reallocate` |

PFJ timeline now includes `liability_allocation` entries.

### H3 — Authorization lifecycle

Tables: `authorizations` (requested → approved | partial | denied | expired)  
Engine: `pending_authorization_amount` derived; gate recognition (H4).

### H4 — Recognition policies

Events: `patient_receivable_recognized`, `insurer_receivable_recognized`  
Policy pack rules: when claim submitted vs approved vs self-pay checkout.

### H5 — Claim line architecture

`claim_lines.care_charge_id` required; `insurance_claims.pfj_id`; optional `sales_invoice_id` for export only.

### H6 — Settlement orchestration

Link `patient_payment_received` / deposits to patient AR accruals; discharge `pfj_settlement` close record.

### H3–H6 + UI

**Migration:** `148_hospital_economic_kernel_h3_h6.sql`

- `care_authorizations`, `hospital_recognition_records`, `insurance_claim_lines`, `pfj_discharge_settlements`
- `insurance_claims.pfj_id` (nullable)

**UI:** Finance → **Patient Financial Journeys** (`#finance-patient-journeys`)

---

## Migration

Run on Supabase (in order):

```text
pharmasight/database/migrations/146_hospital_economic_kernel_h1.sql
pharmasight/database/migrations/147_hospital_economic_kernel_h2.sql
pharmasight/database/migrations/148_hospital_economic_kernel_h3_h6.sql
```

---

## Testing

```bash
cd pharmasight/backend
python -m pytest tests/test_hospital_economic_kernel.py tests/test_hospital_liability_engine.py tests/test_finance_e3_events.py -q
```
