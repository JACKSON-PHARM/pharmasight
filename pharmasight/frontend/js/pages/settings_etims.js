/**
 * eTIMS (KRA OSCU) tenant compliance view.
 *
 * Integrator-grade architecture:
 * - Platform Admin manages all credentials (PIN, BHF ID, device serial, CMC key, environment, test, enable).
 * - Company owners/users only see per-branch compliance status (read-only).
 */

/** Normalize branch_roles from API or cache (objects, or legacy string entries). */
function normalizeBranchRoleNames(branchRoles) {
    if (!branchRoles || !Array.isArray(branchRoles)) return [];
    return branchRoles
        .map((br) => {
            if (typeof br === 'string') return String(br).trim().toLowerCase();
            return String(br.role_name || br.role || '').trim().toLowerCase();
        })
        .filter(Boolean);
}

/** Match backend _user_has_owner_or_admin_role: owner, admin, super admin; plus common UI aliases. */
function roleNamesImplyEtimsAdmin(names) {
    const set = new Set(names.map((n) => n.replace(/\s+/g, ' ').trim()));
    const allowed = ['owner', 'admin', 'super admin', 'administrator', 'superadmin'];
    for (const a of allowed) {
        if (set.has(a)) return true;
    }
    return false;
}

// Credential management is Platform Admin only.
async function userIsEtimsAdmin() { return false; }

function etimsBadgeHtml(status, enabled) {
    const s = (status || 'not_configured').toLowerCase();
    if (!enabled && s === 'disabled') {
        return '<span class="badge badge-secondary" title="eTIMS disabled">eTIMS: Off</span>';
    }
    if (s === 'verified' && enabled) {
        return '<span class="badge badge-success" title="eTIMS verified">eTIMS: Verified</span>';
    }
    if (s === 'failed') {
        return '<span class="badge badge-danger" title="eTIMS test or submit failed">eTIMS: Failed</span>';
    }
    if (s === 'not_tested') {
        return '<span class="badge badge-warning" title="Save credentials and run Test Connection">eTIMS: Not tested</span>';
    }
    if (s === 'not_configured') {
        return '<span class="badge badge-secondary" title="Incomplete credentials">eTIMS: Not configured</span>';
    }
    return '<span class="badge badge-secondary" title="eTIMS">eTIMS</span>';
}

function formatEtimsDate(iso) {
    if (!iso) return '—';
    try {
        const d = new Date(iso);
        return isNaN(d.getTime()) ? '—' : d.toLocaleString();
    } catch (_) {
        return '—';
    }
}

async function renderEtimsSettingsPage() {
    const page = document.getElementById('settings');
    if (!page) return;

    const isAdmin = false;
    let branches = [];
    let company = null;
    let preselectBranch = CONFIG.BRANCH_ID || null;
    try {
        const full = (window.location.hash || '').replace(/^#/, '');
        const qIdx = full.indexOf('?');
        if (qIdx >= 0) {
            const q = new URLSearchParams(full.slice(qIdx + 1));
            const b = q.get('branch');
            if (b) preselectBranch = b;
        }
    } catch (_) {}

    if (CONFIG.COMPANY_ID) {
        try {
            company = await API.company.get(CONFIG.COMPANY_ID);
        } catch (e) {
            console.warn('eTIMS wizard: company load failed', e);
        }
        try {
            branches = await API.branch.list(CONFIG.COMPANY_ID);
        } catch (e) {
            console.warn('eTIMS wizard: branches load failed', e);
        }
    }

    const pinOk = !!(company && String(company.pin || '').trim());

    page.innerHTML = `
        <div class="card">
            <div class="card-header">
                <h3 class="card-title"><i class="fas fa-file-signature"></i> eTIMS (KRA OSCU)</h3>
            </div>
            <div class="card-body">
                <p style="color: var(--text-secondary); margin-bottom: 1.25rem; max-width: 52rem;">
                    Configure per-branch OSCU credentials. Invoices submit to KRA only when eTIMS is <strong>enabled</strong> and <strong>Test Connection</strong> has succeeded (connection verified).
                    Company <strong>KRA PIN</strong> is stored as PIN / Tax ID on the Company profile (used as TIN for OSCU).
                </p>

                <div class="etims-wizard-steps" style="display: grid; gap: 1.25rem; max-width: 52rem;">
                    <div style="border: 1px solid var(--border-color); border-radius: 0.5rem; padding: 1rem;">
                        <h4 style="margin: 0 0 0.5rem 0; font-size: 1rem;"><span class="badge badge-primary" style="margin-right: 0.35rem;">1</span> Company KRA PIN</h4>
                        <p style="margin: 0 0 0.5rem 0; font-size: 0.875rem; color: var(--text-secondary);">
                            ${pinOk ? '<i class="fas fa-check-circle" style="color: var(--success-color);"></i> PIN is set.' : '<i class="fas fa-exclamation-circle" style="color: var(--warning-color);"></i> Set PIN / Tax ID under Settings → Company.'}
                        </p>
                        <button type="button" class="btn btn-outline btn-sm" onclick="if(window.loadSettingsSubPage) window.loadSettingsSubPage('company');">
                            <i class="fas fa-building"></i> Open Company profile
                        </button>
                    </div>

                    <div style="border: 1px solid var(--border-color); border-radius: 0.5rem; padding: 1rem;">
                        <h4 style="margin: 0 0 0.5rem 0; font-size: 1rem;"><span class="badge badge-primary" style="margin-right: 0.35rem;">2</span> Branch</h4>
                        <div class="form-group" style="margin-bottom: 0;">
                            <label class="form-label">Select branch</label>
                            <select id="etimsWizardBranchSelect" class="form-select" ${branches.length ? '' : 'disabled'}>
                                ${branches.length ? branches.map((b) => `<option value="${b.id}" ${String(b.id) === String(preselectBranch) ? 'selected' : ''}>${escapeHtml(b.name)} (${escapeHtml(b.code || '')})</option>`).join('') : '<option value="">No branches</option>'}
                            </select>
                        </div>
                    </div>

                    <div id="etimsWizardBranchPanel" style="border: 1px solid var(--border-color); border-radius: 0.5rem; padding: 1rem;">
                        <p style="color: var(--text-secondary);">Select a branch above.</p>
                    </div>
                </div>
            </div>
        </div>
    `;

    const sel = document.getElementById('etimsWizardBranchSelect');
    const panel = document.getElementById('etimsWizardBranchPanel');
    if (!sel || !panel) return;

    async function reloadBranchPanel() {
        const bid = sel.value;
        if (!bid || !API.etims) {
            panel.innerHTML = '<p style="color: var(--text-secondary);">API not available.</p>';
            return;
        }
        panel.innerHTML = '<p style="color: var(--text-secondary);">Loading…</p>';
        let cred = null;
        try {
            cred = await API.etims.getBranchCredentials(bid);
        } catch (e) {
            panel.innerHTML = `<p class="alert alert-danger" style="margin:0;">${escapeHtml(e.message || 'Failed to load eTIMS status')}</p>`;
            return;
        }

        const st = cred.connection_status || 'not_configured';
        panel.innerHTML = `
            <h4 style="margin: 0 0 0.75rem 0; font-size: 1rem;">Branch eTIMS status</h4>
            <p style="margin: 0 0 0.5rem 0;">${etimsBadgeHtml(st, cred.enabled)}</p>
            <ul style="margin: 0; padding-left: 1.25rem; font-size: 0.875rem; color: var(--text-secondary);">
                <li>Environment: <strong>${escapeHtml(cred.environment || 'sandbox')}</strong></li>
                <li>Last connection test: <strong>${formatEtimsDate(cred.last_tested_at)}</strong></li>
                <li>Submission enabled: <strong>${cred.enabled ? 'Yes' : 'No'}</strong></li>
            </ul>
            <div class="alert alert-info" style="margin-top: 0.75rem;">
                eTIMS credentials are managed by <strong>PharmaSight Platform Admin</strong>. If you need changes, contact support.
            </div>
        `;
        return;
    }

    sel.onchange = function () {
        void reloadBranchPanel();
    };
    await reloadBranchPanel();
}

if (typeof window !== 'undefined') {
    window.renderEtimsSettingsPage = renderEtimsSettingsPage;
    window.userIsEtimsAdmin = userIsEtimsAdmin;
    window.etimsBadgeHtml = etimsBadgeHtml;
    window.normalizeBranchRoleNames = normalizeBranchRoleNames;
    window.roleNamesImplyEtimsAdmin = roleNamesImplyEtimsAdmin;
}
