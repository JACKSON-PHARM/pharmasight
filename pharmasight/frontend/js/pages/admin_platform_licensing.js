/**
 * Platform Admin (admin.html): Licensing / module control UI.
 *
 * Uses admin auth (admin_token) to call /api/admin/platform-licensing/* endpoints,
 * so platform ops stay inside admin.html without requiring an app user session.
 */

import {
    loadPricingCatalog,
    saasTiersFromCatalog,
    renderPricingPlaybookHtml,
    tierBySlug as catalogTierBySlug,
} from '/js/pricing/sightops_pricing_catalog.js?v=2026-05';

const LIC_SEARCH_STORAGE_KEY = 'pharmasight_admin_lic_search';
/** Prevents stale list responses (e.g. initial full list finishing after a search) from overwriting the table. */
let _licListLoadSeq = 0;

async function copyTextToClipboard(text, toastFn) {
    const value = String(text || '').trim();
    if (!value) {
        if (toastFn) toastFn('No link to copy', 'error');
        return false;
    }
    try {
        await navigator.clipboard.writeText(value);
        if (toastFn) toastFn('Login link copied', 'success');
        return true;
    } catch (_) {
        try {
            const ta = document.createElement('textarea');
            ta.value = value;
            ta.setAttribute('readonly', '');
            ta.style.position = 'fixed';
            ta.style.left = '-9999px';
            document.body.appendChild(ta);
            ta.select();
            document.execCommand('copy');
            document.body.removeChild(ta);
            if (toastFn) toastFn('Login link copied', 'success');
            return true;
        } catch (e2) {
            if (toastFn) toastFn('Could not copy link', 'error');
            return false;
        }
    }
}

/** Populated from sightops_pricing_catalog.json in init(). slug = companies.subscription_plan */
let SAAS_TIERS = [];
let PRICING_CATALOG = null;

function _tierBySlug(slug) {
    const s = (slug || '').trim().toLowerCase();
    const direct = SAAS_TIERS.find((t) => t.slug === s);
    if (direct) return direct;
    if (PRICING_CATALOG) {
        const t = catalogTierBySlug(PRICING_CATALOG, s);
        if (t) return saasTiersFromCatalog(PRICING_CATALOG).find((x) => x.slug === t.slug) || null;
    }
    return null;
}

function _licFormatCap(n) {
    if (n == null) return 'Unlimited';
    return String(n);
}

function createClientCompanySectionHtml(esc) {
    const tierOpts = SAAS_TIERS.map(
        (t) =>
            `<option value="${esc(t.slug)}"${t.slug === 'retail_solo' ? ' selected' : ''}>${esc(t.title)} — ${esc(t.price)} (${esc(t.slug)})</option>`,
    ).join('');
    return `
            <div class="lic-create-client" style="margin-bottom: 20px; padding: 16px; border: 1px solid #e2e8f0; border-radius: 12px; background: #fff;">
                <h3 style="margin: 0 0 8px 0; font-size: 1.05rem;">Create client company</h3>
                <p style="margin: 0 0 14px 0; color: #475569; font-size: 0.9rem; line-height: 1.4;">
                    Provisions a <strong>company</strong>, HQ <strong>branch</strong>, and <strong>tenant</strong> row on the shared database (same path as legacy admin tenant create).
                    No login user is created here — after saving, send an <strong>invite</strong> so the client can complete signup and get branch access.
                </p>
                <form id="lic-create-client-form" style="display: grid; gap: 12px; max-width: 640px;">
                    <div>
                        <label style="display:block; font-weight:600; margin-bottom:4px;">Company name *</label>
                        <input name="name" type="text" required maxlength="255" class="form-input" placeholder="e.g. Acme Retail Ltd" style="width:100%; padding:8px 10px; border:1px solid #e2e8f0; border-radius:8px;">
                    </div>
                    <div>
                        <label style="display:block; font-weight:600; margin-bottom:4px;">Admin email *</label>
                        <input name="admin_email" type="email" required class="form-input" placeholder="owner@client.com" style="width:100%; padding:8px 10px; border:1px solid #e2e8f0; border-radius:8px;">
                    </div>
                    <div>
                        <label style="display:block; font-weight:600; margin-bottom:4px;">Admin full name <span style="font-weight:400; color:#64748b;">(recommended — used for default username)</span></label>
                        <input name="admin_full_name" type="text" maxlength="255" class="form-input" placeholder="e.g. Jane Mwangi" style="width:100%; padding:8px 10px; border:1px solid #e2e8f0; border-radius:8px;">
                    </div>
                    <div>
                        <label style="display:block; font-weight:600; margin-bottom:4px;">Phone</label>
                        <input name="phone" type="text" maxlength="50" class="form-input" placeholder="Optional" style="width:100%; padding:8px 10px; border:1px solid #e2e8f0; border-radius:8px;">
                    </div>
                    <div style="display:grid; grid-template-columns: 1fr 1fr; gap:12px;">
                        <div>
                            <label style="display:block; font-weight:600; margin-bottom:4px;">Currency</label>
                            <input name="currency" type="text" value="KES" maxlength="10" class="form-input" style="width:100%; padding:8px 10px; border:1px solid #e2e8f0; border-radius:8px;">
                        </div>
                        <div>
                            <label style="display:block; font-weight:600; margin-bottom:4px;">Timezone</label>
                            <input name="timezone" type="text" value="Africa/Nairobi" maxlength="50" class="form-input" style="width:100%; padding:8px 10px; border:1px solid #e2e8f0; border-radius:8px;">
                        </div>
                    </div>
                    <div>
                        <label style="display:block; font-weight:600; margin-bottom:4px;">URL subdomain <span style="font-weight:400; color:#64748b;">(optional — unique)</span></label>
                        <input name="tenant_subdomain" type="text" maxlength="100" class="form-input" placeholder="Leave blank to auto-generate from company name" style="width:100%; padding:8px 10px; border:1px solid #e2e8f0; border-radius:8px;">
                    </div>
                    <div>
                        <label style="display:block; font-weight:600; margin-bottom:4px;">Initial subscription plan slug</label>
                        <select name="subscription_plan" class="form-input" style="width:100%; padding:8px 10px; border:1px solid #e2e8f0; border-radius:8px;">
                            <option value="">— Not set (paid trial tenant row) —</option>
                            ${tierOpts}
                        </select>
                        <div style="margin-top:6px; font-size:0.78rem; color:#64748b;">New retail clients: <strong>retail_solo</strong> or <strong>retail_pro</strong>. See <a href="/marketing/pricing-policy.html" target="_blank" rel="noopener">Pricing Policy</a>.</div>
                    </div>
                    <div>
                        <button type="submit" class="btn btn-primary" id="lic-create-client-submit">Create company</button>
                    </div>
                </form>
                <div id="lic-create-client-result" style="display:none; margin-top:14px; padding:12px; border-radius:8px; background:#ecfdf5; border:1px solid #6ee7b7; font-size:0.9rem;"></div>
            </div>`;
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
        const link = `${base.replace(/\/+$/, '')}/app#login?demo=1`;
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

    try {
        PRICING_CATALOG = await loadPricingCatalog();
        SAAS_TIERS = saasTiersFromCatalog(PRICING_CATALOG);
    } catch (e) {
        console.warn('[licensing] pricing catalog load failed', e);
        SAAS_TIERS = [];
    }

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
        const playbookHtml = PRICING_CATALOG ? renderPricingPlaybookHtml(PRICING_CATALOG, esc) : '';

        mount.innerHTML = `
            <div class="card" style="padding:16px;">
                ${playbookHtml}
                ${createClientCompanySectionHtml(esc)}
                ${publicDemoSignupSectionHtml()}
                <div style="display:flex; align-items:center; justify-content:space-between; gap:12px; flex-wrap:wrap;">
                    <div>
                        <h2 style="margin:0;">Governance · Companies</h2>
                        <div style="color:#666; font-size:0.9rem; margin-top:4px;">Search by name, then open a company to manage operating model, access, modules, and branch doctrine.</div>
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
                                <th style="text-align:left; padding:10px; border-bottom:1px solid #eee;">Access</th>
                                <th style="text-align:left; padding:10px; border-bottom:1px solid #eee;">Operating model</th>
                                <th style="text-align:left; padding:10px; border-bottom:1px solid #eee;">Plan</th>
                                <th style="text-align:left; padding:10px; border-bottom:1px solid #eee;">Status</th>
                                <th style="text-align:left; padding:10px; border-bottom:1px solid #eee;">Trial expires</th>
                                <th style="text-align:left; padding:10px; border-bottom:1px solid #eee;">Active</th>
                                <th style="text-align:left; padding:10px; border-bottom:1px solid #eee;">Login link</th>
                                <th style="text-align:left; padding:10px; border-bottom:1px solid #eee;">Actions</th>
                            </tr>
                        </thead>
                        <tbody id="lic-tbody">
                            <tr><td colspan="9" style="padding:12px; color:#666;">Loading…</td></tr>
                        </tbody>
                    </table>
                </div>
            </div>
        `;

        const tbody = document.getElementById('lic-tbody');
        void setupPublicDemoSignupQr();
        const wireCreateClient = () => {
            const form = document.getElementById('lic-create-client-form');
            const resultEl = document.getElementById('lic-create-client-result');
            const submitBtn = document.getElementById('lic-create-client-submit');
            if (!form || !resultEl) return;

            form.addEventListener('submit', async (ev) => {
                ev.preventDefault();
                const fd = new FormData(form);
                const name = (fd.get('name') || '').toString().trim();
                const admin_email = (fd.get('admin_email') || '').toString().trim();
                const admin_full_name = (fd.get('admin_full_name') || '').toString().trim() || null;
                const phone = (fd.get('phone') || '').toString().trim() || null;
                const currency = (fd.get('currency') || 'KES').toString().trim() || 'KES';
                const timezone = (fd.get('timezone') || 'Africa/Nairobi').toString().trim() || 'Africa/Nairobi';
                const tenant_subdomain = (fd.get('tenant_subdomain') || '').toString().trim() || null;
                const subscription_plan = (fd.get('subscription_plan') || '').toString().trim() || null;
                const payload = {
                    name,
                    admin_email,
                    admin_full_name,
                    phone,
                    currency,
                    timezone,
                    tenant_subdomain,
                };
                if (subscription_plan) payload.subscription_plan = subscription_plan;
                if (submitBtn) submitBtn.disabled = true;
                resultEl.style.display = 'none';
                try {
                    const out = await api.createCompany(payload);
                    const tid = out.tenant_id;
                    const sub = out.subdomain || out.org_slug || '—';
                    const orgLoginUrl = out.org_login_url || '';
                    const cid = out.company?.id || '—';
                    const inv = out.initial_invite || null;
                    const invWarn = out.invite_warning ? String(out.invite_warning) : '';
                    const setupUrl = inv && inv.setup_url ? String(inv.setup_url) : '';
                    const emailed = inv && inv.email_sent === true;
                    resultEl.style.display = 'block';
                    resultEl.innerHTML = `
                        <p style="margin:0 0 8px 0; font-weight:600;">Company created</p>
                        <p style="margin:0 0 8px 0;">Company ID: <code>${esc(cid)}</code></p>
                        <p style="margin:0 0 8px 0;">Tenant ID: <code>${esc(tid)}</code> · Subdomain: <code>${esc(sub)}</code></p>
                        ${
                            orgLoginUrl
                                ? `<div style="margin:0 0 10px 0;">
                            <label style="display:block; font-weight:600; font-size:0.85rem; margin-bottom:4px;">Organization sign-in link (share with users)</label>
                            <div style="display:flex; flex-wrap:wrap; gap:8px; align-items:center;">
                                <input type="text" readonly value="${esc(orgLoginUrl)}" style="flex:1; min-width:220px; padding:8px 10px; border:1px solid #e2e8f0; border-radius:8px; font-size:12px;">
                                <button type="button" class="btn btn-outline btn-sm lic-copy-login-inline" data-login-url="${esc(orgLoginUrl)}">Copy login link</button>
                                <a href="${esc(orgLoginUrl)}" target="_blank" rel="noopener" class="btn btn-secondary btn-sm">Open</a>
                            </div>
                        </div>`
                                : ''
                        }
                        ${
                            invWarn
                                ? `<p style="margin:0 0 8px 0; color:#b45309;">Invite: ${esc(invWarn)}</p>`
                                : `<p style="margin:0 0 8px 0; color:#065f46;">A setup invite was created automatically${
                                      emailed ? ' and the email was queued (requires SMTP on the server).' : '.'
                                  }</p>`
                        }
                        ${
                            setupUrl
                                ? `<div style="margin:0 0 10px 0;">
                            <label style="display:block; font-weight:600; font-size:0.85rem; margin-bottom:4px;">Setup link (share if email did not send)</label>
                            <input type="text" readonly value="${esc(setupUrl)}" style="width:100%; max-width:560px; padding:8px 10px; border:1px solid #e2e8f0; border-radius:8px; font-size:12px;">
                        </div>`
                                : ''
                        }
                        <p style="margin:0 0 6px 0; color:#64748b; font-size:0.85rem;">You can resend or fix the email under <strong>Manage</strong> for this company.</p>
                        <button type="button" class="btn btn-secondary btn-sm" id="lic-create-client-invite-btn">Send another invite email</button>
                        <span id="lic-create-client-invite-status" style="margin-left:10px; color:#64748b;"></span>
                    `;
                    toast('Company created. Invite created — check Manage if email did not arrive.', 'success');
                    resultEl.querySelector('.lic-copy-login-inline')?.addEventListener('click', () => {
                        const url = resultEl.querySelector('.lic-copy-login-inline')?.getAttribute('data-login-url');
                        if (url) void copyTextToClipboard(url, toast);
                    });
                    document.getElementById('lic-create-client-invite-btn')?.addEventListener('click', async () => {
                        const st = document.getElementById('lic-create-client-invite-status');
                        if (st) st.textContent = 'Sending…';
                        try {
                            const invApi = window.API?.admin?.tenants?.invites;
                            if (!invApi?.create) throw new Error('Invite API not available');
                            await invApi.create(tid, { expires_in_days: 7, send_email: true });
                            if (st) st.textContent = 'Invite queued (check SMTP on server).';
                            toast('Invite email queued', 'success');
                        } catch (e2) {
                            if (st) st.textContent = '';
                            toast(e2.message || 'Invite failed', 'error');
                        }
                    });
                } catch (e) {
                    toast(e.message || 'Create failed', 'error');
                } finally {
                    if (submitBtn) submitBtn.disabled = false;
                }
            });
        };
        wireCreateClient();

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
                const accessLabel = c.governance_access_label || '—';
                const accessLegacy = c.governance_uses_legacy
                    ? ' <span style="color:#b45309;font-size:0.75rem;">legacy</span>'
                    : '';
                const opModel = (c.organization_operating_model || '—').replace(/_/g, ' ');
                const effectiveStatus = (c.subscription_status || '').trim() || '—';
                const trialIso = c.trial_display_expires_at || c.trial_expires_at;
                const trialCell = trialIso
                    ? `${esc(new Date(trialIso).toLocaleString())}${
                          !c.trial_expires_at && c.trial_display_expires_at
                              ? ' <span style="color:#64748b;font-size:0.78rem;">(demo default)</span>'
                              : ''
                      }`
                    : '—';
                const loginUrl = (c.org_login_url || '').trim();
                const loginCell = loginUrl
                    ? `<button type="button" class="btn btn-outline btn-sm lic-copy-login" data-login-url="${esc(loginUrl)}" title="${esc(loginUrl)}">Copy login link</button>`
                    : `<span style="color:#b45309;font-size:0.8rem;">No subdomain</span>`;
                return `
                    <tr data-cid="${cid}" style="cursor:pointer;">
                        <td style="padding:10px; border-bottom:1px solid #f1f5f9;">${esc(c.name || '—')}</td>
                        <td style="padding:10px; border-bottom:1px solid #f1f5f9;">${esc(accessLabel)}${accessLegacy}</td>
                        <td style="padding:10px; border-bottom:1px solid #f1f5f9;">${esc(opModel)}</td>
                        <td style="padding:10px; border-bottom:1px solid #f1f5f9;">${esc(c.subscription_plan || '—')}</td>
                        <td style="padding:10px; border-bottom:1px solid #f1f5f9;">${esc(effectiveStatus)}</td>
                        <td style="padding:10px; border-bottom:1px solid #f1f5f9;">${trialCell}</td>
                        <td style="padding:10px; border-bottom:1px solid #f1f5f9;">${active}</td>
                        <td style="padding:10px; border-bottom:1px solid #f1f5f9; white-space:nowrap;">${loginCell}</td>
                        <td style="padding:10px; border-bottom:1px solid #f1f5f9; white-space:nowrap;">
                            <button type="button" class="btn btn-primary btn-sm lic-open-manage" data-cid="${cid}">Manage</button>
                        </td>
                    </tr>
                `;
            }).join('');
            if (seq !== _licListLoadSeq) return;
            tbody.innerHTML = rows || '<tr><td colspan="9" style="padding:12px; color:#666;">No companies match.</td></tr>';

            tbody.addEventListener('click', (e) => {
                const copyBtn = e.target.closest('.lic-copy-login');
                if (copyBtn) {
                    e.preventDefault();
                    e.stopPropagation();
                    void copyTextToClipboard(copyBtn.getAttribute('data-login-url'), toast);
                    return;
                }
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
            tbody.innerHTML = `<tr><td colspan="9" style="padding:12px; color:#b91c1c;">Failed: ${esc(e.message || 'Error')}</td></tr>`;
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
        wholesale: 'Pharmacy wholesale (B2B customers)',
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
                <h2 style="margin:0 0 8px 0;">Company governance</h2>
                <p style="margin:0; color:#666;">Loading…</p>
            </div>
        `;
        try {
            const govUi = await import('/js/pages/admin_governance_panel.js?v=1');
            const [resp, etims, gov] = await Promise.all([
                api.company(companyId),
                (typeof api.etimsCompany === 'function' ? api.etimsCompany(companyId) : Promise.resolve(null)).catch(() => null),
                (typeof api.governance === 'function' ? api.governance(companyId) : Promise.resolve(null)).catch(() => null),
            ]);
            const c = resp.company || {};
            const dispUserCap = c.user_limit != null ? c.user_limit : c.resolved_user_limit;
            const dispBranchCap = c.branch_limit != null ? c.branch_limit : c.resolved_branch_limit;
            const dispProductCap = c.product_limit != null ? c.product_limit : c.resolved_product_limit;
            const planSlugForUi = (c.subscription_plan || '').trim().toLowerCase();
            const tierForUi = _tierBySlug(planSlugForUi);
            const fmtCap = (n) => (n == null ? 'Unlimited' : String(n));
            const trialForInput = c.trial_expires_at || c.trial_display_expires_at;
            const trialListLabel = trialForInput ? new Date(trialForInput).toLocaleString() : '—';
            const tenantIdForInvite = (c.tenant_id || '').trim();
            const orgLoginUrl = (resp.org_login_url || c.org_login_url || '').trim();
            const orgSlug = (resp.org_slug || c.org_slug || c.tenant_subdomain || '').trim();
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

            const govHtml = gov
                ? govUi.renderGovernanceOverview(gov, esc) +
                  govUi.renderOperatingModelPresets(gov, esc) +
                  govUi.renderBranchGovernanceTable(gov, esc)
                : '<p class="gov-alert gov-alert--warning">Governance profile unavailable (run migration 126 and restart API).</p>';

            mount.innerHTML = `
                <div class="card" style="padding:16px;">
                    <div style="margin-bottom:8px;">
                        <button id="lic-back" class="btn btn-secondary">← Back to companies</button>
                    </div>
                    ${govHtml}

                    <details class="gov-advanced">
                    <summary>Access &amp; billing</summary>
                    <div style="margin-top:14px; padding:12px 14px; border-radius:10px; border:2px solid #4338ca; background:linear-gradient(135deg,#f5f3ff 0%,#eef2ff 100%); box-shadow:0 0 0 1px rgba(67,56,202,0.12);">
                        <div style="font-weight:700; color:#312e81; font-size:0.95rem;">Current plan</div>
                        <div style="margin-top:6px; color:#3730a3; font-size:0.88rem; line-height:1.45;">
                            <strong>${esc(tierForUi ? tierForUi.title : planSlugForUi || '—')}</strong>
                            ${planSlugForUi ? ` · slug <code style="background:#e0e7ff;padding:1px 6px;border-radius:4px;">${esc(planSlugForUi)}</code>` : ''}
                            ${c.subscription_status ? ` · status <code style="background:#e0e7ff;padding:1px 6px;border-radius:4px;">${esc(String(c.subscription_status))}</code>` : ''}
                        </div>
                        <div style="margin-top:8px; font-size:0.85rem; color:#4338ca;">
                            <strong>Enforced caps</strong> (what the app applies now):
                            Users ${esc(fmtCap(c.resolved_user_limit))},
                            Branches ${esc(fmtCap(c.resolved_branch_limit))},
                            Products ${esc(fmtCap(c.resolved_product_limit))}
                        </div>
                        <div style="margin-top:6px; font-size:0.8rem; color:#64748b;">
                            Stored columns can be blank; demo still uses platform defaults. Use <strong>Save subscription</strong> to persist explicit numbers on the company row.
                        </div>
                        <div style="margin-top:10px; font-size:0.85rem; color:#4338ca;">
                            <strong>Trial / access window</strong> (for list + reminders): ${esc(trialListLabel)}
                            ${
                                !c.trial_expires_at && c.trial_display_expires_at
                                    ? ' <span style="color:#64748b;">(inferred for <code>demo</code> from company creation — set <strong>Trial expires</strong> below and save to store on the company row.)</span>'
                                    : ''
                            }
                        </div>
                    </div>

                    <div style="margin-top:16px; border:1px solid #e2e8f0; border-radius:10px; padding:14px; background:#fafafa;">
                        <h3 style="margin:0 0 6px 0;">Organization &amp; setup invite</h3>
                        ${
                            orgLoginUrl
                                ? `<div style="margin:0 0 14px 0; padding:12px; border-radius:8px; background:#ecfdf5; border:1px solid #a7f3d0;">
                            <div style="font-weight:600; color:#065f46; margin-bottom:6px;">Customer sign-in link</div>
                            <p style="margin:0 0 8px 0; color:#047857; font-size:0.88rem; line-height:1.45;">
                                Share this with staff for day-to-day login. It includes <code>?org=${esc(orgSlug)}</code> so the app opens the correct company.
                                Password-reset emails use the same link.
                            </p>
                            <div style="display:flex; flex-wrap:wrap; gap:8px; align-items:center;">
                                <input id="lic-org-login-url" type="text" readonly value="${esc(orgLoginUrl)}" style="flex:1; min-width:240px; padding:8px 10px; border:1px solid #cbd5e1; border-radius:8px; font-size:12px;">
                                <button type="button" id="lic-copy-org-login" class="btn btn-outline btn-sm">Copy login link</button>
                                <a href="${esc(orgLoginUrl)}" target="_blank" rel="noopener" class="btn btn-secondary btn-sm">Open</a>
                            </div>
                        </div>`
                                : `<p style="margin:0 0 12px 0; color:#b45309; font-size:0.88rem;">No organization subdomain is linked — repair tenant registry before sharing a login link.</p>`
                        }
                        <p style="margin:0 0 12px 0; color:#64748b; font-size:0.88rem; line-height:1.4;">
                            Fix typos in the owner contact, then resend the setup email so they can choose a password. If SMTP is not configured on the server, copy the setup link below or configure <code>SMTP_*</code> in the backend environment.
                        </p>
                        <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap:10px;">
                            <div style="grid-column: 1 / -1;">
                                <label style="display:block; font-weight:600; margin-bottom:4px; font-size:0.85rem;">Company name</label>
                                <input id="lic-prof-name" type="text" value="${esc(c.name || '')}" maxlength="255" style="width:100%; max-width:480px; padding:8px 10px; border:1px solid #e2e8f0; border-radius:8px;">
                            </div>
                            <div>
                                <label style="display:block; font-weight:600; margin-bottom:4px; font-size:0.85rem;">Owner email (login / invites)</label>
                                <input id="lic-prof-email" type="email" value="${esc(c.email || '')}" style="width:100%; padding:8px 10px; border:1px solid #e2e8f0; border-radius:8px;">
                            </div>
                            <div>
                                <label style="display:block; font-weight:600; margin-bottom:4px; font-size:0.85rem;">Phone</label>
                                <input id="lic-prof-phone" type="text" value="${esc(c.phone || '')}" maxlength="50" style="width:100%; padding:8px 10px; border:1px solid #e2e8f0; border-radius:8px;">
                            </div>
                            <div>
                                <label style="display:block; font-weight:600; margin-bottom:4px; font-size:0.85rem;">Owner full name <span style="font-weight:400;color:#64748b;">(suggested username)</span></label>
                                <input id="lic-prof-admin-name" type="text" value="${esc(c.tenant_admin_full_name || '')}" maxlength="255" style="width:100%; padding:8px 10px; border:1px solid #e2e8f0; border-radius:8px;">
                            </div>
                            <div style="grid-column: 1 / -1;">
                                <label style="display:block; font-weight:600; margin-bottom:4px; font-size:0.85rem;">Customer portal · WhatsApp (upgrades)</label>
                                <input id="lic-prof-portal-wa" type="text" value="${esc(c.portal_upgrade_whatsapp || '')}" maxlength="32" placeholder="e.g. 0708476318 — overrides platform default on marketing portal" style="width:100%; max-width:480px; padding:8px 10px; border:1px solid #e2e8f0; border-radius:8px;">
                                <div style="margin-top:6px; font-size:0.78rem; color:#64748b;">Shown on <code>/marketing/portal.html</code> “Contact WhatsApp”. Leave blank to use server default (<code>PORTAL_DEFAULT_WHATSAPP</code>).</div>
                            </div>
                        </div>
                        <button type="button" id="lic-save-profile" class="btn btn-primary" style="margin-top:12px;">Save organization</button>
                        <div style="margin-top:16px; padding-top:14px; border-top:1px solid #e2e8f0;">
                            <div style="font-weight:600; margin-bottom:6px;">Setup invite</div>
                            ${
                                tenantIdForInvite
                                    ? `<p style="margin:0 0 8px 0; font-size:0.85rem; color:#475569;">Tenant <code>${esc(tenantIdForInvite)}</code>${c.tenant_subdomain ? ` · subdomain <code>${esc(c.tenant_subdomain)}</code>` : ''}</p>
                                <button type="button" id="lic-resend-invite" class="btn btn-secondary">Resend setup invite email</button>
                                <span id="lic-invite-action-status" style="margin-left:10px; color:#64748b; font-size:0.85rem;"></span>`
                                    : `<p style="margin:0; color:#b45309; font-size:0.88rem;">No tenant registry row is linked to this company — invites cannot be sent until provisioning is repaired.</p>`
                            }
                        </div>
                    </div>

                    <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap:16px; margin-top:16px;">
                        <div style="border:1px solid #e2e8f0; border-radius:10px; padding:12px; grid-column: 1 / -1;">
                            <h3 style="margin:0 0 6px 0;">Subscription &amp; plan</h3>
                            <p style="margin:0 0 12px 0; color:#64748b; font-size:0.88rem; line-height:1.4;">
                                Kenya list prices and branch <strong>seat credits</strong> are in the playbook at the top of this page.
                                Choose a tier to preset caps. <strong>retail_solo</strong> = affordable; <strong>retail_pro</strong> = full retail (recommended).
                            </p>
                            <div id="lic-tier-grid" style="display:grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap:10px;">
                                ${SAAS_TIERS.map((t) => {
                                    const cur = ((c.subscription_plan || '').trim().toLowerCase() === t.slug);
                                    const b = cur ? '#4338ca' : '#e2e8f0';
                                    const bg = cur ? '#f5f3ff' : '#fff';
                                    const ring = cur ? '0 0 0 3px rgba(67,56,202,0.35), 0 4px 14px rgba(67,56,202,0.12)' : 'none';
                                    return `
                                <button type="button" class="lic-tier-card" data-tier-slug="${esc(t.slug)}" style="cursor:pointer; text-align:left; border:2px solid ${b}; background:${bg}; border-radius:10px; padding:10px 12px; font:inherit; box-shadow:${ring}; outline:${cur ? '2px solid #4338ca' : 'none'}; outline-offset:2px;">
                                    <div style="font-weight:700; font-size:0.95rem;">${esc(t.title)}</div>
                                    <div style="color:#64748b; font-size:0.78rem; margin:4px 0 6px;">${esc(t.subtitle)}</div>
                                    <div style="font-weight:600; color:#4338ca; font-size:0.85rem;">${esc(t.price)}</div>
                                    <ul style="margin:8px 0 0; padding-left:18px; color:#475569; font-size:0.78rem; line-height:1.35;">
                                        <li>Users: ${_licFormatCap(t.users)}</li>
                                        <li>Branches: ${_licFormatCap(t.branches)}</li>
                                        <li>Branch credits: ${_licFormatCap(t.branch_credits != null ? t.branch_credits : t.branches)}</li>
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
                                <input id="lic-plan-slug-adv" value="${esc(c.subscription_plan || '')}" placeholder="e.g. retail_solo or retail_pro" style="width:100%; max-width:420px; padding:8px 10px; border:1px solid #e2e8f0; border-radius:8px; font-family:monospace; font-size:12px;">
                            </details>
                            <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap:10px; margin-top:12px;">
                                <div>
                                    <label style="display:block; font-weight:600; margin-bottom:4px; font-size:0.85rem;">User cap</label>
                                    <input id="lic-cap-users" type="number" min="1" placeholder="blank + non-demo → unlimited" value="${dispUserCap != null ? esc(String(dispUserCap)) : ''}" style="width:100%; padding:8px 10px; border:1px solid #e2e8f0; border-radius:8px;">
                                </div>
                                <div>
                                    <label style="display:block; font-weight:600; margin-bottom:4px; font-size:0.85rem;">Branch cap</label>
                                    <input id="lic-cap-branches" type="number" min="1" placeholder="blank + non-demo → unlimited" value="${dispBranchCap != null ? esc(String(dispBranchCap)) : ''}" style="width:100%; padding:8px 10px; border:1px solid #e2e8f0; border-radius:8px;">
                                </div>
                                <div>
                                    <label style="display:block; font-weight:600; margin-bottom:4px; font-size:0.85rem;">Product cap</label>
                                    <input id="lic-cap-products" type="number" min="1" placeholder="blank + non-demo → unlimited" value="${dispProductCap != null ? esc(String(dispProductCap)) : ''}" style="width:100%; padding:8px 10px; border:1px solid #e2e8f0; border-radius:8px;">
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
                            <input id="lic-trial" type="datetime-local" value="${esc(toLocalDatetimeValue(trialForInput))}" style="width:100%; max-width:320px; padding:8px 10px; border:1px solid #e2e8f0; border-radius:8px;">
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

                    </details>

                    <details class="gov-advanced">
                    <summary>Licensed capabilities</summary>
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

                    </details>

                    <details class="gov-advanced">
                    <summary>Fiscal governance (eTIMS)</summary>
                    <div style="border:1px solid #e2e8f0; border-radius:10px; padding:12px; margin-top:16px;">
                        <h3 style="margin:0 0 10px 0;">eTIMS (KRA / Gava Connect onboarding)</h3>
                        <p style="margin:0 0 10px 0; color:#666; font-size:0.9rem; line-height:1.45;">
                            Paste values from <strong>developer.go.ke</strong> validation / test screens. Credentials are stored per company and branch and are used for OAuth and OSCU calls.
                            <strong> Save branch fields</strong> before <strong>Test connection</strong> (the server reads stored values).
                        </p>
                        <div style="margin-bottom:14px; padding:12px; background:#fffbeb; border-radius:10px; border:1px solid #fcd34d;">
                            <div style="font-weight:700; margin-bottom:8px;">KRA execution (tenant)</div>
                            <p style="margin:0 0 10px 0; color:#78350f; font-size:0.88rem; line-height:1.45;">
                                When enabled, this company may enqueue KRA item and invoice work. The deployment must run the outbox worker (<code>KRA_OUTBOX_WORKER_ENABLED</code>).
                            </p>
                            <label style="display:flex; gap:10px; align-items:center; margin-bottom:10px; font-weight:600;">
                                <input type="checkbox" id="lic-etims-kra-enabled" ${etims && etims.kra_enabled ? 'checked' : ''} />
                                Enable KRA for this company
                            </label>
                            <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap:12px; align-items:end;">
                                <div>
                                    <label style="display:block; font-weight:600; font-size:0.85rem; margin-bottom:4px;">Company KRA mode</label>
                                    <select id="lic-etims-kra-mode" class="form-input" style="width:100%; padding:8px 10px; border:1px solid #e2e8f0; border-radius:8px;">
                                        <option value="sandbox" ${String((etims && etims.kra_mode) || 'sandbox') === 'sandbox' ? 'selected' : ''}>sandbox</option>
                                        <option value="production" ${String((etims && etims.kra_mode) || '') === 'production' ? 'selected' : ''}>production</option>
                                    </select>
                                </div>
                                <div style="font-size:0.88rem; color:#64748b;">
                                    KRA onboarded: <strong>${esc(fmtIso(etims && etims.kra_onboarded_at))}</strong>
                                </div>
                            </div>
                        </div>
                        <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap:12px; margin-bottom:14px; padding:12px; background:#f8fafc; border-radius:10px; border:1px solid #e2e8f0;">
                            <div style="grid-column: 1 / -1;">
                                <label style="display:block; font-weight:600; margin-bottom:6px;">Company PIN (TIN / client PIN)</label>
                                <input id="lic-etims-pin" value="${esc((etims && etims.company_pin) || c.pin || '')}" placeholder="e.g. P123456789A" style="width:100%; max-width:420px; padding:8px 10px; border:1px solid #e2e8f0; border-radius:8px;">
                            </div>
                            <div style="grid-column: 1 / -1;">
                                <label style="display:block; font-weight:600; margin-bottom:6px;">Trader invoicing system name <span style="font-weight:400;color:#64748b;">(KRA app label — for SightOps ops traceability)</span></label>
                                <input id="lic-etims-trader-name" value="${esc((etims && etims.trader_invoicing_system_name) || '')}" placeholder="e.g. SightOps ERP (as registered on developer.go.ke)" style="width:100%; max-width:520px; padding:8px 10px; border:1px solid #e2e8f0; border-radius:8px;">
                            </div>
                            <div>
                                <label style="display:block; font-weight:600; margin-bottom:6px;">Integrator PIN</label>
                                <input id="lic-etims-integrator" type="password" autocomplete="new-password" placeholder="${etims && etims.has_company_integrator_pin ? '•••• stored — paste to replace' : 'Paste from KRA validation'}" style="width:100%; padding:8px 10px; border:1px solid #e2e8f0; border-radius:8px;">
                                <label style="display:flex; gap:8px; align-items:center; margin-top:8px; font-size:0.88rem; color:#475569;">
                                    <input type="checkbox" id="lic-etims-clear-integrator">
                                    Clear stored integrator PIN
                                </label>
                            </div>
                            <div style="display:flex; align-items:flex-end;">
                                <button type="button" id="lic-etims-save-company" class="btn btn-secondary">Save company eTIMS identity</button>
                            </div>
                        </div>

                        ${
                            etims && Array.isArray(etims.branches) && etims.branches.length
                                ? `${etims.branches
                                      .map((b) => {
                                          const bid = esc(b.branch_id);
                                          const st = String(b.connection_status || 'not_configured');
                                          const verified = st.toLowerCase() === 'verified';
                                          const sol = esc((b.etims_solution || 'OSCU').toUpperCase());
                                          return `
                            <div data-lic-etims-branch="${bid}" style="margin-bottom:12px; border:1px solid #e2e8f0; border-radius:10px; padding:12px; background:#fff;">
                                <div style="display:flex; flex-wrap:wrap; align-items:center; justify-content:space-between; gap:10px; margin-bottom:10px;">
                                    <div>
                                        <div style="font-weight:700;">${esc(b.branch_name || '—')}</div>
                                        <div style="color:#64748b; font-size:0.85rem;">Branch code <code>${esc(b.branch_code || '—')}</code></div>
                                    </div>
                                    <div style="display:flex; flex-wrap:wrap; gap:8px; align-items:center;">
                                        ${etimsBadge(st, !!b.enabled)}
                                        <span style="color:#64748b; font-size:0.85rem;">Last test: ${esc(fmtIso(b.last_tested_at))}</span>
                                    </div>
                                </div>
                                <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap:10px;">
                                    <div>
                                        <label style="display:block; font-weight:600; font-size:0.8rem; margin-bottom:4px;">Environment</label>
                                        <select data-etims-env class="form-input" style="width:100%; padding:6px 8px; border:1px solid #e2e8f0; border-radius:8px;">
                                            <option value="sandbox" ${String(b.environment || 'sandbox') === 'sandbox' ? 'selected' : ''}>sandbox</option>
                                            <option value="production" ${String(b.environment || '') === 'production' ? 'selected' : ''}>production</option>
                                        </select>
                                    </div>
                                    <div>
                                        <label style="display:block; font-weight:600; font-size:0.8rem; margin-bottom:4px;">eTIMS solution</label>
                                        <input data-etims-solution value="${sol}" placeholder="OSCU" maxlength="50" style="width:100%; padding:6px 8px; border:1px solid #e2e8f0; border-radius:8px;">
                                    </div>
                                    <div>
                                        <label style="display:block; font-weight:600; font-size:0.8rem; margin-bottom:4px;">KRA Branch Id (bhfId)</label>
                                        <input data-etims-bhf value="${esc(b.kra_bhf_id || '')}" placeholder="e.g. 00" style="width:100%; padding:6px 8px; border:1px solid #e2e8f0; border-radius:8px;">
                                    </div>
                                    <div>
                                        <label style="display:block; font-weight:600; font-size:0.8rem; margin-bottom:4px;">Device serial</label>
                                        <input data-etims-dvc value="${esc(b.device_serial || '')}" style="width:100%; padding:6px 8px; border:1px solid #e2e8f0; border-radius:8px;">
                                    </div>
                                    <div>
                                        <label style="display:block; font-weight:600; font-size:0.8rem; margin-bottom:4px;">Apigee App ID</label>
                                        <input data-etims-apigee value="${esc(b.apigee_app_id || '')}" placeholder="UUID from validation" style="width:100%; padding:6px 8px; border:1px solid #e2e8f0; border-radius:8px;">
                                    </div>
                                    <div>
                                        <label style="display:block; font-weight:600; font-size:0.8rem; margin-bottom:4px;">Application test PIN</label>
                                        <input data-etims-client-tax value="${esc(b.client_tax_pin || '')}" placeholder="e.g. P600003213A" style="width:100%; padding:6px 8px; border:1px solid #e2e8f0; border-radius:8px;">
                                    </div>
                                    <div>
                                        <label style="display:block; font-weight:600; font-size:0.8rem; margin-bottom:4px;">Consumer Key</label>
                                        <input data-etims-consumer-key value="${esc(b.consumer_key || '')}" autocomplete="off" style="width:100%; padding:6px 8px; border:1px solid #e2e8f0; border-radius:8px; font-family:monospace; font-size:11px;">
                                    </div>
                                    <div>
                                        <label style="display:block; font-weight:600; font-size:0.8rem; margin-bottom:4px;">Consumer Secret</label>
                                        <input data-etims-consumer-secret type="password" value="" autocomplete="new-password" placeholder="${b.has_consumer_secret ? '•••••••• (stored)' : 'paste secret'}" style="width:100%; padding:6px 8px; border:1px solid #e2e8f0; border-radius:8px;">
                                    </div>
                                    <div>
                                        <label style="display:block; font-weight:600; font-size:0.8rem; margin-bottom:4px;">CMC key</label>
                                        <input data-etims-cmc type="password" value="" placeholder="${b.has_cmc_key ? '•••••••• (stored)' : 'Optional — leave blank to let Test fetch & save from KRA'}" style="width:100%; padding:6px 8px; border:1px solid #e2e8f0; border-radius:8px;">
                                    </div>
                                    <div style="display:flex; flex-direction:column; justify-content:flex-end; gap:8px;">
                                        <label style="display:flex; gap:8px; align-items:center; font-size:0.88rem;">
                                            <input data-etims-enabled type="checkbox" ${b.enabled ? 'checked' : ''} ${verified ? '' : 'disabled'} />
                                            Submission enabled
                                        </label>
                                        <div style="display:flex; flex-wrap:wrap; gap:8px;">
                                            <button type="button" class="btn btn-secondary btn-sm" data-etims-save>Save branch</button>
                                            <button type="button" class="btn btn-primary btn-sm" data-etims-test>Test connection</button>
                                        </div>
                                    </div>
                                </div>
                            </div>`;
                                      })
                                      .join('')}
                        <div style="margin-top:10px; color:#64748b; font-size:0.85rem;">
                            Turn on <strong>Submission enabled</strong> only after <strong>Verified</strong>. <strong>CMC key</strong> is persisted automatically when KRA returns it during Test (same idea as gavaetims); you can still paste one manually if needed (e.g. resultCd 902 without key).
                        </div>`
                                : `<div style="color:#666;">No branches found (or eTIMS endpoint unavailable).</div>`
                        }
                    </details>
                </div>
            `;

            if (gov && typeof govUi.wireGovernancePanel === 'function') {
                govUi.wireGovernancePanel(mount, api, companyId, toast, () => loadCompanyDetail(companyId));
            }

            document.getElementById('lic-back')?.addEventListener('click', () => void loadCompanies());

            document.getElementById('lic-copy-org-login')?.addEventListener('click', () => {
                const url = document.getElementById('lic-org-login-url')?.value || orgLoginUrl;
                if (url) void copyTextToClipboard(url, toast);
            });

            document.getElementById('lic-save-profile')?.addEventListener('click', async () => {
                try {
                    if (typeof api.patchProfile !== 'function') throw new Error('Profile API not available');
                    const name = (document.getElementById('lic-prof-name')?.value || '').trim();
                    const email = (document.getElementById('lic-prof-email')?.value || '').trim();
                    const phone = (document.getElementById('lic-prof-phone')?.value || '').trim() || null;
                    const admin_full_name = (document.getElementById('lic-prof-admin-name')?.value || '').trim() || null;
                    const portal_upgrade_whatsapp =
                        (document.getElementById('lic-prof-portal-wa')?.value || '').trim() || null;
                    if (!name) throw new Error('Company name is required');
                    if (!email) throw new Error('Owner email is required');
                    await api.patchProfile(companyId, {
                        name,
                        email,
                        phone,
                        admin_full_name,
                        portal_upgrade_whatsapp,
                    });
                    toast('Organization saved', 'success');
                    await loadCompanyDetail(companyId);
                } catch (e) {
                    toast(e.message || 'Failed to save organization', 'error');
                }
            });

            document.getElementById('lic-resend-invite')?.addEventListener('click', async () => {
                const tid = tenantIdForInvite;
                const st = document.getElementById('lic-invite-action-status');
                if (!tid) return;
                if (st) st.textContent = 'Sending…';
                try {
                    const invApi = window.API?.admin?.tenants?.invites;
                    if (!invApi?.create) throw new Error('Invite API not available');
                    const inv = await invApi.create(tid, { expires_in_days: 7, send_email: true });
                    const url = inv && inv.setup_url ? String(inv.setup_url) : '';
                    if (st) {
                        st.textContent = inv?.email_sent ? 'Email queued.' : 'Invite created; email may be disabled (check SMTP).';
                    }
                    if (url) {
                        toast(inv?.email_sent ? 'Invite email queued' : `Setup link: ${url}`, 'info');
                    } else {
                        toast('Invite created', 'success');
                    }
                } catch (e) {
                    if (st) st.textContent = '';
                    toast(e.message || 'Invite failed', 'error');
                }
            });

            const licApplyTierToForm = (slug) => {
                const t = _tierBySlug(slug);
                const adv = document.getElementById('lic-plan-slug-adv');
                if (adv) adv.value = slug || '';
                const statusEl = document.getElementById('lic-status');
                if (statusEl && slug && slug !== 'demo') {
                    const cur = (statusEl.value || '').trim().toLowerCase();
                    if (!cur || cur === 'demo') statusEl.value = 'active';
                }
                if (!t) return;
                const u = document.getElementById('lic-cap-users');
                const br = document.getElementById('lic-cap-branches');
                const pr = document.getElementById('lic-cap-products');
                if (u) u.value = t.users != null ? String(t.users) : '';
                if (br) br.value = t.branches != null ? String(t.branches) : '';
                if (pr) pr.value = t.products != null ? String(t.products) : '';
                mount.querySelectorAll('.lic-tier-card').forEach((btn) => {
                    const on = (btn.getAttribute('data-tier-slug') || '') === slug;
                    btn.style.borderColor = on ? '#4338ca' : '#e2e8f0';
                    btn.style.background = on ? '#f5f3ff' : '#fff';
                    btn.style.boxShadow = on ? '0 0 0 3px rgba(67,56,202,0.35), 0 4px 14px rgba(67,56,202,0.12)' : 'none';
                    btn.style.outline = on ? '2px solid #4338ca' : 'none';
                    btn.style.outlineOffset = on ? '2px' : '';
                });
            };

            mount.querySelectorAll('.lic-tier-card').forEach((btn) => {
                btn.addEventListener('click', () => {
                    const slug = btn.getAttribute('data-tier-slug');
                    if (slug) licApplyTierToForm(slug);
                });
            });

            document.getElementById('lic-etims-save-company')?.addEventListener('click', async () => {
                try {
                    const pin = (document.getElementById('lic-etims-pin')?.value || '').trim() || null;
                    const trader_invoicing_system_name =
                        (document.getElementById('lic-etims-trader-name')?.value || '').trim() || null;
                    const integratorRaw = (document.getElementById('lic-etims-integrator')?.value || '').trim();
                    const clear_integrator_pin = !!document.getElementById('lic-etims-clear-integrator')?.checked;
                    const kra_enabled = !!document.getElementById('lic-etims-kra-enabled')?.checked;
                    const kra_mode = (document.getElementById('lic-etims-kra-mode')?.value || 'sandbox').trim();
                    if (typeof api.etimsPatchCompanyPin !== 'function') throw new Error('eTIMS API not available');
                    const body = { pin, trader_invoicing_system_name, kra_enabled, kra_mode };
                    if (clear_integrator_pin) body.clear_integrator_pin = true;
                    else if (integratorRaw) body.integrator_pin = integratorRaw;
                    await api.etimsPatchCompanyPin(companyId, body);
                    toast('Saved company eTIMS identity', 'success');
                    await loadCompanyDetail(companyId);
                } catch (e) {
                    toast(e.message || 'Failed to save company eTIMS fields', 'error');
                }
            });

            mount.querySelectorAll('[data-lic-etims-branch]').forEach((panel) => {
                const branchId = panel.getAttribute('data-lic-etims-branch');
                const saveBtn = panel.querySelector('[data-etims-save]');
                const testBtn = panel.querySelector('[data-etims-test]');
                const runSave = async (opts) => {
                    const silent = !!(opts && opts.silent);
                    if (!branchId) return;
                    if (typeof api.etimsPatchBranch !== 'function') throw new Error('eTIMS API not available');
                    const environment = panel.querySelector('[data-etims-env]')?.value || null;
                    const kra_bhf_id = (panel.querySelector('[data-etims-bhf]')?.value || '').trim() || null;
                    const device_serial = (panel.querySelector('[data-etims-dvc]')?.value || '').trim() || null;
                    const etims_solution = (panel.querySelector('[data-etims-solution]')?.value || '').trim() || null;
                    const apigee_app_id = (panel.querySelector('[data-etims-apigee]')?.value || '').trim() || null;
                    const client_tax_pin = (panel.querySelector('[data-etims-client-tax]')?.value || '').trim() || null;
                    const consumer_key = (panel.querySelector('[data-etims-consumer-key]')?.value || '').trim() || null;
                    const consumer_secret_raw = (panel.querySelector('[data-etims-consumer-secret]')?.value || '').trim();
                    const cmc_key = (panel.querySelector('[data-etims-cmc]')?.value || '').trim() || null;
                    const enabled = !!panel.querySelector('[data-etims-enabled]')?.checked;
                    const payload = {
                        environment,
                        kra_bhf_id,
                        device_serial,
                        etims_solution,
                        apigee_app_id,
                        client_tax_pin,
                        consumer_key,
                        enabled,
                    };
                    if (cmc_key) payload.cmc_key = cmc_key;
                    if (consumer_secret_raw) payload.consumer_secret = consumer_secret_raw;
                    await api.etimsPatchBranch(branchId, payload);
                    if (!silent) {
                        toast('Saved branch eTIMS', 'success');
                        await loadCompanyDetail(companyId);
                    }
                };
                const runTest = async () => {
                    if (!branchId) return;
                    if (typeof api.etimsTestBranchConnection !== 'function') throw new Error('eTIMS API not available');
                    const kra_bhf_chk = (panel.querySelector('[data-etims-bhf]')?.value || '').trim();
                    const dvc_chk = (panel.querySelector('[data-etims-dvc]')?.value || '').trim();
                    const env_chk = (panel.querySelector('[data-etims-env]')?.value || '').trim();
                    if (!kra_bhf_chk) {
                        throw new Error(
                            'KRA Branch Id (bhfId) is empty — use the value from developer.go.ke (often 00), click Save branch, then Test.'
                        );
                    }
                    if (!dvc_chk) {
                        throw new Error('Device serial is empty — fill it from your Gava validation screen, Save branch, then Test.');
                    }
                    if (env_chk === 'production') {
                        const ok = window.confirm(
                            'Environment is set to production. Gava Connect validation is sandbox — tests usually fail against production. Switch Environment to sandbox and Save branch, unless you intend production.'
                        );
                        if (!ok) return;
                    }
                    toast('Saving branch, then testing…', 'info');
                    await runSave({ silent: true });
                    const res = await api.etimsTestBranchConnection(branchId);
                    if (!res || res.success !== true) {
                        const hint = res && res.hint ? String(res.hint) : '';
                        const msg =
                            (res && res.response && (res.response.resultMsg || res.response.message)) ||
                            (res && res.response_text) ||
                            hint ||
                            'KRA did not return success — check credentials and sandbox vs production.';
                        throw new Error(typeof msg === 'string' ? msg : 'eTIMS test failed');
                    }
                    let okMsg = 'eTIMS test succeeded (verified)';
                    if (res.cmc_extracted_from_response) okMsg += ' — CMC key returned by KRA and saved.';
                    toast(okMsg, 'success');
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
                        try {
                            await loadCompanyDetail(companyId);
                        } catch (_) {}
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

