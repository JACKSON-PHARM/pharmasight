/**
 * Platform Admin: Companies list
 * Route: #platform-admin-companies
 */
(function () {
    function escapeHtml(s) {
        const d = document.createElement('div');
        d.textContent = s == null ? '' : String(s);
        return d.innerHTML;
    }

    function fmtDate(s) {
        if (!s) return '—';
        try {
            return new Date(s).toLocaleString();
        } catch (_) {
            return String(s);
        }
    }

    function showErr(msg) {
        if (typeof window.showToast === 'function') window.showToast(msg, 'error');
        else alert(msg);
    }

    async function loadPlatformAdminCompanies() {
        const el = document.getElementById('platform-admin-companies');
        if (!el) return;
        el.innerHTML = '<div class="card" style="padding:1rem;"><p>Loading companies…</p></div>';
        try {
            const list = await API.platformAdmin.companies();
            const rows = (Array.isArray(list) ? list : [])
                .map((c) => {
                    const activeBadge = c.is_active ? '<span class="badge badge-success">active</span>' : '<span class="badge badge-danger">inactive</span>';
                    return `
                        <tr data-cid="${escapeHtml(c.id)}" style="cursor:pointer;">
                            <td>${escapeHtml(c.name || '—')}</td>
                            <td>${escapeHtml(c.subscription_plan || '—')}</td>
                            <td>${escapeHtml(c.subscription_status || '—')}</td>
                            <td>${escapeHtml(fmtDate(c.trial_expires_at))}</td>
                            <td>${activeBadge}</td>
                        </tr>
                    `;
                })
                .join('');

            el.innerHTML = `
                <div class="card" style="padding:1rem;">
                    <div style="display:flex; align-items:center; justify-content:space-between; gap:1rem; flex-wrap:wrap;">
                        <h2 style="margin:0;">Platform Admin · Companies</h2>
                        <div style="display:flex; gap:0.5rem; align-items:center;">
                            <input id="paCompanySearch" class="form-input" placeholder="Search company…" style="min-width:220px;" />
                            <button type="button" class="btn btn-outline btn-sm" id="paCompanySearchBtn">Search</button>
                        </div>
                    </div>
                    <div style="overflow:auto; margin-top:0.75rem;">
                        <table class="data-table" style="width:100%;">
                            <thead>
                                <tr>
                                    <th>Company</th>
                                    <th>Plan</th>
                                    <th>Status</th>
                                    <th>Trial expires</th>
                                    <th>Active</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${rows || '<tr><td colspan="5">No companies</td></tr>'}
                            </tbody>
                        </table>
                    </div>
                </div>
            `;

            const tbody = el.querySelector('tbody');
            if (tbody) {
                tbody.querySelectorAll('tr[data-cid]').forEach((tr) => {
                    tr.addEventListener('click', () => {
                        const cid = tr.getAttribute('data-cid');
                        window.location.hash = `#platform-admin-company?id=${encodeURIComponent(cid)}`;
                        if (typeof window.loadPage === 'function') void window.loadPage('platform-admin-company');
                    });
                });
            }

            const doSearch = async () => {
                const q = (document.getElementById('paCompanySearch')?.value || '').trim();
                try {
                    const filtered = await API.platformAdmin.companies(q ? { q } : {});
                    // reload by re-rendering using the same function (cheap enough)
                    // but keep the search term in the box
                    await loadPlatformAdminCompaniesFromList(filtered, q);
                } catch (e) {
                    showErr(e.message || 'Search failed');
                }
            };

            document.getElementById('paCompanySearchBtn')?.addEventListener('click', () => void doSearch());
            document.getElementById('paCompanySearch')?.addEventListener('keydown', (ev) => {
                if (ev.key === 'Enter') {
                    ev.preventDefault();
                    void doSearch();
                }
            });
        } catch (e) {
            el.innerHTML = `<div class="card" style="padding:1rem;"><p class="text-danger">Could not load companies. ${escapeHtml(e.message || '')}</p></div>`;
        }
    }

    async function loadPlatformAdminCompaniesFromList(list, searchValue) {
        const el = document.getElementById('platform-admin-companies');
        if (!el) return;
        const rows = (Array.isArray(list) ? list : [])
            .map((c) => {
                const activeBadge = c.is_active ? '<span class="badge badge-success">active</span>' : '<span class="badge badge-danger">inactive</span>';
                return `
                    <tr data-cid="${escapeHtml(c.id)}" style="cursor:pointer;">
                        <td>${escapeHtml(c.name || '—')}</td>
                        <td>${escapeHtml(c.subscription_plan || '—')}</td>
                        <td>${escapeHtml(c.subscription_status || '—')}</td>
                        <td>${escapeHtml(fmtDate(c.trial_expires_at))}</td>
                        <td>${activeBadge}</td>
                    </tr>
                `;
            })
            .join('');

        el.querySelector('tbody').innerHTML = rows || '<tr><td colspan="5">No companies</td></tr>';
        const input = document.getElementById('paCompanySearch');
        if (input) input.value = searchValue || '';

        el.querySelectorAll('tr[data-cid]').forEach((tr) => {
            tr.addEventListener('click', () => {
                const cid = tr.getAttribute('data-cid');
                window.location.hash = `#platform-admin-company?id=${encodeURIComponent(cid)}`;
                if (typeof window.loadPage === 'function') void window.loadPage('platform-admin-company');
            });
        });
    }

    window.loadPlatformAdminCompanies = loadPlatformAdminCompanies;
})();

