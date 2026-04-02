/**
 * Platform Admin: Company detail
 * Route: #platform-admin-company?id=<company_id>
 */
(function () {
    function escapeHtml(s) {
        const d = document.createElement('div');
        d.textContent = s == null ? '' : String(s);
        return d.innerHTML;
    }

    function showErr(msg) {
        if (typeof window.showToast === 'function') window.showToast(msg, 'error');
        else alert(msg);
    }

    function showOk(msg) {
        if (typeof window.showToast === 'function') window.showToast(msg, 'success');
    }

    function setBusy(container, busy) {
        if (!container) return;
        container.querySelectorAll('button, input, select').forEach((el) => {
            if (el.id === 'paBackBtn') return;
            el.disabled = !!busy;
        });
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

    function splitModules(modNames) {
        const business = [];
        const clinical = [];
        (modNames || []).forEach((m) => {
            const name = String(m || '').trim().toLowerCase();
            if (!name) return;
            if (['clinic', 'patients', 'opd', 'prescriptions', 'lab', 'radiology', 'ipd', 'emr'].includes(name)) clinical.push(name);
            else business.push(name);
        });
        return { business, clinical };
    }

    function catalogGroups(resp) {
        const catalog = Array.isArray(resp.module_catalog) ? resp.module_catalog : [];
        if (!catalog.length) return null;
        const business = [];
        const clinical = [];
        const other = [];
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
        return { business, clinical, other };
    }

    async function loadPlatformAdminCompany() {
        const el = document.getElementById('platform-admin-company');
        if (!el) return;

        const params = new URLSearchParams((window.location.hash || '').split('?')[1] || '');
        const companyId = params.get('id');
        if (!companyId) {
            el.innerHTML = '<div class="card" style="padding:1rem;"><p>Missing company id.</p></div>';
            return;
        }

        el.innerHTML = '<div class="card" style="padding:1rem;"><p>Loading company…</p></div>';
        try {
            const resp = await API.platformAdmin.company(companyId);
            const c = resp.company || {};
            const core = Array.isArray(resp.core_modules) ? resp.core_modules.map((x) => String(x).toLowerCase()) : [];
            const moduleRows = Array.isArray(resp.modules) ? resp.modules : [];

            const enabled = new Set(moduleRows.filter((r) => r && r.enabled).map((r) => String(r.name || '').toLowerCase()).filter(Boolean));
            const knownNonCore = moduleRows.map((r) => String(r.name || '').toLowerCase()).filter((n) => n && !core.includes(n));
            const fromCatalog = catalogGroups(resp);
            const split = splitModules(knownNonCore);
            const groups =
                fromCatalog || {
                    business: split.business.sort().map((n) => ({ name: n, enabled: enabled.has(n) })),
                    clinical: split.clinical.sort().map((n) => ({ name: n, enabled: enabled.has(n) })),
                    other: [],
                };

            el.innerHTML = `
                <div class="card" style="padding:1rem;" id="paCompanyCard">
                    <div style="display:flex; align-items:center; justify-content:space-between; gap:1rem; flex-wrap:wrap;">
                        <div>
                            <h2 style="margin:0;">Platform Admin · ${escapeHtml(c.name || 'Company')}</h2>
                            <div style="color:var(--text-secondary); font-size:0.9rem; margin-top:0.25rem;">
                                <code>${escapeHtml(companyId)}</code>
                            </div>
                        </div>
                        <button type="button" class="btn btn-outline btn-sm" id="paBackBtn">← Back</button>
                    </div>

                    <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap:1rem; margin-top:1rem;">
                        <div class="card" style="padding:0.75rem;">
                            <h3 style="margin:0 0 0.5rem;">Subscription</h3>
                            <div class="form-group">
                                <label>Plan</label>
                                <input id="paPlan" class="form-input" value="${escapeHtml(c.subscription_plan || '')}" placeholder="starter / pro / custom" />
                            </div>
                            <div class="form-group" style="margin-top:0.5rem;">
                                <label>Status</label>
                                <input id="paSubStatus" class="form-input" value="${escapeHtml(c.subscription_status || '')}" placeholder="trial / active / past_due / suspended" />
                            </div>
                            <div class="form-group" style="margin-top:0.5rem;">
                                <label>Trial expires at</label>
                                <input id="paTrial" type="datetime-local" class="form-input" value="${toLocalDatetimeValue(c.trial_expires_at)}" />
                            </div>
                            <button type="button" class="btn btn-primary btn-sm" id="paSaveSub" style="margin-top:0.75rem;">Save subscription</button>
                        </div>

                        <div class="card" style="padding:0.75rem;">
                            <h3 style="margin:0 0 0.5rem;">Status</h3>
                            <label style="display:flex; gap:0.5rem; align-items:center; cursor:pointer;">
                                <input id="paIsActive" type="checkbox" ${c.is_active ? 'checked' : ''} />
                                <span>Company is active</span>
                            </label>
                            <button type="button" class="btn btn-primary btn-sm" id="paSaveStatus" style="margin-top:0.75rem;">Save status</button>
                            <div style="margin-top:0.75rem; color:var(--text-secondary); font-size:0.85rem;">
                                Turning off blocks access at the platform layer.
                            </div>
                        </div>
                    </div>

                    <div class="card" style="padding:0.75rem; margin-top:1rem;">
                        <h3 style="margin:0 0 0.5rem;">Licensed modules</h3>
                        <p style="margin:0 0 0.75rem; color:var(--text-secondary); font-size:0.9rem;">
                            Core capabilities stay on for every company. Toggle licensed add-ons; saving writes rows in company modules.
                        </p>
                        ${renderModuleGroup('Business modules', groups.business, enabled, !!fromCatalog)}
                        ${renderModuleGroup('Clinical modules', groups.clinical, enabled, !!fromCatalog)}
                        ${groups.other && groups.other.length ? renderModuleGroup('Other modules', groups.other, enabled, !!fromCatalog) : ''}
                        <button type="button" class="btn btn-primary btn-sm" id="paSaveModules" style="margin-top:0.75rem;">Save modules</button>
                    </div>
                </div>
            `;

            document.getElementById('paBackBtn')?.addEventListener('click', () => {
                window.location.hash = '#platform-admin-companies';
                if (typeof window.loadPage === 'function') void window.loadPage('platform-admin-companies');
            });

            const card = document.getElementById('paCompanyCard');

            document.getElementById('paSaveSub')?.addEventListener('click', async () => {
                try {
                    setBusy(card, true);
                    const subscription_plan = (document.getElementById('paPlan')?.value || '').trim() || null;
                    const subscription_status = (document.getElementById('paSubStatus')?.value || '').trim() || null;
                    const trial_expires_at = fromLocalDatetimeValue(document.getElementById('paTrial')?.value || '');
                    await API.platformAdmin.patchSubscription(companyId, { subscription_plan, subscription_status, trial_expires_at });
                    showOk('Subscription saved');
                } catch (e) {
                    showErr(e.message || 'Failed to save subscription');
                } finally {
                    setBusy(card, false);
                }
            });

            document.getElementById('paSaveStatus')?.addEventListener('click', async () => {
                try {
                    setBusy(card, true);
                    const is_active = !!document.getElementById('paIsActive')?.checked;
                    await API.platformAdmin.patchStatus(companyId, { is_active });
                    showOk('Status saved');
                } catch (e) {
                    showErr(e.message || 'Failed to save status');
                } finally {
                    setBusy(card, false);
                }
            });

            document.getElementById('paSaveModules')?.addEventListener('click', async () => {
                try {
                    setBusy(card, true);
                    const mods = [];
                    card.querySelectorAll('input[data-mod]').forEach((cb) => {
                        const name = cb.getAttribute('data-mod');
                        const checked = cb.checked === true;
                        mods.push({ name, enabled: checked });
                    });
                    await API.platformAdmin.patchModules(companyId, { modules: mods });
                    showOk('Modules saved');
                    await loadPlatformAdminCompany(); // refresh state
                } catch (e) {
                    showErr(e.message || 'Failed to save modules');
                } finally {
                    setBusy(card, false);
                }
            });
        } catch (e) {
            el.innerHTML = `<div class="card" style="padding:1rem;"><p class="text-danger">Could not load company. ${escapeHtml(e.message || '')}</p></div>`;
        }
    }

    function renderModuleGroup(title, mods, enabledSet, catalogMode) {
        if (!mods || mods.length === 0) {
            return `<div style="margin-top:0.5rem;"><strong>${escapeHtml(title)}:</strong> <span style="color:var(--text-secondary);">None</span></div>`;
        }
        const rows = mods
            .map((item) => {
                const isObj = item && typeof item === 'object' && item.name != null;
                const name = String(isObj ? item.name : item).toLowerCase();
                const on = catalogMode ? item.enabled === true : enabledSet.has(name);
                return `
                    <label style="display:flex; gap:0.5rem; align-items:center; padding:0.25rem 0;">
                        <input type="checkbox" data-mod="${escapeHtml(name)}" ${on ? 'checked' : ''} />
                        <span>${escapeHtml(moduleDisplayName(name))}</span>
                    </label>
                `;
            })
            .join('');
        return `
            <div style="margin-top:0.75rem;">
                <div style="font-weight:600; margin-bottom:0.25rem;">${escapeHtml(title)}</div>
                <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap:0.25rem 1rem;">
                    ${rows}
                </div>
            </div>
        `;
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
            const d = new Date(s);
            return d.toISOString();
        } catch (_) {
            return null;
        }
    }

    window.loadPlatformAdminCompany = loadPlatformAdminCompany;
})();

