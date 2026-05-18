# Finance E1 — Implementation Review (Finance REBAC Foundations)

**Epic:** E1 only — permissions, governance package, targeted API refactors.  
**Migrations:** `133_finance_permissions.sql`, `134_finance_permission_role_backfill.sql`  
**Code:** `backend/app/finance/governance/`

---

## 1. Migration SQL

| Migration | Purpose |
|-----------|---------|
| `133_finance_permissions.sql` | Seeds 24 namespaced permissions (`finance.*`, `wholesale.ar.*`, `hospital.*`, `retail.till.*`) |
| `134_finance_permission_role_backfill.sql` | Grants to admin roles; maps legacy `reports.view`, `settings.edit`, `customers.*`, `sales.*` |

**Fix (2026-05-17):** Block 2 in `134` incorrectly selected `ur.role_id` from `user_roles` (column does not exist). Correct source is `rp.role_id` from `role_permissions`. If startup failed on 134, restart the app after pulling the fix; `133` is already applied, `134` will run on next boot.

`reports.view` is **not removed** — compatibility only.

---

## 2. Permission matrix (old → new)

| Legacy permission | New permission(s) granted (via shim and/or migration 134) |
|-------------------|-----------------------------------------------------------|
| `reports.view` | `finance.cashbook.view_branch`, `finance.reports.operational`; `finance.reports.management` for pharmacist/admin/viewer/procurement roles only |
| `settings.edit` | `finance.cashbook.reconcile_branch`, `retail.till.reconcile`, `hospital.insurance.manage_providers` |
| `dashboard.view_gross_profit` | `finance.reports.management` (runtime shim) |
| `customers.view` | `wholesale.ar.view` |
| `customers.record_payment` | `wholesale.ar.collect` |
| `customers.manage_credit` | `wholesale.ar.credit_control` |
| `sales.view` | `hospital.insurance.view`, `hospital.billing.view` |
| `sales.edit` | `hospital.insurance.settle`, `hospital.billing.adjust` |
| `sales.create` | `hospital.billing.create`, `retail.till.operate` |
| Super Admin / admin / owner / platform admin | All finance namespace permissions (global) |

### Runtime legacy shim (`LEGACY_FINANCE_PERMISSION_ALIASES`)

Documented in `app/finance/governance/permissions.py`. Explicit permission is always checked first; legacy names apply only when `allow_legacy=True` (default).

**Notable tightening:**

| Endpoint | Before | After |
|----------|--------|-------|
| `POST /api/cashbook/backfill` | `reports.view` | `finance.cashbook.reconcile_branch` (legacy: `settings.edit` only) |
| `GET /api/customers/reports/aging` | No permission (module gate only) | `wholesale.ar.view` |
| Insurance APIs | `sales.view` / `settings.edit` / `reports.view` | `hospital.insurance.*` |

---

## 3. Endpoint-by-endpoint permission changes

### `api/cashbook.py`

| Method | Path | New permission | Branch guard |
|--------|------|----------------|--------------|
| GET | `/cashbook` | `finance.cashbook.view_branch` | Required (`branch_id` or `X-Branch-ID`) + assignment |
| GET | `/cashbook/summary` | `finance.cashbook.view_branch` | Same |
| POST | `/cashbook/backfill` | `finance.cashbook.reconcile_branch` | Same |

### `api/reports.py`

| Method | Path | New permission | Branch guard |
|--------|------|----------------|--------------|
| GET | `/reports/item-movement` | `finance.reports.operational` | Session `X-Branch-ID` + assignment |
| GET | `/reports/batch-movement` | `finance.reports.operational` | Session branch; optional `branch_id` query validated |

### `api/insurance_management.py`

| Method | Path | New permission |
|--------|------|----------------|
| GET | `/providers` | `hospital.insurance.view` |
| POST | `/providers` | `hospital.insurance.manage_providers` |
| PUT | `/providers/{id}` | `hospital.insurance.manage_providers` |
| GET | `/claims` | `hospital.insurance.view` |
| PATCH | `/claims/{id}/status` | `hospital.insurance.settle` |
| POST | `/settlements` | `hospital.insurance.settle` + branch access on `body.branch_id` |
| GET | `/settlements` | `hospital.insurance.view` |
| GET | `/statement` | `hospital.insurance.view` |
| GET | `/aging` | `hospital.insurance.view` |

### `api/customer_management.py` (aging only)

| Method | Path | New permission | Branch guard |
|--------|------|----------------|--------------|
| GET | `/reports/aging` | `wholesale.ar.view` | Optional `branch_id` validated when provided |

**Out of scope (E1):** other customer routes remain on existing `customers.*` permissions.

---

## 4. Backward compatibility assumptions

1. **Migration 134 must run** before deploy in environments that rely on new permission rows.
2. **Legacy shim** remains enabled by default until roles are migrated in UI and legacy grants are removed (future epic).
3. Users with **only** `reports.view` retain cashbook view + operational reports; **not** cashbook backfill unless they also have `settings.edit`.
4. **Cashier** role: if it has `sales.create` but not `reports.view`, it gains `retail.till.operate` via migration 134; still no cashbook/management reports unless explicitly granted.
5. **`finance.cashbook.view_company`** is seeded but **not used** in E1 endpoints (no company-wide cashbook API yet) — avoids implying company visibility from branch permission.
6. **GL permissions** (`finance.gl.*`) are seeded for admin roles but **not enforced** on any route in E1.

---

## 5. Security edge cases discovered

| Issue | Mitigation in E1 |
|-------|------------------|
| Customer aging had **no permission** beyond wholesale module | Now requires `wholesale.ar.view` |
| `branch_id` query could target another branch | `assert_finance_branch_access_optional` on aging when `branch_id` set |
| Company-wide aging without `branch_id` still returns all company AR | **Known gap** — E2 visibility scope will filter to assigned branches |
| `finance.cashbook.view_company` aliased to `reports.view` in shim | Documented; E2 will remove alias and require explicit company scope + permission |
| Insurance settlement `branch_id` from client | Now validated with `assert_finance_branch_access` |
| Batch report optional `branch_id` | Re-validated against user assignments (not session-only) |

---

## 6. Example role templates (recommended grants)

### Retail cashier

| Permission | Purpose |
|------------|---------|
| `retail.till.operate` | POS / sales |
| `sales.create`, `sales.view` | Operational (existing) |
| **Deny** | `finance.cashbook.*`, `finance.reports.management`, `wholesale.ar.*` |

### Branch manager

| Permission | Purpose |
|------------|---------|
| `finance.cashbook.view_branch` | Branch cash position |
| `finance.reports.operational` | Movement / operational reports |
| `finance.reports.management` | Branch P&L / gross profit |
| `retail.till.reconcile` | Till closure |
| `expenses.view`, `expenses.create` | Branch expenses |

### Wholesale credit controller

| Permission | Purpose |
|------------|---------|
| `wholesale.ar.view` | Aging, statements |
| `wholesale.ar.credit_control` | Limits / terms |
| `wholesale.ar.collect` | Record payments |
| `finance.reports.management` | AR dashboards |
| Module: `wholesale` + branch `WHOLESALE_DISTRIBUTION` |

### Hospital billing officer

| Permission | Purpose |
|------------|---------|
| `hospital.billing.view`, `hospital.billing.create`, `hospital.billing.adjust` | Patient billing |
| `hospital.insurance.view` | Claims visibility |
| **Not** | `hospital.insurance.manage_providers` unless head office |

### CFO / Finance executive

| Permission | Purpose |
|------------|---------|
| `finance.cashbook.view_company` | Treasury (when APIs exist) |
| `finance.reports.executive` | Consolidated P&L |
| `finance.vat.view_company`, `finance.vat.export` | Compliance |
| `finance.reports.audit_read` | Audit trails |
| All branch assignments or `COMPANY` scope (E2) |

### Auditor

| Permission | Purpose |
|------------|---------|
| `finance.reports.audit_read` | Read-only finance reports |
| `finance.gl.view` | When GL ships |
| **Deny** | `*.post`, `*.settle`, `*.collect`, `reconcile_branch` |

---

## 7. Review gates checklist

- [x] No new endpoint uses **only** `reports.view`
- [x] `company_id` isolation unchanged (existing request state / RLS GUC)
- [x] No new permission implies company-wide data access without `view_company` (unused in E1 routes)
- [x] Backend enforcement on all refactored endpoints
- [ ] Frontend role editor — **follow-up** (not E1): expose finance permission groups
- [ ] `/auth/me` finance permission list — **follow-up** (not E1)

---

## 8. Consolidation pass (post-migration)

- Added `app/finance/governance/access.py` — single entry point for permission + branch checks.
- Remapped: expenses summary, gross profit, supplier aging, items batch dropdown.
- Removed direct `reports.view` from all E1 finance API modules (enforced by `test_finance_e1_consolidation.py`).
- Permission heatmap: `docs/FINANCE_E1_PERMISSION_HEATMAP.md`.

## 9. Explicitly not in E1

- `financial_events` table or emitters
- `cashbook_accounts`
- `ReportContext` / report registry router
- Visibility scope columns on `user_branch_roles`
- Classification enforcement
- GL tables or routes
- Changes to `commercial_transactions`

---

## 9. Tests

- `backend/tests/test_finance_governance_permissions.py` — registry and legacy alias invariants

Run: `pytest backend/tests/test_finance_governance_permissions.py`
