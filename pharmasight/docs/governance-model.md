# SightOps Governance Model

PharmaSight / SightOps uses a **single shared database** scoped by `company_id`. Platform governance defines policy; operational systems consume compiled policy; the commercial transaction engine records constitutional transitions under that policy.

## Hierarchy

```text
Platform Admin (control plane)
  → Company governance (commercial access, operating model, modules)
      → Branch fiscal doctrine (invoice_workflow_type)
          → Runtime enforcement (API guards, UI, lifecycle hooks)
              → Constitutional record (commercial_transactions)
```

**Modules are capabilities. Doctrine is workflow behavior. Never infer one from the other.**

## Five governance layers

| Layer | Source of truth | Purpose |
|-------|-----------------|--------|
| 1. Commercial access | `companies.is_active`, `subscription_status`, `trial_expires_at` | Can the tenant use SightOps? |
| 2. Licensed capabilities | `company_modules` | Which product areas are licensed? |
| 3. Organizational operating model | `companies.organization_operating_model` | What kind of organization is this? |
| 4. Branch fiscal doctrine | `branches.invoice_workflow_type` | How does this branch close the fiscal spine? |
| 5. Constitutional record | `commercial_transactions` (+ transitions) | What happened to commercial transactions? |

## Operating models

| Value | Intent |
|-------|--------|
| `PHARMACY_RETAIL` | Retail-first; branches typically `RETAIL_COUNTER` |
| `OUTPATIENT_CLINIC` | Encounter-first; branches typically `ENCOUNTER_CONSOLIDATED` |
| `HYBRID_HOSPITAL` | Pharmacy + clinic; mixed branch doctrines |
| `ENTERPRISE_NETWORK` | Multi-branch enterprise; broad capabilities |

Presets compile into `company_modules` rows and default HQ `invoice_workflow_type`. Operators may override individual modules or branch doctrine where the operating model allows.

## Branch fiscal doctrine

| Value | Meaning |
|-------|---------|
| `RETAIL_COUNTER` | Pharmacy counter owns batch → billing accepted on batch (retail spine) |
| `ENCOUNTER_CONSOLIDATED` | Batch → operationally complete only; billing acceptance not auto on batch |

## Policy compilation

Admin actions (preset / operating model) should compile into:

- `company_modules`
- HQ branch workflow default
- Suggested subscription fields (provisioning)

Future: billing permissions, KRA expectations, UI route visibility.

**Compiler:** `backend/app/services/company_governance_service.py` — `compile_governance_profile()`, `apply_operating_model_preset()`.

## Derived runtime states

| State | Meaning |
|-------|---------|
| `active` | Paid / explicit active subscription |
| `trial` | Valid trial window |
| `expired` | Trial ended |
| `demo` | Explicit demo status |
| `suspended` | Suspended / canceled / past_due |
| `blocked` | Company inactive |
| `legacy_active` | Grandfathered: null operating model + null subscription_status (Option A) |
| `onboarding_pending` | Non-legacy company without explicit commercial access |

`GET /api/auth/me` includes a `governance` summary. `subscription_access` still maps from legacy `CompanyAccess` until Phase 2 enforcement tightens.

## Enforcement order

1. Commercial gate — `is_active`, derived access
2. Module gate — `require_module()` / compiled entitlements
3. Doctrine gate — `invoice_workflow_policy`, lifecycle on batch/KRA
4. Constitutional engine — records transitions; does not set policy

## Forbidden inference rules

Runtime must **not**:

- Assume encounter workflow because `clinic` module is enabled
- Assume retail lifecycle because `pharmacy` is enabled
- Default pharmacy when module rows are missing (except **legacy grandfather**)
- Default `RETAIL_COUNTER` without reading branch row (DB default is not a governance substitute for unset policy on new orgs)
- Treat null `subscription_status` as full access on **new** companies

## Migration doctrine (Option A)

- **Existing** companies with null `organization_operating_model` and null `subscription_status` → `legacy_active` until migrated
- **New** companies (provisioning) → explicit `organization_operating_model`, `subscription_status` (`trialing` or `demo`), compiled modules
- Admin UI warns when `uses_legacy_governance` is true
- Long-term: eliminate implicit unrestricted access everywhere

## Constitutional engine responsibilities

- Append-only `commercial_transaction_transitions`
- Lawful state transitions per `commercial_transaction_state.py`
- Hooks from sales create/batch, KRA submit, payment — **under** branch doctrine
- Does **not** define subscription, modules, or operating model

## Admin APIs (platform licensing)

| Endpoint | Purpose |
|----------|---------|
| `GET .../company/{id}/governance` | Full compiled profile |
| `PATCH .../company/{id}/operating-model` | Set operating model (+ optional preset compile) |
| `POST .../company/{id}/apply-governance-preset` | Re-compile modules + HQ doctrine |
| `PATCH .../branch/{id}/fiscal-doctrine` | Set branch `invoice_workflow_type` |

Canonical UI: `admin.html` → Licensing tab.

## Duplicated surfaces (technical debt)

- In-app `#platform-admin-*` duplicates licensing — converge on platform-licensing APIs
- `tenants` registry is identity/onboarding only, not subscription truth
