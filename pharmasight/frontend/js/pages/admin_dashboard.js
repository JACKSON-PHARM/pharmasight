/**
 * Platform Admin Dashboard – usage, health, and engagement metrics.
 * Requires PLATFORM_ADMIN (admin token). Uses API.admin.metrics.* endpoints.
 * Data is aggregated only; no sensitive company/inventory data.
 */
let chartInstance = null;

/**
 * Fetch helper: calls API with admin token, shows error toast on failure.
 */
async function fetchMetrics(apiMethod) {
    if (!window.API?.admin?.metrics?.[apiMethod]) {
        throw new Error('API.admin.metrics not available');
    }
    const fn = window.API.admin.metrics[apiMethod];
    const result = await fn();
    if (result && result.detail && typeof result.detail === 'string' && result.status === 401) {
        throw new Error('Unauthorized. Please log in as platform admin.');
    }
    return result;
}

function showError(msg) {
    if (typeof window.showNotification === 'function') {
        window.showNotification(msg, 'error');
    } else {
        console.error(msg);
    }
}

/**
 * Render summary cards (companies, branches, users, active sessions).
 */
function renderSummary(data) {
    const el = document.getElementById('platform-dashboard-summary');
    if (!el) return;
    if (!data) {
        el.innerHTML = '<p class="text-muted">Loading…</p>';
        return;
    }
    el.innerHTML = `
        <div class="platform-metrics-cards">
            <div class="platform-metric-card">
                <span class="platform-metric-value">${escapeHtml(String(data.companies_count ?? '—'))}</span>
                <span class="platform-metric-label">Companies</span>
            </div>
            <div class="platform-metric-card">
                <span class="platform-metric-value">${escapeHtml(String(data.branches_count ?? '—'))}</span>
                <span class="platform-metric-label">Active branches</span>
            </div>
            <div class="platform-metric-card">
                <span class="platform-metric-value">${escapeHtml(String(data.users_count ?? '—'))}</span>
                <span class="platform-metric-label">Users</span>
            </div>
            <div class="platform-metric-card platform-metric-card--highlight">
                <span class="platform-metric-value">${escapeHtml(String(data.active_sessions_now ?? '—'))}</span>
                <span class="platform-metric-label">Active sessions (now)</span>
            </div>
        </div>
        ${data.generated_at ? `<p class="platform-metrics-meta">Generated: ${escapeHtml(data.generated_at)}</p>` : ''}
    `;
}

/**
 * Render active users snapshot (now, 24h, 7d).
 */
function renderActiveUsers(data) {
    const el = document.getElementById('platform-dashboard-active-users');
    if (!el) return;
    if (!data) {
        el.innerHTML = '<p class="text-muted">Loading…</p>';
        return;
    }
    el.innerHTML = `
        <div class="platform-metrics-cards platform-metrics-cards--small">
            <div class="platform-metric-card">
                <span class="platform-metric-value">${escapeHtml(String(data.active_now ?? '—'))}</span>
                <span class="platform-metric-label">Active now</span>
            </div>
            <div class="platform-metric-card">
                <span class="platform-metric-value">${escapeHtml(String(data.active_last_24h ?? '—'))}</span>
                <span class="platform-metric-label">Last 24h</span>
            </div>
            <div class="platform-metric-card">
                <span class="platform-metric-value">${escapeHtml(String(data.active_last_7d ?? '—'))}</span>
                <span class="platform-metric-label">Last 7 days</span>
            </div>
        </div>
    `;
}

/**
 * Render DAU time series chart (Chart.js).
 */
function renderActiveUsersChart(series) {
    const canvas = document.getElementById('platform-dashboard-chart');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    if (chartInstance) {
        chartInstance.destroy();
        chartInstance = null;
    }

    const labels = (series || []).map((d) => d.date);
    const values = (series || []).map((d) => d.active_users);

    if (labels.length === 0) {
        canvas.parentElement.innerHTML = '<p class="text-muted">No daily data yet. Data comes from refresh token activity.</p>';
        return;
    }

    if (typeof Chart === 'undefined') {
        canvas.parentElement.innerHTML = '<p class="text-muted">Chart.js not loaded. Add script tag for Chart.js.</p>';
        return;
    }

    chartInstance = new Chart(ctx, {
        type: 'line',
        data: {
            labels,
            datasets: [{
                label: 'Daily active users',
                data: values,
                borderColor: 'rgb(20, 184, 166)',
                backgroundColor: 'rgba(20, 184, 166, 0.1)',
                fill: true,
                tension: 0.2,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
            },
            scales: {
                y: { beginAtZero: true },
            },
        },
    });
}

/**
 * Render companies table from metrics/companies.
 */
function renderCompaniesTable(companies, total) {
    const el = document.getElementById('platform-dashboard-companies-body');
    if (!el) return;
    if (!Array.isArray(companies)) {
        el.innerHTML = '<tr><td colspan="4" class="text-center text-muted">Loading…</td></tr>';
        return;
    }
    if (companies.length === 0) {
        el.innerHTML = '<tr><td colspan="4" class="text-center text-muted">No companies</td></tr>';
        return;
    }
    el.innerHTML = companies
        .map(
            (c) => `
        <tr>
            <td>${escapeHtml(c.name || '—')}</td>
            <td>${escapeHtml(String(c.branch_count ?? 0))}</td>
            <td>${escapeHtml(String(c.user_count ?? 0))}</td>
            <td>${escapeHtml(c.created_at ? new Date(c.created_at).toLocaleDateString() : '—')}</td>
        </tr>
    `
        )
        .join('');
    const totalEl = document.getElementById('platform-dashboard-companies-total');
    if (totalEl) totalEl.textContent = total != null ? total : companies.length;
}

/**
 * Render branches table from metrics/branches.
 */
function renderBranchesTable(branches, total) {
    const el = document.getElementById('platform-dashboard-branches-body');
    if (!el) return;
    if (!Array.isArray(branches)) {
        el.innerHTML = '<tr><td colspan="5" class="text-center text-muted">Loading…</td></tr>';
        return;
    }
    if (branches.length === 0) {
        el.innerHTML = '<tr><td colspan="5" class="text-center text-muted">No branches</td></tr>';
        return;
    }
    el.innerHTML = branches
        .map(
            (b) => `
        <tr>
            <td>${escapeHtml(b.company_name || '—')}</td>
            <td>${escapeHtml(b.name || '—')}</td>
            <td>${escapeHtml(b.code || '—')}</td>
            <td>${b.last_activity ? escapeHtml(new Date(b.last_activity).toLocaleString()) : '—'}</td>
            <td>${b.is_active ? 'Yes' : 'No'}</td>
        </tr>
    `
        )
        .join('');
    const totalEl = document.getElementById('platform-dashboard-branches-total');
    if (totalEl) totalEl.textContent = total != null ? total : branches.length;
}

/**
 * Render usage-by-company table (sessions per company).
 */
function renderUsageByCompany(companies) {
    const el = document.getElementById('platform-dashboard-usage-body');
    if (!el) return;
    if (!Array.isArray(companies)) {
        el.innerHTML = '<tr><td colspan="3" class="text-center text-muted">Loading…</td></tr>';
        return;
    }
    if (companies.length === 0) {
        el.innerHTML = '<tr><td colspan="3" class="text-center text-muted">No data</td></tr>';
        return;
    }
    el.innerHTML = companies
        .map(
            (c) => `
        <tr>
            <td>${escapeHtml(c.company_name || '—')}</td>
            <td>${escapeHtml(String(c.active_sessions ?? 0))}</td>
            <td>${escapeHtml(String(c.total_token_count ?? 0))}</td>
        </tr>
    `
        )
        .join('');
}

/**
 * Render health status card.
 */
function renderHealth(data) {
    const el = document.getElementById('platform-dashboard-health');
    if (!el) return;
    if (!data) {
        el.innerHTML = '<p class="text-muted">Loading…</p>';
        return;
    }
    const status = data.status === 'healthy' ? 'healthy' : 'degraded';
    el.innerHTML = `
        <div class="platform-health-status platform-health-status--${status}">
            <span class="platform-health-dot"></span>
            <span>${escapeHtml(data.status || 'unknown')}</span>
        </div>
        <p class="platform-metrics-meta">Database: ${data.database_connected ? 'Connected' : 'Disconnected'}</p>
        <p class="platform-metrics-meta">Server time: ${escapeHtml(data.server_time_utc || '—')}</p>
    `;
}

/**
 * Render errors placeholder (backend returns empty structure until APM integrated).
 */
function renderErrors(data) {
    const el = document.getElementById('platform-dashboard-errors');
    if (!el) return;
    if (!data) {
        el.innerHTML = '<p class="text-muted">Loading…</p>';
        return;
    }
    el.innerHTML = `
        <p><strong>Auth failures (24h):</strong> ${escapeHtml(String(data.auth_failures_24h ?? 0))}</p>
        <p><strong>Server errors (24h):</strong> ${escapeHtml(String(data.server_errors_24h ?? 0))}</p>
        ${data.message ? `<p class="text-muted small">${escapeHtml(data.message)}</p>` : ''}
    `;
}

/**
 * Render request volume placeholder.
 */
function renderRequestVolume(data) {
    const el = document.getElementById('platform-dashboard-request-volume');
    if (!el) return;
    if (!data) {
        el.innerHTML = '<p class="text-muted">Loading…</p>';
        return;
    }
    el.innerHTML = `
        <p><strong>Peak concurrent users:</strong> ${escapeHtml(String(data.peak_concurrent_users ?? 0))}</p>
        <p><strong>Avg response time:</strong> ${data.avg_response_time_ms != null ? escapeHtml(String(data.avg_response_time_ms) + ' ms') : '—'}</p>
        ${data.message ? `<p class="text-muted small">${escapeHtml(data.message)}</p>` : ''}
    `;
}

function escapeHtml(s) {
    if (s == null) return '';
    const div = document.createElement('div');
    div.textContent = s;
    return div.innerHTML;
}

/**
 * Load all metrics and render dashboard. Call on tab switch and refresh.
 */
export async function loadDashboard() {
    const container = document.getElementById('platform-dashboard-content');
    if (!container) return;

    const setLoading = (loading) => {
        container.querySelectorAll('.platform-dashboard-loading').forEach((el) => {
            el.style.visibility = loading ? 'visible' : 'hidden';
        });
    };

    setLoading(true);
    try {
        const [summary, companiesRes, branchesRes, activeUsers, activeUsersTs, usageRes, health, errors, requestVolume] = await Promise.allSettled([
            fetchMetrics('summary'),
            fetchMetrics('companies').then((r) => r),
            fetchMetrics('branches').then((r) => r),
            fetchMetrics('activeUsers'),
            fetchMetrics('activeUsersTimeseries').then((r) => r).catch(() => ({ series: [] })),
            fetchMetrics('usageByCompany'),
            fetchMetrics('health'),
            fetchMetrics('errors'),
            fetchMetrics('requestVolume'),
        ]);

        if (summary.status === 'rejected') {
            showError(summary.reason?.message || 'Failed to load summary');
            return;
        }
        renderSummary(summary.value);
        renderActiveUsers(activeUsers.status === 'fulfilled' ? activeUsers.value : null);
        renderActiveUsersChart(activeUsersTs.status === 'fulfilled' && activeUsersTs.value?.series ? activeUsersTs.value.series : []);

        if (companiesRes.status === 'fulfilled' && companiesRes.value) {
            renderCompaniesTable(companiesRes.value.companies || [], companiesRes.value.total);
        }
        if (branchesRes.status === 'fulfilled' && branchesRes.value) {
            renderBranchesTable(branchesRes.value.branches || [], branchesRes.value.total);
        }
        renderUsageByCompany(usageRes.status === 'fulfilled' && usageRes.value ? (usageRes.value.companies || usageRes.value) : null);
        renderHealth(health.status === 'fulfilled' ? health.value : null);
        renderErrors(errors.status === 'fulfilled' ? errors.value : null);
        renderRequestVolume(requestVolume.status === 'fulfilled' ? requestVolume.value : null);
    } catch (e) {
        showError(e?.message || 'Failed to load dashboard');
    } finally {
        setLoading(false);
    }
}

/**
 * Build dashboard DOM and mount into #platform-dashboard-mount.
 * Call once when dashboard tab is first shown.
 */
export function renderDashboardSkeleton() {
    const mount = document.getElementById('platform-dashboard-mount');
    if (!mount || mount.querySelector('#platform-dashboard-content')) return;

    mount.innerHTML = `
        <div id="platform-dashboard-content" class="platform-dashboard">
            <div class="platform-dashboard-loading" style="position:absolute;top:8px;right:12px;visibility:hidden;">Updating…</div>
            <h2 class="platform-dashboard-title">Platform metrics</h2>
            <p class="platform-dashboard-subtitle">Aggregated usage and health. No item-level or transactional data.</p>

            <section class="platform-dashboard-section">
                <h3>Summary</h3>
                <div id="platform-dashboard-summary">Loading…</div>
            </section>

            <section class="platform-dashboard-section">
                <h3>Active users</h3>
                <div id="platform-dashboard-active-users">Loading…</div>
                <div class="platform-dashboard-chart-wrap" style="height: 220px;">
                    <canvas id="platform-dashboard-chart"></canvas>
                </div>
            </section>

            <section class="platform-dashboard-section">
                <h3>Companies</h3>
                <p class="platform-metrics-meta">Total: <span id="platform-dashboard-companies-total">0</span></p>
                <div class="table-container">
                    <table>
                        <thead><tr><th>Name</th><th>Branches</th><th>Users</th><th>Created</th></tr></thead>
                        <tbody id="platform-dashboard-companies-body"></tbody>
                    </table>
                </div>
            </section>

            <section class="platform-dashboard-section">
                <h3>Branches</h3>
                <p class="platform-metrics-meta">Total: <span id="platform-dashboard-branches-total">0</span></p>
                <div class="table-container">
                    <table>
                        <thead><tr><th>Company</th><th>Branch</th><th>Code</th><th>Last activity</th><th>Active</th></tr></thead>
                        <tbody id="platform-dashboard-branches-body"></tbody>
                    </table>
                </div>
            </section>

            <section class="platform-dashboard-section">
                <h3>Usage by company (sessions)</h3>
                <div class="table-container">
                    <table>
                        <thead><tr><th>Company</th><th>Active sessions</th><th>Token count</th></tr></thead>
                        <tbody id="platform-dashboard-usage-body"></tbody>
                    </table>
                </div>
            </section>

            <div class="platform-dashboard-grid-2">
                <section class="platform-dashboard-section">
                    <h3>System health</h3>
                    <div id="platform-dashboard-health">Loading…</div>
                </section>
                <section class="platform-dashboard-section">
                    <h3>Errors (placeholder)</h3>
                    <div id="platform-dashboard-errors">Loading…</div>
                </section>
                <section class="platform-dashboard-section">
                    <h3>Request volume (placeholder)</h3>
                    <div id="platform-dashboard-request-volume">Loading…</div>
                </section>
            </div>

            <div class="platform-dashboard-actions">
                <button type="button" class="btn btn-primary" id="platform-dashboard-refresh">Refresh</button>
            </div>
        </div>
    `;

    const refreshBtn = document.getElementById('platform-dashboard-refresh');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', () => loadDashboard());
    }
}

/**
 * Init dashboard: ensure skeleton exists, then load data.
 * Called when user switches to "Platform Dashboard" tab.
 */
export async function init() {
    renderDashboardSkeleton();
    await loadDashboard();
}
