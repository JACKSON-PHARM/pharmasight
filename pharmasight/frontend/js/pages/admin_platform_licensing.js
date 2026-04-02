/**
 * Platform Admin (admin.html): Licensing / module control UI.
 *
 * Uses admin auth (admin_token) to call /api/admin/platform-licensing/* endpoints,
 * so platform ops stay inside admin.html without requiring an app user session.
 */

const LIC_SEARCH_STORAGE_KEY = 'pharmasight_admin_lic_search';
/** Prevents stale list responses (e.g. initial full list finishing after a search) from overwriting the table. */
let _licListLoadSeq = 0;

function readLastLicSearch() {
    try {
        return (sessionStorage.getItem(LIC_SEARCH_STORAGE_KEY) || '').trim();
    } catch (_) {
        return '';
    }
}

function saveLastLicSearch(q) {
    try {
        sessionStorage.setItem(LIC_SEARCH_STORAGE_KEY, (q || '').trim());
    } catch (_) {}
}

export async function init() {
    const mount = document.getElementById('platform-licensing-mount');
    if (!mount) return;

    mount.innerHTML = `
        <div class="card" style="padding:16px;">
            <h2 style="margin:0 0 8px 0;">Licensing</h2>
            <p style="margin:0; color:#666;">Loading…</p>
        </div>
    `;

    const esc = (s) => {
        const d = document.createElement('div');
        d.textContent = s == null ? '' : String(s);
        return d.innerHTML;
    };

    const toast = (msg, type) => {
        if (typeof window.showNotification === 'function') window.showNotification(msg, type || 'info');
        else console.log(msg);
    };

    const api = window.API?.admin?.platformLicensing;
    if (!api) {
        mount.innerHTML = `
            <div class="card" style="padding:16px;">
                <h2 style="margin:0 0 8px 0;">Licensing</h2>
                <p style="margin:0; color:#b91c1c;">API client not loaded for platform licensing.</p>
            </div>
        `;
        return;
    }

    async function loadCompanies(q) {
        const qNorm = typeof q === 'string' ? q.trim() : '';
        saveLastLicSearch(qNorm);
        const seq = ++_licListLoadSeq;

        mount.innerHTML = `
            <div class="card" style="padding:16px;">
                <div style="display:flex; align-items:center; justify-content:space-between; gap:12px; flex-wrap:wrap;">
                    <div>
                        <h2 style="margin:0;">Licensing · Companies</h2>
                        <div style="color:#666; font-size:0.9rem; margin-top:4px;">Search by name, then open a company to toggle modules and subscription.</div>
                    </div>
                    <div style="display:flex; gap:8px; align-items:center;">
                        <input id="lic-search" type="search" autocomplete="off" value="${esc(qNorm)}" placeholder="Search company…" style="padding:8px 10px; border:1px solid #e2e8f0; border-radius:8px; min-width:220px;">
                        <button type="button" id="lic-search-btn" class="btn btn-secondary">Search</button>
                    </div>
                </div>
                <div style="overflow:auto; margin-top:12px;">
                    <table style="width:100%; border-collapse:collapse;">
                        <thead>
                            <tr>
                                <th style="text-align:left; padding:10px; border-bottom:1px solid #eee;">Company</th>
                                <th style="text-align:left; padding:10px; border-bottom:1px solid #eee;">Plan</th>
                                <th style="text-align:left; padding:10px; border-bottom:1px solid #eee;">Status</th>
                                <th style="text-align:left; padding:10px; border-bottom:1px solid #eee;">Trial expires</th>
                                <th style="text-align:left; padding:10px; border-bottom:1px solid #eee;">Active</th>
                                <th style="text-align:left; padding:10px; border-bottom:1px solid #eee;">Actions</th>
                            </tr>
                        </thead>
                        <tbody id="lic-tbody">
                            <tr><td colspan="6" style="padding:12px; color:#666;">Loading…</td></tr>
                        </tbody>
                    </table>
                </div>
            </div>
        `;

        const tbody = document.getElementById('lic-tbody');
        try {
            const listRaw = await api.companies(qNorm ? { q: qNorm } : {}, { _skipDedupe: true });
            if (seq !== _licListLoadSeq) return;

            let list = Array.isArray(listRaw) ? listRaw : [];
            if (qNorm) {
                const ql = qNorm.toLowerCase();
                list = list.filter((c) => (c.name || '').toLowerCase().includes(ql));
            }

            const rows = list.map((c) => {
                const active = c.is_active ? '<span style="color:#16a34a; font-weight:600;">Yes</span>' : '<span style="color:#dc2626; font-weight:600;">No</span>';
                const cid = esc(c.id);
                return `
                    <tr data-cid="${cid}" style="cursor:pointer;">
                        <td style="padding:10px; border-bottom:1px solid #f1f5f9;">${esc(c.name || '—')}</td>
                        <td style="padding:10px; border-bottom:1px solid #f1f5f9;">${esc(c.subscription_plan || '—')}</td>
                        <td style="padding:10px; border-bottom:1px solid #f1f5f9;">${esc(c.subscription_status || '—')}</td>
                        <td style="padding:10px; border-bottom:1px solid #f1f5f9;">${esc(c.trial_expires_at ? new Date(c.trial_expires_at).toLocaleString() : '—')}</td>
                        <td style="padding:10px; border-bottom:1px solid #f1f5f9;">${active}</td>
                        <td style="padding:10px; border-bottom:1px solid #f1f5f9; white-space:nowrap;">
                            <button type="button" class="btn btn-primary btn-sm lic-open-manage" data-cid="${cid}">Manage</button>
                        </td>
                    </tr>
                `;
            }).join('');
            if (seq !== _licListLoadSeq) return;
            tbody.innerHTML = rows || '<tr><td colspan="6" style="padding:12px; color:#666;">No companies match.</td></tr>';

            tbody.addEventListener('click', (e) => {
                const btn = e.target.closest('.lic-open-manage');
                if (btn) {
                    e.preventDefault();
                    e.stopPropagation();
                    const id = btn.getAttribute('data-cid');
                    if (id) void loadCompanyDetail(id);
                    return;
                }
                const tr = e.target.closest('tr[data-cid]');
                if (tr) {
                    const id = tr.getAttribute('data-cid');
                    if (id) void loadCompanyDetail(id);
                }
            });
        } catch (e) {
            if (seq !== _licListLoadSeq) return;
            tbody.innerHTML = `<tr><td colspan="6" style="padding:12px; color:#b91c1c;">Failed: ${esc(e.message || 'Error')}</td></tr>`;
        }

        if (seq !== _licListLoadSeq) return;

        const runSearch = () => {
            const v = (document.getElementById('lic-search')?.value || '').trim();
            void loadCompanies(v);
        };

        document.getElementById('lic-search-btn')?.addEventListener('click', runSearch);
        document.getElementById('lic-search')?.addEventListener('keydown', (ev) => {
            if (ev.key === 'Enter') {
                ev.preventDefault();
                runSearch();
            }
        });
    }

    function toLocalDatetimeValue(iso) {
        if (!iso) return '';
        try {
            const d = new Date(iso);
            const pad = (n) => String(n).padStart(2, '0');
            return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
        } catch (_) {
            return '';
        }
    }

    function fromLocalDatetimeValue(v) {
        const s = String(v || '').trim();
        if (!s) return null;
        try {
            return new Date(s).toISOString();
        } catch (_) {
            return null;
        }
    }

    const MODULE_DISPLAY = {
        pharmacy: 'Pharmacy',
        inventory: 'Inventory',
        finance: 'Finance',
        procurement: 'Procurement',
        pos: 'Point of sale',
        billing: 'Billing',
        clinic: 'Clinic',
        patients: 'Patients',
        opd: 'OPD',
        prescriptions: 'Prescriptions',
        lab: 'Laboratory',
        radiology: 'Radiology',
        ipd: 'IPD',
        emr: 'EMR',
    };

    function moduleDisplayName(name) {
        const n = String(name || '').toLowerCase();
        if (MODULE_DISPLAY[n]) return MODULE_DISPLAY[n];
        return n.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
    }

    function etimsBadge(status, enabled) {
        const s = String(status || 'not_configured').toLowerCase();
        if (!enabled && s === 'disabled') return '<span class="badge badge-secondary">Off</span>';
        if (s === 'verified' && enabled) return '<span class="badge badge-success">Verified</span>';
        if (s === 'verified') return '<span class="badge badge-warning">Verified (not enabled)</span>';
        if (s === 'failed') return '<span class="badge badge-danger">Failed</span>';
        if (s === 'not_tested') return '<span class="badge badge-warning">Not tested</span>';
        if (s === 'not_configured') return '<span class="badge badge-secondary">Not configured</span>';
        return `<span class="badge badge-secondary">${esc(s)}</span>`;
    }

    function fmtIso(iso) {
        if (!iso) return '—';
        try {
            const d = new Date(iso);
            return isNaN(d.getTime()) ? '—' : d.toLocaleString();
        } catch (_) {
            return '—';
        }
    }

    async function loadCompanyDetail(companyId) {
        mount.innerHTML = `
            <div class="card" style="padding:16px;">
                <h2 style="margin:0 0 8px 0;">Company</h2>
                <p style="margin:0; color:#666;">Loading…</p>
            </div>
        `;
        try {
            const [resp, etims] = await Promise.all([
                api.company(companyId),
                (typeof api.etimsCompany === 'function' ? api.etimsCompany(companyId) : Promise.resolve(null)).catch(() => null),
            ]);
            const c = resp.company || {};
            const core = new Set((resp.core_modules || []).map((x) => String(x).toLowerCase()));
            const mods = Array.isArray(resp.modules) ? resp.modules : [];
            const catalog = Array.isArray(resp.module_catalog) ? resp.module_catalog : [];

            const enabled = new Set(mods.filter((m) => m && m.enabled).map((m) => String(m.name || '').toLowerCase()).filter(Boolean));
            const nonCore = mods.map((m) => String(m.name || '').toLowerCase()).filter((n) => n && !core.has(n));

            const isClinical = (name) =>
                ['clinic', 'patients', 'opd', 'prescriptions', 'lab', 'radiology', 'ipd', 'emr'].includes(name);

            let business = [];
            let clinical = [];
            let other = [];
            if (catalog.length) {
                catalog.forEach((row) => {
                    if (!row || !row.name) return;
                    const cat = String(row.category || 'business').toLowerCase();
                    if (cat === 'clinical') clinical.push(row);
                    else if (cat === 'business') business.push(row);
                    else other.push(row);
                });
                const byName = (a, b) => String(a.name).localeCompare(String(b.name));
                business.sort(byName);
                clinical.sort(byName);
                other.sort(byName);
            } else {
                business = nonCore.filter((n) => !isClinical(n)).sort().map((name) => ({ name, enabled: enabled.has(name) }));
                clinical = nonCore.filter((n) => isClinical(n)).sort().map((name) => ({ name, enabled: enabled.has(name) }));
            }

            const renderToggle = (item) => {
                const name = String(item.name || '').toLowerCase();
                const on = catalog.length ? item.enabled === true : enabled.has(name);
                return `
                <label style="display:flex; gap:8px; align-items:center; padding:4px 0;">
                    <input type="checkbox" data-mod="${esc(name)}" ${on ? 'checked' : ''}>
                    <span>${esc(moduleDisplayName(name))}</span>
                </label>
            `;
            };

            mount.innerHTML = `
                <div class="card" style="padding:16px;">
                    <div style="display:flex; align-items:center; justify-content:space-between; gap:12px; flex-wrap:wrap;">
                        <div>
                            <h2 style="margin:0;">${esc(c.name || 'Company')}</h2>
                            <div style="margin-top:4px; color:#666; font-size:0.9rem;"><code>${esc(companyId)}</code></div>
                        </div>
                        <button id="lic-back" class="btn btn-secondary">← Back</button>
                    </div>

                    <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap:16px; margin-top:16px;">
                        <div style="border:1px solid #e2e8f0; border-radius:10px; padding:12px;">
                            <h3 style="margin:0 0 10px 0;">Subscription</h3>
                            <label style="display:block; font-weight:600; margin-bottom:6px;">Plan</label>
                            <input id="lic-plan" value="${esc(c.subscription_plan || '')}" style="width:100%; padding:8px 10px; border:1px solid #e2e8f0; border-radius:8px;">
                            <label style="display:block; font-weight:600; margin:10px 0 6px 0;">Status</label>
                            <input id="lic-status" value="${esc(c.subscription_status || '')}" style="width:100%; padding:8px 10px; border:1px solid #e2e8f0; border-radius:8px;">
                            <label style="display:block; font-weight:600; margin:10px 0 6px 0;">Trial expires</label>
                            <input id="lic-trial" type="datetime-local" value="${esc(toLocalDatetimeValue(c.trial_expires_at))}" style="width:100%; padding:8px 10px; border:1px solid #e2e8f0; border-radius:8px;">
                            <button id="lic-save-sub" class="btn btn-primary" style="margin-top:12px;">Save subscription</button>
                        </div>

                        <div style="border:1px solid #e2e8f0; border-radius:10px; padding:12px;">
                            <h3 style="margin:0 0 10px 0;">Status</h3>
                            <label style="display:flex; gap:8px; align-items:center;">
                                <input id="lic-active" type="checkbox" ${c.is_active ? 'checked' : ''}>
                                <span>Company is active</span>
                            </label>
                            <button id="lic-save-active" class="btn btn-primary" style="margin-top:12px;">Save status</button>
                        </div>
                    </div>

                    <div style="border:1px solid #e2e8f0; border-radius:10px; padding:12px; margin-top:16px;">
                        <h3 style="margin:0 0 10px 0;">Modules</h3>
                        <p style="margin:0 0 10px 0; color:#666; font-size:0.9rem;">
                            Core capabilities (settings, reports, users, dashboard, etc.) stay on for every company. Toggle licensed add-ons below; saving writes explicit rows in company modules.
                        </p>
                        <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap:16px;">
                            <div>
                                <div style="font-weight:700; margin-bottom:6px;">Business</div>
                                ${business.length ? business.map(renderToggle).join('') : '<div style="color:#666;">None</div>'}
                            </div>
                            <div>
                                <div style="font-weight:700; margin-bottom:6px;">Clinical</div>
                                ${clinical.length ? clinical.map(renderToggle).join('') : '<div style="color:#666;">None</div>'}
                            </div>
                            ${
                                other.length
                                    ? `<div style="grid-column:1/-1;">
                                <div style="font-weight:700; margin-bottom:6px;">Other</div>
                                ${other.map(renderToggle).join('')}
                            </div>`
                                    : ''
                            }
                        </div>
                        <button id="lic-save-mods" class="btn btn-primary" style="margin-top:12px;">Save modules</button>
                    </div>

                    <div style="border:1px solid #e2e8f0; border-radius:10px; padding:12px; margin-top:16px;">
                        <h3 style="margin:0 0 10px 0;">eTIMS (KRA OSCU)</h3>
                        <p style="margin:0 0 10px 0; color:#666; font-size:0.9rem;">
                            Platform Admin manages per-branch eTIMS credentials. Company owners only see a status badge in-app.
                        </p>
                        <div style="display:flex; gap:10px; align-items:flex-end; flex-wrap:wrap; margin-bottom:12px;">
                            <div style="min-width:260px; flex: 1 1 320px;">
                                <label style="display:block; font-weight:600; margin-bottom:6px;">Company PIN (TIN)</label>
                                <input id="lic-etims-pin" value="${esc((etims && etims.company_pin) || c.pin || '')}" placeholder="e.g. P123456789A" style="width:100%; padding:8px 10px; border:1px solid #e2e8f0; border-radius:8px;">
                            </div>
                            <button id="lic-etims-save-pin" class="btn btn-secondary">Save PIN</button>
                        </div>

                        ${
                            etims && Array.isArray(etims.branches) && etims.branches.length
                                ? `<div style="overflow:auto;">
                            <table style="width:100%; border-collapse:collapse;">
                                <thead>
                                    <tr>
                                        <th style="text-align:left; padding:10px; border-bottom:1px solid #eee;">Branch</th>
                                        <th style="text-align:left; padding:10px; border-bottom:1px solid #eee;">Env</th>
                                        <th style="text-align:left; padding:10px; border-bottom:1px solid #eee;">BHF ID</th>
                                        <th style="text-align:left; padding:10px; border-bottom:1px solid #eee;">Device serial</th>
                                        <th style="text-align:left; padding:10px; border-bottom:1px solid #eee;">CMC key</th>
                                        <th style="text-align:left; padding:10px; border-bottom:1px solid #eee;">Status</th>
                                        <th style="text-align:left; padding:10px; border-bottom:1px solid #eee;">Last test</th>
                                        <th style="text-align:left; padding:10px; border-bottom:1px solid #eee;">Enabled</th>
                                        <th style="text-align:left; padding:10px; border-bottom:1px solid #eee;">Actions</th>
                                    </tr>
                                </thead>
                                <tbody>
                                ${etims.branches
                                    .map((b) => {
                                        const bid = esc(b.branch_id);
                                        const st = String(b.connection_status || 'not_configured');
                                        const verified = st.toLowerCase() === 'verified';
                                        return `
                                    <tr data-etims-branch="${bid}">
                                        <td style="padding:10px; border-bottom:1px solid #f1f5f9;">
                                            <div style="font-weight:600;">${esc(b.branch_name || '—')}</div>
                                            <div style="color:#666; font-size:0.85rem;">${esc(b.branch_code || '')}</div>
                                        </td>
                                        <td style="padding:10px; border-bottom:1px solid #f1f5f9;">
                                            <select data-etims-env style="padding:6px 8px; border:1px solid #e2e8f0; border-radius:8px;">
                                                <option value="sandbox" ${String(b.environment || 'sandbox') === 'sandbox' ? 'selected' : ''}>sandbox</option>
                                                <option value="production" ${String(b.environment || '') === 'production' ? 'selected' : ''}>production</option>
                                            </select>
                                        </td>
                                        <td style="padding:10px; border-bottom:1px solid #f1f5f9;"><input data-etims-bhf value="${esc(b.kra_bhf_id || '')}" style="width:160px; padding:6px 8px; border:1px solid #e2e8f0; border-radius:8px;"></td>
                                        <td style="padding:10px; border-bottom:1px solid #f1f5f9;"><input data-etims-dvc value="${esc(b.device_serial || '')}" style="width:190px; padding:6px 8px; border:1px solid #e2e8f0; border-radius:8px;"></td>
                                        <td style="padding:10px; border-bottom:1px solid #f1f5f9;">
                                            <input data-etims-cmc type="password" value="" placeholder="${b.has_cmc_key ? '•••••••• (stored)' : 'paste key'}" style="width:170px; padding:6px 8px; border:1px solid #e2e8f0; border-radius:8px;">
                                        </td>
                                        <td style="padding:10px; border-bottom:1px solid #f1f5f9;">${etimsBadge(st, !!b.enabled)}</td>
                                        <td style="padding:10px; border-bottom:1px solid #f1f5f9; color:#666; font-size:0.9rem;">${esc(fmtIso(b.last_tested_at))}</td>
                                        <td style="padding:10px; border-bottom:1px solid #f1f5f9;">
                                            <label style="display:flex; gap:6px; align-items:center;">
                                                <input data-etims-enabled type="checkbox" ${b.enabled ? 'checked' : ''} ${verified ? '' : 'disabled'} />
                                                <span style="color:#666; font-size:0.9rem;">On</span>
                                            </label>
                                        </td>
                                        <td style="padding:10px; border-bottom:1px solid #f1f5f9; white-space:nowrap;">
                                            <button type="button" class="btn btn-secondary btn-sm" data-etims-save>Save</button>
                                            <button type="button" class="btn btn-primary btn-sm" data-etims-test ${b.has_oauth_config ? '' : 'disabled'}>Test</button>
                                        </td>
                                    </tr>
                                `;
                                    })
                                    .join('')}
                                </tbody>
                            </table>
                        </div>
                        <div style="margin-top:10px; color:#64748b; font-size:0.85rem;">
                            “Enabled” can only be turned on after the branch is <strong>Verified</strong> (Test Connection success).
                        </div>`
                                : `<div style="color:#666;">No branches found (or eTIMS endpoint unavailable).</div>`
                        }
                    </div>
                </div>
            `;

            document.getElementById('lic-back')?.addEventListener('click', () => void loadCompanies());

            document.getElementById('lic-etims-save-pin')?.addEventListener('click', async () => {
                try {
                    const pin = (document.getElementById('lic-etims-pin')?.value || '').trim() || null;
                    if (typeof api.etimsPatchCompanyPin !== 'function') throw new Error('eTIMS API not available');
                    await api.etimsPatchCompanyPin(companyId, { pin });
                    toast('Saved eTIMS PIN', 'success');
                    await loadCompanyDetail(companyId);
                } catch (e) {
                    toast(e.message || 'Failed to save PIN', 'error');
                }
            });

            // eTIMS row actions (save + test)
            mount.querySelectorAll('tr[data-etims-branch]').forEach((tr) => {
                const branchId = tr.getAttribute('data-etims-branch');
                const saveBtn = tr.querySelector('[data-etims-save]');
                const testBtn = tr.querySelector('[data-etims-test]');
                const runSave = async () => {
                    if (!branchId) return;
                    if (typeof api.etimsPatchBranch !== 'function') throw new Error('eTIMS API not available');
                    const environment = tr.querySelector('[data-etims-env]')?.value || null;
                    const kra_bhf_id = (tr.querySelector('[data-etims-bhf]')?.value || '').trim() || null;
                    const device_serial = (tr.querySelector('[data-etims-dvc]')?.value || '').trim() || null;
                    const cmc_key = (tr.querySelector('[data-etims-cmc]')?.value || '').trim() || null;
                    const enabled = !!tr.querySelector('[data-etims-enabled]')?.checked;
                    await api.etimsPatchBranch(branchId, { environment, kra_bhf_id, device_serial, cmc_key, enabled });
                    toast('Saved branch eTIMS', 'success');
                    await loadCompanyDetail(companyId);
                };
                const runTest = async () => {
                    if (!branchId) return;
                    if (typeof api.etimsTestBranchConnection !== 'function') throw new Error('eTIMS API not available');
                    toast('Testing eTIMS connection…', 'info');
                    await api.etimsTestBranchConnection(branchId);
                    toast('eTIMS test done', 'success');
                    await loadCompanyDetail(companyId);
                };
                saveBtn?.addEventListener('click', async (ev) => {
                    ev.preventDefault();
                    try {
                        await runSave();
                    } catch (e) {
                        toast(e.message || 'Failed to save branch eTIMS', 'error');
                    }
                });
                testBtn?.addEventListener('click', async (ev) => {
                    ev.preventDefault();
                    try {
                        await runTest();
                    } catch (e) {
                        toast(e.message || 'Failed to test connection', 'error');
                    }
                });
            });

            document.getElementById('lic-save-sub')?.addEventListener('click', async () => {
                try {
                    const subscription_plan = (document.getElementById('lic-plan')?.value || '').trim() || null;
                    const subscription_status = (document.getElementById('lic-status')?.value || '').trim() || null;
                    const trial_expires_at = fromLocalDatetimeValue(document.getElementById('lic-trial')?.value || '');
                    await api.patchSubscription(companyId, { subscription_plan, subscription_status, trial_expires_at });
                    toast('Saved subscription', 'success');
                } catch (e) {
                    toast(e.message || 'Failed', 'error');
                }
            });

            document.getElementById('lic-save-active')?.addEventListener('click', async () => {
                try {
                    const is_active = !!document.getElementById('lic-active')?.checked;
                    await api.patchStatus(companyId, { is_active });
                    toast('Saved status', 'success');
                } catch (e) {
                    toast(e.message || 'Failed', 'error');
                }
            });

            document.getElementById('lic-save-mods')?.addEventListener('click', async () => {
                try {
                    const modules = [];
                    mount.querySelectorAll('input[data-mod]').forEach((cb) => {
                        modules.push({ name: cb.getAttribute('data-mod'), enabled: cb.checked === true });
                    });
                    await api.patchModules(companyId, { modules });
                    toast('Saved modules', 'success');
                    await loadCompanyDetail(companyId);
                } catch (e) {
                    toast(e.message || 'Failed', 'error');
                }
            });
        } catch (e) {
            mount.innerHTML = `
                <div class="card" style="padding:16px;">
                    <h2 style="margin:0 0 8px 0;">Licensing</h2>
                    <p style="margin:0; color:#b91c1c;">${esc(e.message || 'Failed to load company')}</p>
                    <button id="lic-back2" class="btn btn-secondary" style="margin-top:12px;">Back</button>
                </div>
            `;
            document.getElementById('lic-back2')?.addEventListener('click', () => void loadCompanies(readLastLicSearch()));
        }
    }

    await loadCompanies(readLastLicSearch());
}

