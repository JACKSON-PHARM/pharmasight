# Finance E2.5 — Governance Hardening & Observability

Stabilization phase before `financial_events` or any accounting orchestration. No GL, journals, posting queues, or cashbook_accounts were introduced.

## 1. Governance telemetry event catalog

Logger: `pharmasight.finance.governance` (JSON lines, append-only).

| Event | Level | When |
|-------|-------|------|
| `finance_access_denied` | WARNING | Permission check failed |
| `finance_scope_denied` | WARNING | Branch/department outside allowed set |
| `finance_classification_denied` | WARNING | Required classification exceeds holder ceiling |
| `finance_permission_granted` | INFO | Explicit finance permission satisfied |
| `finance_audit_scope_used` | INFO | Successful access with `AUDIT_READ` visibility |
| `finance_executive_scope_used` | INFO | Successful access with holder `executive` classification |
| `finance_company_scope_used` | INFO | Successful access with `COMPANY` visibility |
| `deprecated_permission_fallback_used` | INFO | Legacy alias satisfied permission (e.g. `reports.view`) |

### Payload fields

- `user_id`, `company_id`, `timestamp` (UTC ISO)
- `endpoint` (route path when bound via `bind_fastapi_request`)
- `permission`, `required_classification`
- `resolved_scope`, `max_classification`
- `requested_branch_id`, `allowed_branch_ids`
- `correlation_id` (`X-Request-ID`, `X-Correlation-ID`, or `request.state`)
- `registry_id`, `legacy_permission` (fallback only)

Telemetry failures are swallowed; requests are never blocked by logging.

## 2. Endpoint governance inventory

Canonical source: `app/finance/governance/registry.py` → `FINANCE_GOVERNANCE_REGISTRY`.

Programmatic export: `introspect_registry()`.

Each entry defines: `registry_id`, module, route template, permission, classification, scope expectation, branch/company scoping, legacy fallback flag.

Finance API routes reference `registry_id=...` on guards so metadata is not duplicated in handlers.

## 3. Remaining legacy compatibility paths

Legacy satisfaction is **only** inside `resolves_finance_permission_with_source()` / `LEGACY_FINANCE_PERMISSION_ALIASES`.

| Finance permission | Legacy aliases |
|--------------------|----------------|
| `finance.reports.operational` | `reports.view` |
| `finance.reports.management` | `reports.view`, `dashboard.view_gross_profit` |
| `finance.cashbook.view_branch` | `reports.view` |
| `finance.cashbook.reconcile_branch` | `settings.edit` |
| `wholesale.ar.view` | `reports.view`, `customers.view` |
| `hospital.insurance.view` | `sales.view`, `reports.view` |
| … | See `permissions.py` for full map |

Fallback usage emits `deprecated_permission_fallback_used`.

Finance API modules must **not** call `reports.view` directly (enforced by tests).

## 4. Classification semantics

Business lanes (ordered): `operational` → `branch_finance` → `management` → `confidential` → `executive`.

`audit` is an **orthogonal lane**:

- Endpoints requiring `audit` classification → only holders with `audit` clearance.
- Holders with `audit` may read all business-lane classifications (read governance).
- `executive` does **not** imply `audit`.

Aggregation across assignments: `effective_max_classification()` — audit on any row grants audit lane; otherwise highest business lane.

`classification_allows()` is the single authorization primitive (avoid raw rank compares in APIs).

## 5. Branch query scope safety

`resolve_branch_query_scope()` modes:

| Mode | SQL behavior |
|------|----------------|
| `UNRESTRICTED_COMPANY` | No branch filter (`COMPANY` / `AUDIT_READ`, branches known) |
| `FILTER_BRANCHES` | `.in_(allowed_branch_ids)` |
| `DENY_EMPTY` | `WHERE false` — **never** treat empty allowed set as “all branches” |

`FinanceAccessContext` is immutable; filtering uses pure functions in `query_scope.py`.

## 6. Unresolved future governance risks

- Role editor UI does not yet surface `finance_visibility_scope` / `max_finance_classification`.
- `/auth/me` does not expose finance permissions or effective scope.
- `require_finance_permission()` FastAPI dependency still permission-only (no context) — must pair with context guards.
- VAT / executive report routes not yet in registry when added.
- No persisted governance audit table (logs only); SIEM ingestion not configured.
- Department scope filtering on transactional writes not fully enforced outside reports.

## 7. Migration safety notes

- No new DB migrations in E2.5.
- E2 migrations `135` / `136` must be applied before scope columns are reliable.
- Legacy fallback remains enabled (`allow_legacy=True`) until role backfill is verified in production.
- Disabling legacy without explicit grants will deny users who only hold `reports.view`.

## Review gates (E2.5)

- [x] Finance endpoints use `FinanceAccessContext` resolution
- [x] `assert_finance_access()` central enforcement + telemetry
- [x] No direct `reports.view` in finance API modules
- [x] Empty branch allow-list cannot return unfiltered company data
- [x] AUDIT ≠ executive superset
- [x] Telemetry cannot break requests
