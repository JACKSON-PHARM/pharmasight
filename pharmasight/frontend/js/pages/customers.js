/**
 * Customer hub — CRM foundation (retail relationships & wholesale B2B accounts).
 */
(function () {
    'use strict';

    function esc(s) {
        if (s == null) return '';
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function fmtMoney(n) {
        const x = Number(n || 0);
        return 'KES ' + x.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }

    function localDateString(d) {
        const dt = d || new Date();
        const y = dt.getFullYear();
        const m = String(dt.getMonth() + 1).padStart(2, '0');
        const day = String(dt.getDate()).padStart(2, '0');
        return y + '-' + m + '-' + day;
    }

    function localMonthStart(d) {
        const dt = d || new Date();
        return localDateString(new Date(dt.getFullYear(), dt.getMonth(), 1));
    }

    const customerStatementDateFrom = {};
    const customerStatementDateTo = {};
    const customerDetailTab = {};

    function companyId() {
        return window.CONFIG && CONFIG.COMPANY_ID;
    }

    function branchId() {
        return window.CONFIG && CONFIG.BRANCH_ID;
    }

    function hubMode() {
        try {
            if (window.BranchContext && typeof BranchContext.isWholesaleDistributionBranch === 'function') {
                if (BranchContext.isWholesaleDistributionBranch()) return 'wholesale';
            }
            if (window.BranchContext && typeof BranchContext.getInvoiceWorkflowType === 'function') {
                if (BranchContext.getInvoiceWorkflowType() === 'RETAIL_COUNTER') return 'retail';
            }
        } catch (_) {}
        return 'retail';
    }

    function hubCopy(mode) {
        if (mode === 'wholesale') {
            return {
                title: 'Customers',
                subtitle: 'B2B trading accounts — credit control, performance, and wholesale sales.',
                newLabel: 'New customer',
                emptyTitle: 'Set up your first wholesale customer',
                emptySteps: [
                    'Create a customer account with credit terms and contact details.',
                    'Activate the account when ready to trade; deactivate to block new sales.',
                    'Use <strong>New sale</strong> to invoice; record payments and follow-ups on the profile.',
                ],
                customerTypes: [
                    ['PHARMACY', 'Pharmacy'],
                    ['HOSPITAL', 'Hospital'],
                    ['CLINIC', 'Clinic'],
                    ['INSTITUTION', 'Institution'],
                    ['OTHER', 'Other'],
                ],
                profileHeading: 'Customer profile',
                saleBtn: 'New wholesale sale',
            };
        }
        return {
            title: 'Customers',
            subtitle: 'Client relationships — refills, follow-ups, and account sales at this branch.',
            newLabel: 'New customer',
            emptyTitle: 'Add your first customer',
            emptySteps: [
                'Register clients you want to track (refills, visits, reminders).',
                'Log follow-ups and calls from the customer profile.',
                'Link them on a sale when invoicing on credit or by name.',
            ],
            customerTypes: [
                ['OTHER', 'Walk-in / household'],
                ['PHARMACY', 'Pharmacy'],
                ['CLINIC', 'Clinic'],
            ],
            profileHeading: 'Customer profile',
            saleBtn: 'New sale',
        };
    }

    function accessHintHtml(err) {
        const msg = (err && (err.message || err.detail)) || String(err || '');
        if (/Wholesale module is not licensed/i.test(msg)) {
            return `<p style="margin-top:0.75rem;">Enable <strong>Wholesale</strong> under Admin → Licensed capabilities, then refresh.</p>`;
        }
        if (/Wholesale distribution fiscal doctrine/i.test(msg) || /Customer management is available/i.test(msg)) {
            return `<p style="margin-top:0.75rem;">Set this branch to <strong>Wholesale distribution</strong> or <strong>Retail counter</strong> in Admin → Branch governance.</p>`;
        }
        if (/X-Branch-ID/i.test(msg)) {
            return `<p style="margin-top:0.75rem;">Select a branch from the header, then open this page again.</p>`;
        }
        return '';
    }

    function setupChecklistHtml(copy, count) {
        if (count > 0) return '';
        return `
            <div class="card" style="padding:1.25rem;margin-bottom:1rem;border-left:4px solid var(--primary-color);">
                <h3 style="margin:0 0 0.5rem;font-size:1rem;">${esc(copy.emptyTitle)}</h3>
                <ol style="margin:0;padding-left:1.2rem;line-height:1.6;font-size:0.9rem;">
                    ${copy.emptySteps.map((s) => `<li style="margin-bottom:0.35rem;">${s}</li>`).join('')}
                </ol>
            </div>`;
    }

    let _customerCache = null;
    let _customerHubMounted = false;
    let _customerSearchSeq = 0;
    let _customerSearchDebounce = null;
    let _tableFilterTerm = '';

    function whatsAppUrl(phone) {
        if (!phone) return null;
        let digits = String(phone).replace(/\D/g, '');
        if (!digits) return null;
        if (digits.startsWith('0')) digits = '254' + digits.slice(1);
        else if (digits.length <= 9) digits = '254' + digits;
        return 'https://wa.me/' + digits;
    }

    function customerHaystack(c) {
        return [c.name, c.phone, c.contact_person, c.customer_type].filter(Boolean).join(' ').toLowerCase();
    }

    function customerById(id) {
        if (!_customerCache || !id) return null;
        return _customerCache.find((c) => String(c.id) === String(id)) || null;
    }

    function statusBadgeHtml(c) {
        if (Number(c.overdue_amount) > 0) {
            return '<span class="badge badge-danger" style="font-size:0.7rem;">Overdue</span>';
        }
        if (Number(c.outstanding_balance) > 0) {
            return '<span class="badge badge-warning" style="font-size:0.7rem;">Balance</span>';
        }
        return '<span class="badge badge-success" style="font-size:0.7rem;">Clear</span>';
    }

    function renderCustomerTableRows(list) {
        if (!list || !list.length) {
            return '<tr><td colspan="7" style="padding:1.25rem;text-align:center;color:var(--text-secondary);">No customers yet. Use search above or create a new customer.</td></tr>';
        }
        return list
            .map(
                (c) => `
                <tr class="customer-row" data-id="${esc(c.id)}" style="cursor:pointer">
                    <td><strong>${esc(c.name)}</strong><br><small class="text-muted">${esc(c.customer_type || '')}</small></td>
                    <td>${esc(c.phone || '—')}</td>
                    <td>${esc(c.contact_person || '—')}</td>
                    <td>${statusBadgeHtml(c)}</td>
                    <td class="text-right">${fmtMoney(c.outstanding_balance)}</td>
                    <td class="text-right" style="color:${c.overdue_amount > 0 ? '#b91c1c' : 'inherit'}">${fmtMoney(c.overdue_amount)}</td>
                    <td class="text-right">${fmtMoney(c.this_month_sales)}</td>
                </tr>`
            )
            .join('');
    }

    function bindCustomerTableRows() {
        const page = document.getElementById('customers');
        if (!page) return;
        page.querySelectorAll('.customer-row').forEach((tr) => {
            tr.addEventListener('click', () => {
                const id = tr.getAttribute('data-id');
                if (id) openCustomerProfile(id);
            });
        });
    }

    function refreshCustomerTableBody() {
        const tbody = document.getElementById('customerHubTableBody');
        if (!tbody || !_customerCache) return;
        const term = (_tableFilterTerm || '').toLowerCase().trim();
        let list = _customerCache.slice();
        if (term) list = list.filter((c) => customerHaystack(c).includes(term));
        list.sort((a, b) => {
            const ao = Number(a.overdue_amount) || 0;
            const bo = Number(b.overdue_amount) || 0;
            if (bo !== ao) return bo - ao;
            return (a.name || '').localeCompare(b.name || '');
        });
        tbody.innerHTML = renderCustomerTableRows(list);
        bindCustomerTableRows();
    }

    function hideCustomerSearchDropdown() {
        const dd = document.getElementById('customerHubSearchDropdown');
        if (dd) {
            dd.style.display = 'none';
            dd.innerHTML = '';
        }
    }

    function renderCustomerSearchDropdown(rows, messageHtml) {
        const dd = document.getElementById('customerHubSearchDropdown');
        if (!dd) return;
        if (messageHtml) {
            dd.innerHTML = `<div class="customer-hub-search-hit" style="padding:0.65rem 0.85rem;color:var(--text-secondary);font-size:0.88rem;">${messageHtml}</div>`;
            dd.style.display = 'block';
            return;
        }
        if (!rows || !rows.length) {
            dd.innerHTML =
                '<div class="customer-hub-search-hit" style="padding:0.65rem 0.85rem;color:var(--text-secondary);">No customers found</div>';
            dd.style.display = 'block';
            return;
        }
        dd.innerHTML = rows
            .map((c, idx) => {
                const sub = [c.phone, c.contact_person, c.customer_type].filter(Boolean).join(' · ');
                const out = Number(c.outstanding_balance) || 0;
                const meta =
                    out > 0
                        ? `<span style="color:#b45309;">${fmtMoney(out)} outstanding</span>`
                        : '<span style="color:var(--text-secondary);">Paid up</span>';
                return `<button type="button" class="customer-hub-search-hit" data-idx="${idx}" style="display:block;width:100%;text-align:left;padding:0.55rem 0.85rem;border:none;border-bottom:1px solid var(--border-color);background:#fff;cursor:pointer;">
                    <div style="font-weight:600;">${esc(c.name)}</div>
                    <div style="font-size:0.78rem;color:var(--text-secondary);margin-top:2px;">${esc(sub || '—')} · ${meta}</div>
                </button>`;
            })
            .join('');
        dd._lastResults = rows;
        dd.style.display = 'block';
    }

    async function runCustomerHubSearch(query) {
        const input = document.getElementById('customerHubSearchInput');
        const seq = ++_customerSearchSeq;
        const q = (query || '').trim();
        if (!input || (input.value || '').trim() !== q) return;

        if (q.length < 2) {
            hideCustomerSearchDropdown();
            _tableFilterTerm = q;
            refreshCustomerTableBody();
            return;
        }

        renderCustomerSearchDropdown(null, '<i class="fas fa-spinner fa-spin"></i> Searching…');

        const cid = companyId();
        let hits = [];
        try {
            if (cid && API.customers && API.customers.search) {
                const apiRows = await API.customers.search(q, cid, 12);
                if (seq !== _customerSearchSeq) return;
                hits = (apiRows || []).map(
                    (r) =>
                        customerById(r.id) || {
                            id: r.id,
                            name: r.name,
                            phone: r.phone || '',
                            contact_person: r.contact_person || '',
                        }
                );
            }
        } catch (err) {
            if (seq !== _customerSearchSeq) return;
            renderCustomerSearchDropdown(null, esc((err && err.message) || 'Search failed'));
            return;
        }

        if (seq !== _customerSearchSeq) return;
        if (!hits.length && _customerCache) {
            hits = _customerCache.filter((c) => customerHaystack(c).includes(q.toLowerCase())).slice(0, 12);
        }
        renderCustomerSearchDropdown(hits);
        _tableFilterTerm = q;
        refreshCustomerTableBody();
    }

    function bindCustomerHubSearch() {
        const input = document.getElementById('customerHubSearchInput');
        const dd = document.getElementById('customerHubSearchDropdown');
        if (!input || input.dataset.bound === '1') return;
        input.dataset.bound = '1';

        input.addEventListener('input', () => {
            if (_customerSearchDebounce) clearTimeout(_customerSearchDebounce);
            _customerSearchDebounce = setTimeout(() => void runCustomerHubSearch(input.value), 350);
        });

        input.addEventListener('focus', () => {
            const q = (input.value || '').trim();
            if (q.length >= 2) void runCustomerHubSearch(q);
            else if (_customerCache && _customerCache.length) renderCustomerSearchDropdown(_customerCache.slice(0, 8));
        });

        input.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') hideCustomerSearchDropdown();
        });

        if (dd && dd.dataset.bound !== '1') {
            dd.dataset.bound = '1';
            dd.addEventListener('mousedown', (e) => {
                const hit = e.target.closest('.customer-hub-search-hit');
                if (!hit || !dd._lastResults) return;
                e.preventDefault();
                const idx = parseInt(hit.getAttribute('data-idx'), 10);
                const row = dd._lastResults[idx];
                if (row && row.id) {
                    input.value = row.name || '';
                    hideCustomerSearchDropdown();
                    openCustomerProfile(row.id);
                }
            });
        }

        if (!window._customerHubDocClickBound) {
            window._customerHubDocClickBound = true;
            document.addEventListener('click', (e) => {
                const wrap = document.getElementById('customerHubSearchWrap');
                if (wrap && !wrap.contains(e.target)) hideCustomerSearchDropdown();
            });
        }
    }

    window.openCustomerProfile = function (customerId) {
        _customerHubMounted = false;
        if (typeof loadPage === 'function') loadPage('customers-' + customerId);
    };

    window.openCustomerFollowUp = function (customerId) {
        try {
            sessionStorage.setItem('customer_hub_focus_followup', String(customerId));
        } catch (_) {}
        openCustomerProfile(customerId);
    };

    async function ensureCustomerCache(force) {
        if (_customerCache && !force) return _customerCache;
        _customerCache = await API.customers.listEnriched({ branch_id: branchId() });
        return _customerCache || [];
    }

    function renderCustomerHubShell(copy, all) {
        const page = document.getElementById('customers');
        if (!page) return;
        page.innerHTML = `
            <div class="page-header" style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:1rem;gap:1rem;flex-wrap:wrap;">
                <div>
                    <h2 style="margin:0;">${esc(copy.title)}</h2>
                    <p class="text-muted" style="margin:0.35rem 0 0;max-width:42rem;">${esc(copy.subtitle)}</p>
                </div>
                <div style="display:flex;gap:0.5rem;flex-wrap:wrap;">
                    <button type="button" class="btn btn-primary" onclick="showCreateCustomerModal()"><i class="fas fa-plus"></i> ${esc(copy.newLabel)}</button>
                    <button type="button" class="btn btn-secondary" onclick="loadPage('customers-follow-ups')"><i class="fas fa-bell"></i> Follow-ups</button>
                    <button type="button" class="btn btn-secondary" onclick="loadPage('sales')"><i class="fas fa-file-invoice-dollar"></i> Sales</button>
                </div>
            </div>
            ${setupChecklistHtml(copy, all.length)}
            <div class="card" style="padding:1rem 1.25rem;margin-bottom:1rem;">
                <label style="font-weight:600;font-size:0.9rem;display:block;margin-bottom:0.35rem;">Find customer</label>
                <p class="text-muted" style="font-size:0.82rem;margin:0 0 0.65rem;">Type at least 2 characters — pick from the list to open profile, follow-ups, or WhatsApp.</p>
                <div id="customerHubSearchWrap" style="position:relative;max-width:520px;">
                    <input type="text" class="form-input" id="customerHubSearchInput" placeholder="Search name, phone, contact…" autocomplete="off" style="width:100%;padding:0.65rem 0.85rem;">
                    <div id="customerHubSearchDropdown" style="display:none;position:absolute;left:0;right:0;top:100%;margin-top:4px;background:#fff;border:1px solid var(--border-color);border-radius:8px;box-shadow:0 8px 24px rgba(0,0,0,0.12);z-index:60;max-height:280px;overflow-y:auto;"></div>
                </div>
            </div>
            <div class="card">
                <div style="padding:0.75rem 1rem;border-bottom:1px solid var(--border-color);font-weight:600;font-size:0.9rem;">All customers</div>
                <table class="data-table" style="width:100%;">
                    <thead><tr>
                        <th>Customer</th><th>Phone</th><th>Contact</th><th>Status</th>
                        <th class="text-right">Outstanding</th><th class="text-right">Overdue</th><th class="text-right">This month</th>
                    </tr></thead>
                    <tbody id="customerHubTableBody"></tbody>
                </table>
            </div>`;
        bindCustomerHubSearch();
        refreshCustomerTableBody();
        _customerHubMounted = true;
    }

    async function loadCustomersList() {
        const page = document.getElementById('customers');
        if (!page) return;
        const mode = hubMode();
        const copy = hubCopy(mode);

        if (!_customerHubMounted) {
            page.innerHTML =
                '<div class="card" style="padding:1.5rem;"><p><i class="fas fa-spinner fa-spin"></i> Loading customers…</p></div>';
        }

        try {
            const all = await ensureCustomerCache(!_customerHubMounted);
            if (!_customerHubMounted) {
                renderCustomerHubShell(copy, all);
            } else {
                refreshCustomerTableBody();
            }
        } catch (e) {
            _customerHubMounted = false;
            _customerCache = null;
            page.innerHTML = `<div class="card" style="padding:1.5rem;color:#b91c1c;">
                <strong>Could not load customers</strong>
                <p style="margin:0.5rem 0 0;">${esc(e.message || e)}</p>
                ${accessHintHtml(e)}
            </div>`;
        }
    }

    window.switchCustomerDetailTab = function (customerId, tab) {
        customerDetailTab[customerId] = tab;
        const prof = document.getElementById('customerDetailTabProfile');
        const stmt = document.getElementById('customerDetailTabStatement');
        if (prof) prof.style.display = tab === 'statement' ? 'none' : '';
        if (stmt) stmt.style.display = tab === 'statement' ? '' : 'none';
        document.querySelectorAll('.customer-detail-tab').forEach((btn) => {
            const active = btn.getAttribute('data-tab') === tab;
            btn.classList.toggle('btn-primary', active);
            btn.classList.toggle('btn-secondary', !active);
        });
        if (tab === 'statement' && stmt) {
            renderCustomerStatementTab(customerId, window._customerDetailName || '', stmt);
        }
    };

    async function renderCustomerStatementTab(customerId, customerName, container) {
        const today = new Date();
        const fromDate = customerStatementDateFrom[customerId] || localMonthStart(today);
        const toDate = customerStatementDateTo[customerId] || localDateString(today);
        container.innerHTML = '<p><i class="fas fa-spinner fa-spin"></i> Loading statement…</p>';
        try {
            const st = await API.customers.getStatement({
                customer_id: customerId,
                branch_id: branchId(),
                from_date: fromDate,
                to_date: toDate,
            });
            const integrity = st.statement_integrity || {};
            const status = (integrity.status || 'PASS').toUpperCase();
            const statusColor =
                status === 'PASS' ? 'var(--success-color)' : status === 'PASS_WITH_WARNINGS' ? 'var(--warning-color)' : 'var(--danger-color)';
            const warnHtml = (integrity.warnings || []).length
                ? '<ul style="margin:0.35rem 0 0;padding-left:1.2rem;font-size:0.85rem;">' +
                  integrity.warnings.map((w) => '<li>' + esc(w) + '</li>').join('') +
                  '</ul>'
                : '';
            container.innerHTML = `
                <div style="display:flex;flex-wrap:wrap;gap:0.75rem;margin-bottom:1rem;align-items:flex-end;">
                    <div class="form-group" style="margin:0;"><label class="form-label">From</label>
                    <input type="date" id="custStatementDateFrom" class="form-input" value="${esc(fromDate)}"></div>
                    <div class="form-group" style="margin:0;"><label class="form-label">To</label>
                    <input type="date" id="custStatementDateTo" class="form-input" value="${esc(toDate)}"></div>
                    <button type="button" class="btn btn-primary" id="custStatementApply">Apply</button>
                    <button type="button" class="btn btn-secondary" id="custStatementPrint"><i class="fas fa-print"></i> Print</button>
                    <button type="button" class="btn btn-secondary" id="custStatementPdf"><i class="fas fa-file-pdf"></i> PDF</button>
                </div>
                <div id="customerStatementPrint" class="card" style="padding:1.25rem;background:#fff;">
                    <div style="display:flex;justify-content:space-between;flex-wrap:wrap;gap:0.75rem;margin-bottom:1rem;">
                        <div>
                            <h4 style="margin:0;">${esc(st.customer_name || customerName)}</h4>
                            <p class="text-muted" style="margin:0.25rem 0 0;font-size:0.85rem;">
                                ${esc(st.company_name || '')}${st.branch_name ? ' · ' + esc(st.branch_name) : ''}
                            </p>
                            <p style="margin:0.35rem 0 0;font-size:0.85rem;">Period: ${esc(st.from_date)} to ${esc(st.to_date)}</p>
                            <p style="margin:0.25rem 0 0;font-size:0.85rem;">Opening: ${fmtMoney(st.opening_balance)} · Closing: ${fmtMoney(st.closing_balance)}</p>
                        </div>
                        <div style="text-align:right;font-size:0.8rem;">
                            <div><strong>Integrity:</strong> <span style="color:${statusColor}">${esc(status)}</span></div>
                            <div>Doctrine: ${esc(st.doctrine || 'operational_ar_v1')}</div>
                            ${st.prepared_by ? '<div>Prepared by: ' + esc(st.prepared_by) + '</div>' : ''}
                        </div>
                    </div>
                    ${status === 'FAIL' ? '<p style="color:var(--danger-color);font-weight:600;margin:0 0 0.75rem;">DRAFT — NOT FOR EXTERNAL USE until reconciliation passes.</p>' : ''}
                    <table class="data-table" style="width:100%;font-size:0.875rem;">
                        <thead><tr><th>Date</th><th>Description</th><th>Reference</th><th class="text-right">Debit</th><th class="text-right">Credit</th><th class="text-right">Balance</th></tr></thead>
                        <tbody>${(st.lines || [])
                            .map(
                                (l) => `<tr>
                            <td>${esc(l.date)}</td>
                            <td>${esc(l.description || l.entry_type)}</td>
                            <td>${esc(l.reference || '—')}</td>
                            <td class="text-right">${fmtMoney(l.debit)}</td>
                            <td class="text-right">${fmtMoney(l.credit)}</td>
                            <td class="text-right">${fmtMoney(l.balance)}</td>
                        </tr>`
                            )
                            .join('')}</tbody>
                    </table>
                    <div style="margin-top:1rem;font-size:0.85rem;">
                        <div>Ledger closing: ${fmtMoney(integrity.ledger_closing_balance != null ? integrity.ledger_closing_balance : st.closing_balance)}</div>
                        <div>Invoice open total: ${fmtMoney(integrity.invoice_open_balance_sum)} · Delta: ${fmtMoney(integrity.delta)}</div>
                        ${warnHtml}
                    </div>
                </div>`;
            document.getElementById('custStatementApply').addEventListener('click', () => {
                customerStatementDateFrom[customerId] = document.getElementById('custStatementDateFrom').value;
                customerStatementDateTo[customerId] = document.getElementById('custStatementDateTo').value;
                renderCustomerStatementTab(customerId, customerName, container);
            });
            document.getElementById('custStatementPrint').addEventListener('click', () => {
                const el = document.getElementById('customerStatementPrint');
                if (!el) return;
                const w = window.open('', '_blank');
                if (!w) return;
                w.document.write('<html><head><title>Customer statement</title></head><body>' + el.innerHTML + '</body></html>');
                w.document.close();
                w.print();
            });
            document.getElementById('custStatementPdf').addEventListener('click', async () => {
                const btn = document.getElementById('custStatementPdf');
                if (btn) btn.disabled = true;
                try {
                    const r = await API.customers.downloadStatementPdf({
                        customer_id: customerId,
                        branch_id: branchId(),
                        from_date: document.getElementById('custStatementDateFrom').value,
                        to_date: document.getElementById('custStatementDateTo').value,
                        customer_name: customerName,
                        block_on_fail: false,
                    });
                    if (r && r.integrity === 'FAIL' && typeof showToast === 'function') {
                        showToast('PDF saved with DRAFT watermark (integrity FAIL)', 'warning');
                    }
                } catch (err) {
                    if (typeof showToast === 'function') showToast(err.message || 'PDF failed', 'error');
                } finally {
                    if (btn) btn.disabled = false;
                }
            });
        } catch (e) {
            container.innerHTML = '<p style="color:var(--danger-color);">Failed to load statement: ' + esc(e.message || e) + '</p>';
        }
    };

    async function loadCustomerDetail(customerId) {
        const page = document.getElementById('customers');
        if (!page) return;
        const mode = hubMode();
        const copy = hubCopy(mode);
        page.innerHTML = '<div class="card" style="padding:1.5rem;">Loading…</div>';
        try {
            const [c, analytics] = await Promise.all([
                API.customers.get(customerId),
                API.customers.analytics(customerId, { branch_id: branchId() }),
            ]);
            const creditLine =
                c.credit_limit != null
                    ? fmtMoney(c.credit_limit)
                    : 'No limit set';
            const terms =
                c.default_payment_terms_days != null
                    ? esc(String(c.default_payment_terms_days)) + ' days'
                    : 'Not set';
            const wa = whatsAppUrl(c.phone);

            page.innerHTML = `
                <div class="page-header" style="margin-bottom:1rem;">
                    <button type="button" class="btn btn-secondary btn-sm" onclick="loadPage('customers')"><i class="fas fa-arrow-left"></i> All customers</button>
                    <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-top:0.75rem;gap:1rem;flex-wrap:wrap;">
                        <div>
                            <h2 style="margin:0;">${esc(c.name)}</h2>
                            <p class="text-muted" style="margin:0.25rem 0 0;">${esc(c.customer_type)} · ${esc(c.phone || 'No phone')}</p>
                        </div>
                        <div style="display:flex;gap:0.5rem;flex-wrap:wrap;">
                            <button type="button" class="btn btn-primary" onclick="startSaleForCustomer('${esc(customerId)}','${esc(c.name).replace(/'/g, "\\'")}')"><i class="fas fa-cart-plus"></i> ${esc(copy.saleBtn)}</button>
                            <button type="button" class="btn btn-secondary" onclick="document.getElementById('customerFollowUpSection')&&document.getElementById('customerFollowUpSection').scrollIntoView({behavior:'smooth'})"><i class="fas fa-bell"></i> Follow-up</button>
                            ${wa ? `<a class="btn btn-outline" href="${esc(wa)}" target="_blank" rel="noopener"><i class="fab fa-whatsapp"></i> WhatsApp</a>` : ''}
                        </div>
                    </div>
                </div>
                <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:0.75rem;margin-bottom:1rem;">
                    <div class="card" style="padding:0.75rem;"><div class="text-muted" style="font-size:0.8rem;">30d sales</div><strong>${fmtMoney(analytics.sales_30d)}</strong></div>
                    <div class="card" style="padding:0.75rem;"><div class="text-muted" style="font-size:0.8rem;">Outstanding</div><strong>${fmtMoney(analytics.outstanding_balance)}</strong></div>
                    <div class="card" style="padding:0.75rem;"><div class="text-muted" style="font-size:0.8rem;">Overdue</div><strong>${fmtMoney(analytics.overdue_amount)}</strong></div>
                    <div class="card" style="padding:0.75rem;"><div class="text-muted" style="font-size:0.8rem;">Credit limit</div><strong>${creditLine}</strong></div>
                    <div class="card" style="padding:0.75rem;"><div class="text-muted" style="font-size:0.8rem;">Payment terms</div><strong>${terms}</strong></div>
                </div>
                <div style="display:flex;gap:0.5rem;margin-bottom:0.75rem;border-bottom:1px solid var(--border-color);">
                    <button type="button" class="btn btn-secondary btn-sm customer-detail-tab" data-tab="profile" onclick="switchCustomerDetailTab('${customerId}','profile')">Profile</button>
                    <button type="button" class="btn btn-secondary btn-sm customer-detail-tab" data-tab="statement" onclick="switchCustomerDetailTab('${customerId}','statement')">Statement</button>
                </div>
                <div id="customerDetailTabProfile">
                <div class="card" style="padding:1rem;margin-bottom:1rem;">
                    <div style="display:flex;justify-content:space-between;align-items:center;gap:0.75rem;flex-wrap:wrap;margin-bottom:0.75rem;">
                        <h3 style="margin:0;">Previous invoices &amp; refills</h3>
                        <button type="button" class="btn btn-secondary btn-sm" onclick="loadCustomerInvoices('${customerId}')">
                            <i class="fas fa-sync"></i> Refresh
                        </button>
                    </div>
                    <div id="customerInvoicesList">Loading invoices...</div>
                </div>
                <div class="card" style="padding:1rem;margin-bottom:1rem;">
                    <h3 style="margin:0 0 0.75rem;">${esc(copy.profileHeading)}</h3>
                    <form id="customerProfileForm" onsubmit="return saveCustomerProfile(event, '${customerId}')">
                        <div style="display:grid;grid-template-columns:1fr 1fr;gap:0.75rem;">
                            <label>Customer name *<input class="form-input" name="name" value="${esc(c.name)}" required></label>
                            <label>PIN / tax ID<input class="form-input" name="pin" value="${esc(c.pin || '')}"></label>
                            <label>Phone<input class="form-input" name="phone" value="${esc(c.phone || '')}"></label>
                            <label>Email<input class="form-input" name="email" value="${esc(c.email || '')}"></label>
                            <label>Contact person<input class="form-input" name="contact_person" value="${esc(c.contact_person || '')}"></label>
                            <label>Account type<select class="form-input" name="customer_type">
                                ${copy.customerTypes.map(([v, l]) =>
                                    `<option value="${v}" ${c.customer_type === v ? 'selected' : ''}>${l}</option>`).join('')}
                            </select></label>
                            <label>City<input class="form-input" name="city" value="${esc(c.city || '')}"></label>
                            <label>County<input class="form-input" name="county" value="${esc(c.county || '')}"></label>
                            <label style="grid-column:1/-1">Delivery / billing address<textarea class="form-input" name="address" rows="2">${esc(c.address || '')}</textarea></label>
                            <label>Credit limit<input class="form-input" type="number" step="0.01" name="credit_limit" value="${c.credit_limit != null ? c.credit_limit : ''}" placeholder="Leave empty for no cap"></label>
                            <label>Payment terms (days)<input class="form-input" type="number" name="default_payment_terms_days" value="${c.default_payment_terms_days != null ? c.default_payment_terms_days : ''}"></label>
                            <label style="grid-column:1/-1">Internal notes<textarea class="form-input" name="notes" rows="2">${esc(c.notes || '')}</textarea></label>
                            <label><input type="checkbox" name="credit_enabled" ${c.credit_enabled !== false ? 'checked' : ''}> Credit sales enabled</label>
                            <label><input type="checkbox" name="allow_over_credit" ${c.allow_over_credit ? 'checked' : ''}> Allow sales above credit limit</label>
                        </div>
                        <button type="submit" class="btn btn-primary" style="margin-top:0.75rem;">Save profile</button>
                    </form>
                </div>
                <div class="card" style="padding:1rem;" id="customerFollowUpSection">
                    <h3 style="margin:0 0 0.5rem;">Follow-ups &amp; visits</h3>
                    <form onsubmit="return addCustomerActivity(event, '${customerId}')">
                        <div style="display:flex;gap:0.5rem;flex-wrap:wrap;">
                            <input class="form-input" name="subject" placeholder="Subject" required style="flex:2;min-width:160px;">
                            <select class="form-input" name="activity_type" style="flex:1;">
                                <option value="call">Call</option><option value="visit">Visit</option>
                                <option value="email">Email</option><option value="follow_up">Follow-up</option>
                            </select>
                            <input class="form-input" type="date" name="due_date" style="flex:1;">
                            <button class="btn btn-secondary" type="submit">Add</button>
                        </div>
                    </form>
                    <div id="customerActivitiesList" style="margin-top:0.75rem;">Loading activities…</div>
                </div>
                </div>
                <div id="customerDetailTabStatement" style="display:none;"></div>`;
            window._customerDetailName = c.name;
            loadCustomerActivities(customerId);
            loadCustomerInvoices(customerId);
            switchCustomerDetailTab(customerId, customerDetailTab[customerId] || 'profile');
            try {
                const focusId = sessionStorage.getItem('customer_hub_focus_followup');
                if (focusId && String(focusId) === String(customerId)) {
                    sessionStorage.removeItem('customer_hub_focus_followup');
                    setTimeout(() => {
                        const el = document.getElementById('customerFollowUpSection');
                        if (el) el.scrollIntoView({ behavior: 'smooth' });
                    }, 120);
                }
            } catch (_) {}
        } catch (e) {
            page.innerHTML = `<div class="card" style="padding:1.5rem;">Error: ${esc(e.message || e)}${accessHintHtml(e)}</div>`;
        }
    }

    window.startSaleForCustomer = function (customerId, customerName) {
        try {
            sessionStorage.setItem(
                'pharmasight_sale_customer_prefill',
                JSON.stringify({ customer_id: customerId, customer_name: customerName })
            );
        } catch (_) {}
        if (typeof loadPage === 'function') {
            loadPage('sales');
        }
    };

    async function loadCustomerActivities(customerId) {
        const el = document.getElementById('customerActivitiesList');
        if (!el) return;
        try {
            const acts = await API.customers.listActivities({ customer_id: customerId });
            el.innerHTML = (acts || []).length
                ? `<ul style="margin:0;padding-left:1.2rem;">${acts
                      .map(
                          (a) =>
                              `<li>${esc(a.subject)} — ${esc(a.status)} ${a.due_date ? '(due ' + esc(a.due_date) + ')' : ''}</li>`
                      )
                      .join('')}</ul>`
                : '<p class="text-muted">No activities yet.</p>';
        } catch (_) {
            el.innerHTML = '<p class="text-muted">Could not load activities.</p>';
        }
    }

    async function loadCustomerInvoices(customerId) {
        const el = document.getElementById('customerInvoicesList');
        if (!el) return;
        if (!window.API || !API.customers || typeof API.customers.listInvoices !== 'function') {
            el.innerHTML = '<p class="text-muted">Invoice history is not available.</p>';
            return;
        }
        try {
            const invoices = await API.customers.listInvoices(customerId, { branch_id: branchId(), limit: 12 });
            if (!invoices || !invoices.length) {
                el.innerHTML = '<p class="text-muted">No previous invoices for this customer yet.</p>';
                return;
            }
            el.innerHTML = `
                <table class="data-table" style="width:100%;font-size:0.86rem;">
                    <thead><tr><th>Date</th><th>Invoice</th><th>Items</th><th class="text-right">Total</th><th></th></tr></thead>
                    <tbody>${invoices.map(function (inv) {
                        const itemNames = (inv.items || []).map(function (i) {
                            const qty = Number(i.quantity || 0);
                            return esc((i.item_name || 'Item') + (qty ? ' x' + qty : ''));
                        }).join(', ');
                        return `<tr>
                            <td>${esc(inv.invoice_date || '')}</td>
                            <td>${esc(inv.invoice_no || '')}</td>
                            <td title="${esc(itemNames)}">${esc(itemNames || (inv.item_count || 0) + ' item(s)')}</td>
                            <td class="text-right">${fmtMoney(inv.total_inclusive)}</td>
                            <td class="text-right">
                                <button type="button" class="btn btn-primary btn-sm" onclick="cloneCustomerInvoiceToDraft('${esc(inv.id)}')">
                                    <i class="fas fa-copy"></i> Refill
                                </button>
                            </td>
                        </tr>`;
                    }).join('')}</tbody>
                </table>`;
        } catch (err) {
            el.innerHTML = '<p style="color:var(--danger-color);">Failed to load invoices: ' + esc(err.message || err) + '</p>';
        }
    }
    window.loadCustomerInvoices = loadCustomerInvoices;

    window.cloneCustomerInvoiceToDraft = async function (invoiceId) {
        if (!invoiceId || !window.API || !API.sales || typeof API.sales.cloneInvoiceToDraft !== 'function') return;
        try {
            if (typeof showToast === 'function') showToast('Creating refill draft...', 'info');
            const draft = await API.sales.cloneInvoiceToDraft(invoiceId, { branch_id: branchId() });
            if (draft && draft.document_type === 'quotation') {
                const msg = draft.message || 'Refill needs review, so a draft quotation was created.';
                if (typeof showToast === 'function') showToast(msg, 'warning');
                const openQuotation = function () {
                    if (window.viewQuotation && draft.quotation_id) {
                        window.viewQuotation(draft.quotation_id);
                    } else if (window.switchSalesSubPage) {
                        window.switchSalesSubPage('quotations');
                    }
                };
                if (typeof loadPage === 'function') {
                    loadPage('sales');
                    setTimeout(openQuotation, 250);
                } else {
                    openQuotation();
                }
                return;
            }
            if (window.openSalesInvoiceDraftFromData) {
                window.openSalesInvoiceDraftFromData(draft, 'Refill draft created. Review stock and batch when ready.');
            } else if (typeof loadPage === 'function') {
                try {
                    sessionStorage.setItem('pendingSalesDraftId', String(draft.id));
                } catch (_) {}
                loadPage('sales-create-invoice');
            }
        } catch (err) {
            if (typeof showToast === 'function') showToast(err.message || 'Could not create refill draft', 'error');
        }
    };

    window.showCreateCustomerModal = function () {
        const cid = companyId();
        if (!cid) return alert('Company not loaded');
        const copy = hubCopy(hubMode());
        const typeOpts = copy.customerTypes
            .map(([v, l]) => `<option value="${v}">${l}</option>`)
            .join('');
        const html = `
            <form id="createCustomerForm">
                <p class="text-muted" style="font-size:0.85rem;margin:0 0 0.75rem;">${esc(copy.subtitle)}</p>
                <label>Customer name *<input class="form-input" name="name" required autofocus></label>
                <label style="display:block;margin-top:0.5rem;">Phone<input class="form-input" name="phone"></label>
                <label style="display:block;margin-top:0.5rem;">PIN<input class="form-input" name="pin"></label>
                <label style="display:block;margin-top:0.5rem;">Type<select class="form-input" name="customer_type">${typeOpts}</select></label>
                <label style="display:block;margin-top:0.5rem;">Credit limit (optional)<input class="form-input" type="number" step="0.01" name="credit_limit"></label>
                <label style="display:block;margin-top:0.5rem;">Payment terms (days)<input class="form-input" type="number" name="default_payment_terms_days" placeholder="e.g. 30"></label>
            </form>`;
        const footer = `
            <button type="button" class="btn btn-secondary" onclick="closeModal()">Cancel</button>
            <button type="button" class="btn btn-primary" id="createCustomerSubmitBtn"><i class="fas fa-check"></i> Create</button>`;
        if (typeof showModal === 'function') {
            showModal(copy.newLabel, html, footer);
            const submitBtn = document.getElementById('createCustomerSubmitBtn');
            if (submitBtn) {
                submitBtn.onclick = async () => {
                    const form = document.getElementById('createCustomerForm');
                    if (!form || !form.reportValidity()) return;
                    const fd = new FormData(form);
                    const name = (fd.get('name') || '').toString().trim();
                    if (!name) {
                        if (typeof showToast === 'function') showToast('Customer name is required', 'error');
                        return;
                    }
                    submitBtn.disabled = true;
                    try {
                        const payload = {
                            company_id: cid,
                            name,
                            phone: fd.get('phone') || null,
                            pin: fd.get('pin') || null,
                            customer_type: fd.get('customer_type') || 'PHARMACY',
                            credit_limit: fd.get('credit_limit') ? Number(fd.get('credit_limit')) : null,
                            default_payment_terms_days: fd.get('default_payment_terms_days')
                                ? parseInt(fd.get('default_payment_terms_days'), 10)
                                : null,
                            credit_enabled: true,
                        };
                        const created = await API.customers.create(payload);
                        _customerCache = null;
                        if (typeof closeModal === 'function') closeModal();
                        if (typeof showToast === 'function') showToast('Customer created', 'success');
                        if (created && created.id) {
                            loadPage('customers-' + created.id);
                        } else {
                            loadCustomersList();
                        }
                    } catch (err) {
                        if (typeof showToast === 'function') {
                            showToast(err.message || 'Could not create customer', 'error');
                        }
                    } finally {
                        submitBtn.disabled = false;
                    }
                };
            }
        } else {
            const name = prompt('Customer name');
            if (!name) return;
            API.customers.create({ company_id: cid, name, customer_type: 'PHARMACY' }).then(() => loadCustomersList());
        }
    };

    window.saveCustomerProfile = async function (ev, customerId) {
        ev.preventDefault();
        const fd = new FormData(ev.target);
        const data = {
            name: fd.get('name'),
            pin: fd.get('pin') || null,
            phone: fd.get('phone') || null,
            email: fd.get('email') || null,
            contact_person: fd.get('contact_person') || null,
            address: fd.get('address') || null,
            city: fd.get('city') || null,
            county: fd.get('county') || null,
            customer_type: fd.get('customer_type'),
            notes: fd.get('notes') || null,
            credit_limit: fd.get('credit_limit') ? Number(fd.get('credit_limit')) : null,
            default_payment_terms_days: fd.get('default_payment_terms_days')
                ? parseInt(fd.get('default_payment_terms_days'), 10)
                : null,
            credit_enabled: !!fd.get('credit_enabled'),
            allow_over_credit: !!fd.get('allow_over_credit'),
        };
        await API.customers.update(customerId, data);
        if (typeof showToast === 'function') showToast('Customer saved', 'success');
        loadCustomerDetail(customerId);
        return false;
    };

    window.addCustomerActivity = async function (ev, customerId) {
        ev.preventDefault();
        const fd = new FormData(ev.target);
        await API.customers.createActivity({
            customer_id: customerId,
            activity_type: fd.get('activity_type') || 'follow_up',
            subject: fd.get('subject'),
            due_date: fd.get('due_date') || null,
        });
        ev.target.reset();
        loadCustomerActivities(customerId);
        return false;
    };

    window.loadCustomers = function () {
        _customerHubMounted = false;
        _customerCache = null;
        loadCustomersList();
    };

    window.loadCustomerSubPage = function (sub) {
        if (!sub) return loadCustomersList();
        if (sub === 'dashboard') {
            loadCustomerDashboard();
            return;
        }
        if (sub === 'follow-ups') {
            loadCustomerFollowUps();
            return;
        }
        loadCustomerDetail(sub);
    };

    async function loadCustomerDashboard() {
        const page = document.getElementById('customers');
        if (!page) return;
        const copy = hubCopy(hubMode());
        try {
            const list = await API.customers.listEnriched({ branch_id: branchId() });
            const rows = list || [];
            const totalOut = rows.reduce((s, r) => s + Number(r.outstanding_balance || 0), 0);
            const totalOver = rows.reduce((s, r) => s + Number(r.overdue_amount || 0), 0);
            const withBal = rows.filter((r) => Number(r.outstanding_balance) > 0).length;
            page.innerHTML = `
                <div class="page-header" style="margin-bottom:1rem;">
                    <h2 style="margin:0;">AR overview</h2>
                    <p class="text-muted">${esc(copy.title)} — ${esc(copy.subtitle)}</p>
                </div>
                <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:0.75rem;margin-bottom:1rem;">
                    <div class="card" style="padding:1rem;"><div class="text-muted">Accounts</div><strong>${rows.length}</strong></div>
                    <div class="card" style="padding:1rem;"><div class="text-muted">With balance</div><strong>${withBal}</strong></div>
                    <div class="card" style="padding:1rem;"><div class="text-muted">Total outstanding</div><strong>${fmtMoney(totalOut)}</strong></div>
                    <div class="card" style="padding:1rem;"><div class="text-muted">Total overdue</div><strong>${fmtMoney(totalOver)}</strong></div>
                </div>
                <button class="btn btn-secondary" onclick="loadPage('customers')">All customers</button>`;
        } catch (e) {
            page.innerHTML = `<div class="card" style="padding:1rem;">Error: ${esc(e.message)}${accessHintHtml(e)}</div>`;
        }
    }

    async function loadCustomerFollowUps() {
        const page = document.getElementById('customers');
        if (!page) return;
        try {
            const acts = await API.customers.listFollowUps();
            page.innerHTML = `
                <div class="page-header"><h2>Follow-ups due</h2>
                <button class="btn btn-secondary btn-sm" onclick="loadPage('customers')">Back</button></div>
                <div class="card" style="padding:1rem;">
                    <ul>${(acts || [])
                        .map(
                            (a) =>
                                `<li><a href="#" onclick="loadPage('customers-${a.customer_id}');return false;">${esc(a.customer_name || 'Customer')}</a> — ${esc(a.subject)} (${esc(a.due_date || '')})</li>`
                        )
                        .join('') || '<li>None due</li>'}</ul>
                </div>`;
        } catch (e) {
            page.innerHTML = `<div class="card">Error: ${esc(e.message)}</div>`;
        }
    }
})();
