/**
 * Wholesale / B2B customer management (mirror supplier hub in purchases.js)
 */
(function () {
    'use strict';

    function esc(s) {
        if (s == null) return '';
        return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    function fmtMoney(n) {
        const x = Number(n || 0);
        return x.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }

    function companyId() {
        return window.CONFIG && CONFIG.COMPANY_ID;
    }

    function branchId() {
        return window.CONFIG && CONFIG.BRANCH_ID;
    }

    async function loadCustomersList() {
        const page = document.getElementById('customers');
        if (!page) return;
        page.innerHTML = '<div class="card" style="padding:1.5rem;"><p>Loading customers…</p></div>';
        try {
            const list = await API.customers.listEnriched({ branch_id: branchId() });
            const rows = (list || []).map((c) => `
                <tr style="cursor:pointer" onclick="loadPage('customers-${c.id}')">
                    <td><strong>${esc(c.name)}</strong><br><small class="text-muted">${esc(c.customer_type || '')}</small></td>
                    <td>${esc(c.phone || '—')}</td>
                    <td>${esc(c.contact_person || '—')}</td>
                    <td class="text-right">${fmtMoney(c.outstanding_balance)}</td>
                    <td class="text-right" style="color:${c.overdue_amount > 0 ? '#b91c1c' : 'inherit'}">${fmtMoney(c.overdue_amount)}</td>
                    <td class="text-right">${fmtMoney(c.this_month_sales)}</td>
                </tr>`).join('');
            page.innerHTML = `
                <div class="page-header" style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem;">
                    <div>
                        <h2 style="margin:0;">Wholesale Customers</h2>
                        <p class="text-muted" style="margin:0.25rem 0 0;">B2B buyers — pharmacies, hospitals, institutions</p>
                    </div>
                    <button type="button" class="btn btn-primary" onclick="showCreateCustomerModal()"><i class="fas fa-plus"></i> New Customer</button>
                </div>
                <div class="card">
                    <table class="data-table" style="width:100%;">
                        <thead><tr>
                            <th>Customer</th><th>Phone</th><th>Contact</th>
                            <th class="text-right">Outstanding</th><th class="text-right">Overdue</th><th class="text-right">This month</th>
                        </tr></thead>
                        <tbody>${rows || '<tr><td colspan="6">No customers yet.</td></tr>'}</tbody>
                    </table>
                </div>`;
        } catch (e) {
            page.innerHTML = `<div class="card" style="padding:1.5rem;color:#b91c1c;">Failed to load customers: ${esc(e.message || e)}</div>`;
        }
    }

    async function loadCustomerDetail(customerId) {
        const page = document.getElementById('customers');
        if (!page) return;
        page.innerHTML = '<div class="card" style="padding:1.5rem;">Loading…</div>';
        try {
            const [c, analytics] = await Promise.all([
                API.customers.get(customerId),
                API.customers.analytics(customerId, { branch_id: branchId() }),
            ]);
            page.innerHTML = `
                <div class="page-header" style="margin-bottom:1rem;">
                    <button type="button" class="btn btn-secondary btn-sm" onclick="loadPage('customers')"><i class="fas fa-arrow-left"></i> Back</button>
                    <h2 style="margin:0.5rem 0 0;">${esc(c.name)}</h2>
                    <p class="text-muted">${esc(c.customer_type)} · ${esc(c.phone || '')}</p>
                </div>
                <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:0.75rem;margin-bottom:1rem;">
                    <div class="card" style="padding:0.75rem;"><div class="text-muted">30d sales</div><strong>KES ${fmtMoney(analytics.sales_30d)}</strong></div>
                    <div class="card" style="padding:0.75rem;"><div class="text-muted">Outstanding</div><strong>KES ${fmtMoney(analytics.outstanding_balance)}</strong></div>
                    <div class="card" style="padding:0.75rem;"><div class="text-muted">Overdue</div><strong>KES ${fmtMoney(analytics.overdue_amount)}</strong></div>
                    <div class="card" style="padding:0.75rem;"><div class="text-muted">Open follow-ups</div><strong>${analytics.open_follow_ups || 0}</strong></div>
                </div>
                <div class="card" style="padding:1rem;">
                    <h3>Profile</h3>
                    <form id="customerProfileForm" onsubmit="return saveCustomerProfile(event, '${customerId}')">
                        <div style="display:grid;grid-template-columns:1fr 1fr;gap:0.75rem;">
                            <label>Name<input class="form-input" name="name" value="${esc(c.name)}" required></label>
                            <label>PIN<input class="form-input" name="pin" value="${esc(c.pin || '')}"></label>
                            <label>Phone<input class="form-input" name="phone" value="${esc(c.phone || '')}"></label>
                            <label>Email<input class="form-input" name="email" value="${esc(c.email || '')}"></label>
                            <label>Contact person<input class="form-input" name="contact_person" value="${esc(c.contact_person || '')}"></label>
                            <label>Type<select class="form-input" name="customer_type">
                                ${['PHARMACY','HOSPITAL','CLINIC','INSTITUTION','OTHER'].map((t) =>
                                    `<option value="${t}" ${c.customer_type === t ? 'selected' : ''}>${t}</option>`).join('')}
                            </select></label>
                            <label style="grid-column:1/-1">Address<textarea class="form-input" name="address" rows="2">${esc(c.address || '')}</textarea></label>
                            <label>Credit limit<input class="form-input" type="number" step="0.01" name="credit_limit" value="${c.credit_limit != null ? c.credit_limit : ''}"></label>
                            <label>Payment terms (days)<input class="form-input" type="number" name="default_payment_terms_days" value="${c.default_payment_terms_days != null ? c.default_payment_terms_days : ''}"></label>
                            <label><input type="checkbox" name="credit_enabled" ${c.credit_enabled !== false ? 'checked' : ''}> Credit enabled</label>
                            <label><input type="checkbox" name="allow_over_credit" ${c.allow_over_credit ? 'checked' : ''}> Allow over credit limit</label>
                        </div>
                        <button type="submit" class="btn btn-primary" style="margin-top:0.75rem;">Save profile</button>
                    </form>
                </div>
                <div class="card" style="padding:1rem;margin-top:1rem;">
                    <h3>Follow-up</h3>
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
                </div>`;
            loadCustomerActivities(customerId);
        } catch (e) {
            page.innerHTML = `<div class="card" style="padding:1.5rem;">Error: ${esc(e.message || e)}</div>`;
        }
    }

    async function loadCustomerActivities(customerId) {
        const el = document.getElementById('customerActivitiesList');
        if (!el) return;
        try {
            const acts = await API.customers.listActivities({ customer_id: customerId });
            el.innerHTML = (acts || []).length
                ? `<ul style="margin:0;padding-left:1.2rem;">${acts.map((a) =>
                    `<li>${esc(a.subject)} — ${esc(a.status)} ${a.due_date ? '(due ' + esc(a.due_date) + ')' : ''}</li>`).join('')}</ul>`
                : '<p class="text-muted">No activities yet.</p>';
        } catch (_) {
            el.innerHTML = '<p class="text-muted">Could not load activities.</p>';
        }
    }

    window.showCreateCustomerModal = function () {
        const cid = companyId();
        if (!cid) return alert('Company not loaded');
        const html = `
            <form id="createCustomerForm">
                <label>Name *<input class="form-input" name="name" required></label>
                <label style="display:block;margin-top:0.5rem;">Phone<input class="form-input" name="phone"></label>
                <label style="display:block;margin-top:0.5rem;">PIN<input class="form-input" name="pin"></label>
                <label style="display:block;margin-top:0.5rem;">Type<select class="form-input" name="customer_type">
                    <option value="PHARMACY">Pharmacy</option><option value="HOSPITAL">Hospital</option>
                    <option value="CLINIC">Clinic</option><option value="INSTITUTION">Institution</option>
                </select></label>
            </form>`;
        if (typeof showModal === 'function') {
            showModal('New wholesale customer', html, async () => {
                const form = document.getElementById('createCustomerForm');
                const fd = new FormData(form);
                await API.customers.create({
                    company_id: cid,
                    name: fd.get('name'),
                    phone: fd.get('phone') || null,
                    pin: fd.get('pin') || null,
                    customer_type: fd.get('customer_type') || 'PHARMACY',
                });
                loadCustomersList();
            });
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
            customer_type: fd.get('customer_type'),
            credit_limit: fd.get('credit_limit') ? Number(fd.get('credit_limit')) : null,
            default_payment_terms_days: fd.get('default_payment_terms_days')
                ? parseInt(fd.get('default_payment_terms_days'), 10) : null,
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
        loadCustomersList();
    };

    window.loadCustomerSubPage = function (sub) {
        if (!sub) return loadCustomersList();
        if (sub === 'dashboard') {
            const page = document.getElementById('customers');
            if (page) {
                page.innerHTML = '<div class="card" style="padding:1.5rem;"><h3>AR Dashboard</h3><p>Use Customers list for balances. Full dashboard charts can be extended here.</p><button class="btn btn-secondary" onclick="loadPage(\'customers\')">Customers list</button></div>';
            }
            return;
        }
        if (sub === 'follow-ups') {
            loadCustomerFollowUps();
            return;
        }
        loadCustomerDetail(sub);
    };

    async function loadCustomerFollowUps() {
        const page = document.getElementById('customers');
        if (!page) return;
        try {
            const acts = await API.customers.listFollowUps();
            page.innerHTML = `
                <div class="page-header"><h2>Follow-ups due</h2>
                <button class="btn btn-secondary btn-sm" onclick="loadPage('customers')">Back</button></div>
                <div class="card" style="padding:1rem;">
                    <ul>${(acts || []).map((a) =>
                        `<li><a href="#" onclick="loadPage('customers-${a.customer_id}');return false;">${esc(a.customer_name || 'Customer')}</a> — ${esc(a.subject)} (${esc(a.due_date || '')})</li>`).join('') || '<li>None due</li>'}</ul>
                </div>`;
        } catch (e) {
            page.innerHTML = `<div class="card">Error: ${esc(e.message)}</div>`;
        }
    }
})();
