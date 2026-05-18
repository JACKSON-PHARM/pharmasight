# Finance E1 — Permission Heatmap (consolidation gate)

**Status:** E1 stable gate — approved to start E2 only after this audit passes in CI.  
**Last updated:** consolidation pass after migration 134 fix.

---

## Legend

| Risk | Meaning |
|------|---------|
| **Safe** | Explicit `finance.*` / namespace permission only at endpoint |
| **Transitional** | Explicit permission + legacy shim via `resolves_finance_permission()` |
| **Operational** | Not financial aggregation; inventory/sales ops (unchanged) |
| **Deprecated** | `reports.view` — shim only, never in endpoint code |

---

## Central enforcement (use these)

| Helper | Location | Purpose |
|--------|----------|---------|
| `deny_unless_finance_permission` | `finance/governance/access.py` | Single permission check + legacy shim |
| `require_finance_branch` | same | Permission + branch assignment |
| `guard_finance_branch_query_param` | same | Optional `?branch_id=` validation |
| `resolve_finance_branch_id` | same | Branch resolution without permission |

**Rule:** Finance endpoints must not call `_user_has_permission(..., "reports.view")`.

---

## Endpoint heatmap

| Endpoint | Permission | Legacy shim | Branch guard | Risk |
|----------|------------|-------------|--------------|------|
| `GET /api/cashbook` | `finance.cashbook.view_branch` | `reports.view` | Required | Transitional |
| `GET /api/cashbook/summary` | `finance.cashbook.view_branch` | `reports.view` | Required | Transitional |
| `POST /api/cashbook/backfill` | `finance.cashbook.reconcile_branch` | `settings.edit` | Required | Transitional |
| `GET /api/reports/item-movement` | `finance.reports.operational` | `reports.view` | Session + assignment | Transitional |
| `GET /api/reports/batch-movement` | `finance.reports.operational` | `reports.view` | Session + optional branch | Transitional |
| `GET /api/items/.../batches` (batch dropdown) | `finance.reports.operational` | `reports.view` | Query branch validated | Transitional |
| `GET /api/expenses/summary` | `finance.reports.management` | `reports.view`, `dashboard.view_gross_profit` | Optional branch | Transitional |
| `GET /api/sales/branch/{id}/gross-profit` | `finance.reports.management` | `reports.view`, `dashboard.view_gross_profit` | Path + assignment | Transitional |
| `GET /api/suppliers/reports/aging` | `finance.reports.management` | `reports.view` | Optional branch | Transitional |
| `GET /api/customers/reports/aging` | `wholesale.ar.view` | `reports.view`, `customers.view` | Optional branch | Transitional |
| `GET /api/insurance/providers` | `hospital.insurance.view` | `sales.view`, `reports.view` | Company only | Transitional |
| `GET /api/insurance/claims` | `hospital.insurance.view` | `sales.view` | Company only | Transitional |
| `GET /api/insurance/settlements` | `hospital.insurance.view` | `sales.view` | Company only | Transitional |
| `GET /api/insurance/statement` | `hospital.insurance.view` | `sales.view`, `reports.view` | Company only | Transitional |
| `GET /api/insurance/aging` | `hospital.insurance.view` | `sales.view`, `reports.view` | Company only | Transitional |
| `POST /api/insurance/providers` | `hospital.insurance.manage_providers` | `settings.edit` | Company only | Transitional |
| `PUT /api/insurance/providers/{id}` | `hospital.insurance.manage_providers` | `settings.edit` | Company only | Transitional |
| `PATCH /api/insurance/claims/{id}/status` | `hospital.insurance.settle` | `sales.edit` | Company only | Transitional |
| `POST /api/insurance/settlements` | `hospital.insurance.settle` | `sales.edit` | Body branch validated | Transitional |

---

## Known transitional gaps (E2 targets)

| Gap | Current behavior | E2 fix |
|-----|------------------|--------|
| Company-wide AR aging (no `branch_id`) | All company rows if user has permission | Filter to assigned branches |
| Insurance list endpoints | Company-scoped rows | Branch/department scope |
| `finance.cashbook.view_company` | Seeded, unused | Company cashbook APIs + scope |
| Gross profit path `branch_id` | Validated via `ensure_user_has_branch_access` | Centralize in `require_finance_branch` pattern |

---

## Explicitly NOT financial (unchanged)

| Area | Permission | Notes |
|------|------------|-------|
| Sales CRUD / batch / pay | `sales.*` | Operational |
| Expenses CRUD | `expenses.*` | Operational |
| Customer payments | `customers.record_payment` → maps to `wholesale.ar.collect` | E1 wholesale namespace |
| Purchases / GRN | `purchases.*` | Operational |

---

## CI gate

`tests/test_finance_e1_consolidation.py` fails if any E1 finance API file contains a direct `'reports.view'` string.

`tests/test_finance_governance_permissions.py` validates shim invariants (reconcile ≠ reports.view).

---

## E1 exit criteria (this document)

- [x] Zero direct `reports.view` in finance-sensitive API files
- [x] Unified `access.py` helpers
- [x] Cashbook / insurance / customer aging / reports / P&L / expense summary / supplier aging mapped
- [x] Migration 133 + 134 apply cleanly
- [ ] Frontend role editor shows finance permission groups (follow-up)
- [ ] `/auth/me` exposes finance permissions (follow-up)

**E2 may start** when the above checkboxes for backend are signed off by product owner.
