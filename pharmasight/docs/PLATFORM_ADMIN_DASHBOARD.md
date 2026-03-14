# Platform Admin Dashboard

The Platform Admin Dashboard gives the platform operator (you) insight into **usage, health, and engagement** across all companies and branches, without exposing item-level inventory or transactional data.

## Access

- **URL**: Open `/admin.html` and log in with **platform admin** credentials (admin token from `POST /api/admin/auth/login`).
- **Auth**: All dashboard API endpoints require `Authorization: Bearer <admin_token>` and are **PLATFORM_ADMIN-only**. Company admins and normal users cannot access them.

## Backend (FastAPI)

### Endpoints (all under `/api/admin/metrics/`, rate limited)

| Endpoint | Description | Data source |
|----------|-------------|-------------|
| `GET /summary` | Companies count, branches count, users count, active sessions now | `companies`, `branches`, `users`, `refresh_tokens` |
| `GET /companies` | List companies with branch_count, user_count. Optional: `company_id`, `date_from`, `date_to`, `limit`, `offset` | `companies`, `branches`, `user_branch_roles`, `users` |
| `GET /branches` | List branches with company name. Optional: `company_id`, `limit`, `offset`. `last_activity` = latest refresh token issued for any user with that branch (proxy for last login/session); fallback: branch `updated_at` | `branches`, `companies`, `user_branch_roles`, `refresh_tokens` |
| `GET /active-users` | active_now, active_last_24h, active_last_7d (from refresh tokens) | `refresh_tokens` |
| `GET /active-users/timeseries?days=14` | Daily active users for charts | `refresh_tokens` (issued_at) |
| `GET /usage-by-company` | Active sessions and token count per company | `refresh_tokens` + `user_branch_roles` + `branches` + `companies` |
| `GET /health` | DB connectivity, server time, status | `SELECT 1` |
| `GET /errors` | Placeholder: failed API calls, auth failures (returns zeros until APM/logging integrated) | — |
| `GET /request-volume` | Placeholder: request volume, peak concurrent users, avg response time (returns empty until middleware added) | — |

- **Database**: All metrics (except placeholders) use the **app DB** (`get_db` / `SessionLocal`): `companies`, `branches`, `users`, `user_branch_roles`, `refresh_tokens`. No tenant/master DB split for metrics; single-DB architecture.
- **Security**: No item-level or transactional data. Counts and aggregates only. Company/branch names and IDs are allowed for operational visibility.

### Adding a new metric

1. **Service** (`backend/app/services/platform_metrics_service.py`):
   - Add a function that accepts `db: Session` and optional query params.
   - Query only aggregated data (counts, sums, grouped by company/branch). Do not select inventory rows or PII beyond what’s already exposed (e.g. company name).
   - Return a dict (or list) suitable for JSON.

2. **Router** (`backend/app/api/admin_metrics.py`):
   - Add `GET /metrics/your-metric` with `Depends(get_current_admin)`, `@limiter.limit("30/minute")`, and `request: Request`.
   - Use `Depends(get_db)` for DB access. Call the new service function and return the result.

3. **Frontend** (`frontend/js/api.js`):
   - Add a method under `API.admin.metrics`, e.g. `yourMetric: (params) => api.get('/api/admin/metrics/your-metric', params)`.

4. **Dashboard** (`frontend/js/pages/admin_dashboard.js`):
   - In `loadDashboard()`, add a `Promise.allSettled` entry for the new API call.
   - Add a section in `renderDashboardSkeleton()` and a render function (e.g. `renderYourMetric(data)`) to display the data.

### Errors and request volume (future)

- **Errors**: To populate `GET /metrics/errors`, add an error-logging middleware or table (e.g. log endpoint, status, company_id, timestamp) and aggregate in the service.
- **Request volume**: To populate `GET /metrics/request-volume`, add middleware that records each request (e.g. company_id from JWT, timestamp, duration) into a table or time-series store, then aggregate by hour/company.

## Frontend

- **Entry**: `admin.html` → tabs “Tenants” and “Platform Dashboard”. Dashboard content is in `#platform-dashboard-mount`, rendered by `admin_dashboard.js`.
- **Charts**: Chart.js (loaded from CDN in `admin.html`) for the “Daily active users” line chart. Data from `GET /api/admin/metrics/active-users/timeseries`.
- **Refresh**: “Refresh” button re-fetches all metrics and re-renders.

## Security summary

- **PLATFORM_ADMIN only**: All metrics routes use `get_current_admin`; company JWT users get 401.
- **Aggregated data only**: No item IDs, no inventory rows, no transaction details.
- **Rate limiting**: 30/min for most metrics, 60/min for health.
