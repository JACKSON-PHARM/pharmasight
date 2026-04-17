/**
 * Platform Admin (admin.html): Licensing / module control UI.
 *
 * Uses admin auth (admin_token) to call /api/admin/platform-licensing/* endpoints,
 * so platform ops stay inside admin.html without requiring an app user session.
 */

const LIC_SEARCH_STORAGE_KEY = 'pharmasight_admin_lic_search';
/** Prevents stale list responses (e.g. initial full list finishing after a search) from overwriting the table. */
let _licListLoadSeq = 0;

/**
 * Predefined SaaS tiers (slug = companies.subscription_plan).
 * Limits map to company caps (null = no numeric cap / “unlimited” in enforcement).
 * Pricing is indicative for ops UI; Stripe checkout still uses configured Price IDs.
 */
const SAAS_TIERS = [
    {
        slug: 'demo',
        title: 'Demo',
        subtitle: 'Self-service evaluation & trials',
        price: '$0',
        users: 1,
        branches: 1,
        products: 100,
        modules: 'Core + demo scope (tight caps)',
    },
    {
        slug: 'clinic_starter',
        title: 'Clinic Starter',
        subtitle: 'Solo practice & small outpatient clinics',
        price: 'Contact for pricing',
        users: 3,
        branches: 1,
        products: 800,
        modules: 'POS, stock, dispensing, patient register, basic reporting',
    },
    {
        slug: 'pharmacy_growth',
        title: 'Pharmacy Growth',
        subtitle: 'Growing retail & hospital outpatient pharmacy',
        price: 'Contact for pricing',
        users: 10,
        branches: 4,
        products: 8000,
        modules: 'Starter + branch ops, purchasing, eTIMS-ready, extended reports',
    },
    {
        slug: 'health_network',
        title: 'Health Network',
        subtitle: 'Multi-site groups & small chains',
        price: 'Contact for pricing',
        users: 40,
        branches: 15,
        products: 50000,
        modules: 'Growth + clinic modules, finance add-ons, higher throughput',
    },
    {
        slug: 'enterprise',
        title: 'Enterprise',
        subtitle: 'Hospital systems, large chains, custom integrations',
        price: 'Custom',
        users: null,
        branches: null,
        products: null,
        modules: 'All licensed modules · priority support · SLAs (contract-driven)',
    },
];

function _tierBySlug(slug) {
    const s = (slug || '').trim().toLowerCase();
    return SAAS_TIERS.find((t) => t.slug === s) || null;
}

function _licFormatCap(n) {
    if (n == null) return 'Unlimited';
    return String(n);
}

function publicDemoSignupSectionHtml() {
    return `
            <div class="public-demo-qr" style="margin-bottom: 16px; padding: 14px; border: 1px dashed #cbd5e1; border-radius: 12px; background: #f8fafc;">
                <h3 style="margin: 0 0 8px 0; font-size: 1rem;">Free Demo Signup (Public)</h3>
                <p style="margin: 0 0 10px 0; color: #475569; font-size: 0.9rem; line-height: 1.35;">
                    Copy this link for posters. Scanning the QR code opens the signup form. Trial length is enforced on each company record (see Manage).
                </p>
                <div style="display:flex; gap: 14px; align-items: flex-start; flex-wrap: wrap;">
                    <div style="flex: 1; min-width: 280px;">
                        <label style="display:block; font-weight: 600; margin-bottom: 6px;">Signup link</label>
                        <div style="display:flex; gap: 8px; align-items:center;">
                            <input id="public-demo-signup-link" type="text" readonly style="flex:1; padding: 8px 10px; border: 1px solid #e2e8f0; border-radius: 8px; font-family: monospace; font-size: 12px; background: white;">
                            <button id="copy-public-demo-signup-link-btn" type="button" class="btn btn-secondary">Copy</button>
                        </div>
                        <div style="color:#64748b; font-size: 0.85rem; margin-top: 8px;">
                            Example: <code>/</code>#<code>login?demo=1</code>
                        </div>
                    </div>
                    <div style="width: 240px; flex: 0 0 auto;">
                        <label style="display:block; font-weight: 600; margin-bottom: 6px;">QR code</label>
                        <div id="public-demo-qr" style="background: white; border-radius: 10px; padding: 10px; border: 1px solid #e2e8f0; display:flex; align-items:center; justify-content:center;">
                            <span style="color:#94a3b8; font-size: 0.9rem;">Generating…</span>
                        </div>
                    </div>
                </div>
            </div>`;
}

async function setupPublicDemoSignupQr() {
    try {
        const savedPublic = (() => {
            try {
                return (localStorage.getItem('pharmasight_app_public_url') || '').trim().replace(/\/+$/, '');
            } catch (_) {
                return '';
            }
        })();
        const base = savedPublic || window.location.origin;
        const link = `${base}/#login?demo=1`;
        const input = document.getElementById('public-demo-signup-link');
        const copyBtn = document.getElementById('copy-public-demo-signup-link-btn');
        const qrContainer = document.getElementById('public-demo-qr');

        if (!input || !copyBtn || !qrContainer) return;

        input.value = link;

        copyBtn.onclick = async () => {
            try {
                await navigator.clipboard.writeText(link);
                if (window.showNotification) window.showNotification('Demo signup link copied', 'success');
                else alert('Demo signup link copied');
            } catch (e) {
                if (window.showNotification) window.showNotification('Could not copy link', 'error');
                else alert('Could not copy link');
            }
        };

        const canvas = document.createElement('canvas');
        canvas.width = 220;
        canvas.height = 220;
        qrContainer.innerHTML = '';
        qrContainer.appendChild(canvas);

        const qrOpts = { width: 220, margin: 1, errorCorrectionLevel: 'M' };

        const tryGenerate = async (qrLib) => {
            const toCanvas = qrLib?.toCanvas;
            if (typeof toCanvas !== 'function') return false;
            try {
                await toCanvas(canvas, link, qrOpts);
                return true;
            } catch (_) {
                return false;
            }
        };

        let ok = await tryGenerate(window.QRCode);
        if (!ok) {
            const deadline = Date.now() + 3500;
            while (!ok && Date.now() < deadline) {
                await new Promise((r) => setTimeout(r, 150));
                ok = await tryGenerate(window.QRCode);
            }
        }

        if (!ok) {
            qrContainer.innerHTML =
                '<span style="color:#94a3b8; font-size:0.9rem;">QR generation failed (local QR script not ready)</span>';
        }
    } catch (e) {
        console.warn('Public demo QR setup failed:', e);
    }
}

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
                ${publicDemoSignupSectionHtml()}
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
        void setupPublicDemoSignupQr();
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
                const effectiveStatus = (() => {
                    const s = (c.subscription_status || '').trim();
                    if (s) return s;
                    // Treat null subscription fields as active (full access) per single-source-of-truth rules.
                    if (c.trial_expires_at) return 'trial';
                    return 'active';
                })();
                return `
                    <tr data-cid="${cid}" style="cursor:pointer;">
                        <td style="padding:10px; border-bottom:1px solid #f1f5f9;">${esc(c.name || '—')}</td>
                        <td style="padding:10px; border-bottom:1px solid #f1f5f9;">${esc(c.subscription_plan || '—')}</td>
                        <td style="padding:10px; border-bottom:1px solid #f1f5f9;">${esc(effectiveStatus)}</td>
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
                        <div style="border:1px solid #e2e8f0; border-radius:10px; padding:12px; grid-column: 1 / -1;">
                            <h3 style="margin:0 0 6px 0;">Subscription &amp; plan</h3>
                            <p style="margin:0 0 12px 0; color:#64748b; font-size:0.88rem; line-height:1.4;">
                                Choose a predefined healthcare SaaS tier. Caps apply to users, branches, and catalog size (empty cap = unlimited). Billing integration still uses your Stripe price configuration per tier slug.
                            </p>
                            <div id="lic-tier-grid" style="display:grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap:10px;">
                                ${SAAS_TIERS.map((t) => {
                                    const cur = ((c.subscription_plan || '').trim().toLowerCase() === t.slug);
                                    const b = cur ? '#6366f1' : '#e2e8f0';
                                    const bg = cur ? '#f5f3ff' : '#fff';
                                    return `
                                <button type="button" class="lic-tier-card" data-tier-slug="${esc(t.slug)}" style="cursor:pointer; text-align:left; border:2px solid ${b}; background:${bg}; border-radius:10px; padding:10px 12px; font:inherit;">
                                    <div style="font-weight:700; font-size:0.95rem;">${esc(t.title)}</div>
                                    <div style="color:#64748b; font-size:0.78rem; margin:4px 0 6px;">${esc(t.subtitle)}</div>
                                    <div style="font-weight:600; color:#4338ca; font-size:0.85rem;">${esc(t.price)}</div>
                                    <ul style="margin:8px 0 0; padding-left:18px; color:#475569; font-size:0.78rem; line-height:1.35;">
                                        <li>Users: ${_licFormatCap(t.users)}</li>
                                        <li>Branches: ${_licFormatCap(t.branches)}</li>
                                        <li>Products: ${_licFormatCap(t.products)}</li>
                                    </ul>
                                    <div style="margin-top:8px; color:#64748b; font-size:0.72rem;">${esc(t.modules)}</div>
                                    ${cur ? '<div style="margin-top:8px;"><span style="font-size:0.72rem; background:#e0e7ff; color:#3730a3; padding:2px 8px; border-radius:999px;">Current</span></div>' : ''}
                                </button>`;
                                }).join('')}
                            </div>
                            <details style="margin-top:12px;">
                                <summary style="cursor:pointer; color:#475569; font-size:0.88rem;">Advanced · raw plan slug</summary>
                                <label style="display:block; font-weight:600; margin:8px 0 4px;">subscription_plan (stored value)</label>
                                <input id="lic-plan-slug-adv" value="${esc(c.subscription_plan || '')}" placeholder="e.g. clinic_starter" style="width:100%; max-width:420px; padding:8px 10px; border:1px solid #e2e8f0; border-radius:8px; font-family:monospace; font-size:12px;">
                            </details>
                            <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap:10px; margin-top:12px;">
                                <div>
                                    <label style="display:block; font-weight:600; margin-bottom:4px; font-size:0.85rem;">User cap</label>
                                    <input id="lic-cap-users" type="number" min="1" placeholder="empty = unlimited" value="${c.user_limit != null ? esc(String(c.user_limit)) : ''}" style="width:100%; padding:8px 10px; border:1px solid #e2e8f0; border-radius:8px;">
                                </div>
                                <div>
                                    <label style="display:block; font-weight:600; margin-bottom:4px; font-size:0.85rem;">Branch cap</label>
                                    <input id="lic-cap-branches" type="number" min="1" placeholder="empty = unlimited" value="${c.branch_limit != null ? esc(String(c.branch_limit)) : ''}" style="width:100%; padding:8px 10px; border:1px solid #e2e8f0; border-radius:8px;">
                                </div>
                                <div>
                                    <label style="display:block; font-weight:600; margin-bottom:4px; font-size:0.85rem;">Product cap</label>
                                    <input id="lic-cap-products" type="number" min="1" placeholder="empty = unlimited" value="${c.product_limit != null ? esc(String(c.product_limit)) : ''}" style="width:100%; padding:8px 10px; border:1px solid #e2e8f0; border-radius:8px;">
                                </div>
                            </div>
                            <label style="display:block; font-weight:600; margin:12px 0 6px 0;">Status</label>
                            <select id="lic-status" style="width:100%; max-width:320px; padding:8px 10px; border:1px solid #e2e8f0; border-radius:8px;">
                                ${['', 'active', 'trialing', 'past_due', 'canceled', 'suspended', 'incomplete', 'demo'].map((v) => {
                                    const curSt = (c.subscription_status || '').trim().toLowerCase();
                                    const selected = v === '' ? !curSt : curSt === v.toLowerCase();
                                    const lab = v === '' ? '(not set)' : v;
                                    return `<option value="${esc(v)}" ${selected ? 'selected' : ''}>${esc(lab)}</option>`;
                                }).join('')}
                            </select>
                            <label style="display:block; font-weight:600; margin:10px 0 6px 0;">Trial expires</label>
                            <input id="lic-trial" type="datetime-local" value="${esc(toLocalDatetimeValue(c.trial_expires_at))}" style="width:100%; max-width:320px; padding:8px 10px; border:1px solid #e2e8f0; border-radius:8px;">
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

            const licApplyTierToForm = (slug) => {
                const t = _tierBySlug(slug);
                const adv = document.getElementById('lic-plan-slug-adv');
                if (adv) adv.value = slug || '';
                if (!t) return;
                const u = document.getElementById('lic-cap-users');
                const br = document.getElementById('lic-cap-branches');
                const pr = document.getElementById('lic-cap-products');
                if (u) u.value = t.users != null ? String(t.users) : '';
                if (br) br.value = t.branches != null ? String(t.branches) : '';
                if (pr) pr.value = t.products != null ? String(t.products) : '';
                mount.querySelectorAll('.lic-tier-card').forEach((btn) => {
                    const on = (btn.getAttribute('data-tier-slug') || '') === slug;
                    btn.style.borderColor = on ? '#6366f1' : '#e2e8f0';
                    btn.style.background = on ? '#f5f3ff' : '#fff';
                });
            };

            mount.querySelectorAll('.lic-tier-card').forEach((btn) => {
                btn.addEventListener('click', () => {
                    const slug = btn.getAttribute('data-tier-slug');
                    if (slug) licApplyTierToForm(slug);
                });
            });

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

            const _readCap = (id) => {
                const el = document.getElementById(id);
                const v = (el?.value || '').trim();
                if (v === '') return null;
                const n = parseInt(v, 10);
                return Number.isFinite(n) ? n : null;
            };

            document.getElementById('lic-save-sub')?.addEventListener('click', async () => {
                try {
                    const subscription_plan = (document.getElementById('lic-plan-slug-adv')?.value || '').trim() || null;
                    const subscription_status = (document.getElementById('lic-status')?.value || '').trim() || null;
                    const trial_expires_at = fromLocalDatetimeValue(document.getElementById('lic-trial')?.value || '');
                    const user_limit = _readCap('lic-cap-users');
                    const branch_limit = _readCap('lic-cap-branches');
                    const product_limit = _readCap('lic-cap-products');
                    await api.patchSubscription(companyId, {
                        subscription_plan,
                        subscription_status,
                        trial_expires_at,
                        user_limit,
                        branch_limit,
                        product_limit,
                    });
                    toast('Saved subscription', 'success');
                    await loadCompanyDetail(companyId);
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

