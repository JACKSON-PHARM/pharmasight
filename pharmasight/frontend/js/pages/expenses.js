// Expenses Page (OPEX only): list, create, approve; categories management.

let currentExpensesSubPage = 'expenses'; // 'expenses' | 'categories' | 'reports'

function _fmtMoney(v) {
    const n = parseFloat(v || 0);
    return (typeof formatCurrency === 'function') ? formatCurrency(n) : ('KES ' + n.toLocaleString('en-KE', { minimumFractionDigits: 2 }));
}

function _localDateStr(d) {
    const x = d ? new Date(d) : new Date();
    const yyyy = x.getFullYear();
    const mm = String(x.getMonth() + 1).padStart(2, '0');
    const dd = String(x.getDate()).padStart(2, '0');
    return `${yyyy}-${mm}-${dd}`;
}

/** Map router subPage / hash aliases to internal sub-page keys. */
function _normalizeExpensesSubPage(subPage) {
    if (subPage == null || subPage === '') return 'expenses';
    const s = String(subPage).toLowerCase();
    if (s === 'expenses' || s === 'list' || s === 'all') return 'expenses';
    if (s === 'categories' || s === 'category' || s === 'expenses-categories') return 'categories';
    if (s === 'reports' || s === 'expenses-reports' || s === 'insights' || s === 'analytics') return 'reports';
    return s;
}

async function loadExpenses(subPage = null) {
    const target = _normalizeExpensesSubPage(subPage);
    await loadExpensesSubPage(target);
}

async function loadExpensesSubPage(subPage) {
    currentExpensesSubPage = _normalizeExpensesSubPage(subPage);
    const page = document.getElementById('expenses');
    if (!page) return;

    const titleMap = {
        'expenses': 'All Expenses',
        'categories': 'Expense Categories',
        'reports': 'Expense Insights',
    };
    const title = titleMap[currentExpensesSubPage] || 'Expenses';

    page.innerHTML = `
        <div class="card">
            <div class="card-header">
                <h3 class="card-title"><i class="fas fa-money-bill-wave"></i> ${title}</h3>
            </div>
            <div class="card-body" id="expensesBody">
                <div class="spinner" style="margin: 1rem auto;"></div>
            </div>
        </div>
    `;

    if (currentExpensesSubPage === 'categories') {
        await renderExpenseCategories();
        return;
    }
    if (currentExpensesSubPage === 'reports') {
        await renderExpenseInsights();
        return;
    }

    await renderExpensesList();
}

async function renderExpensesList() {
    const body = document.getElementById('expensesBody');
    if (!body) return;
    const today = new Date();
    const start = _localDateStr(new Date(today.getFullYear(), today.getMonth(), 1));
    const end = _localDateStr(today);

    body.innerHTML = `
        <div style="display:flex; flex-wrap:wrap; gap:0.75rem; align-items:end; margin-bottom: 1rem;">
            <div class="form-group" style="margin:0;">
                <label class="form-label">From</label>
                <input type="date" class="form-input" id="expDateFrom" value="${start}">
            </div>
            <div class="form-group" style="margin:0;">
                <label class="form-label">To</label>
                <input type="date" class="form-input" id="expDateTo" value="${end}">
            </div>
            <div class="form-group" style="min-width: 180px; margin:0;">
                <label class="form-label">Status</label>
                <select class="form-select" id="expStatus">
                    <option value="">All</option>
                    <option value="approved">Approved</option>
                    <option value="pending">Pending</option>
                </select>
            </div>
            <div style="margin:0;">
                <button class="btn btn-primary" id="expApplyBtn"><i class="fas fa-filter"></i> Apply</button>
            </div>
            <div style="margin-left:auto;">
                <button class="btn btn-primary" id="expNewBtn"><i class="fas fa-plus"></i> New Expense</button>
            </div>
        </div>
        <div id="expTableWrap"></div>
    `;

    document.getElementById('expApplyBtn')?.addEventListener('click', () => loadExpensesIntoTable());
    document.getElementById('expNewBtn')?.addEventListener('click', () => showNewExpenseModal());

    await loadExpensesIntoTable();
}

async function loadExpensesIntoTable() {
    const wrap = document.getElementById('expTableWrap');
    if (!wrap) return;
    wrap.innerHTML = '<div class="spinner" style="margin: 1rem auto;"></div>';

    const df = document.getElementById('expDateFrom')?.value || null;
    const dt = document.getElementById('expDateTo')?.value || null;
    const st = document.getElementById('expStatus')?.value || '';

    const params = { branch_id: CONFIG.BRANCH_ID, date_from: df, date_to: dt, limit: 500, offset: 0 };
    if (st) params.status = st;

    let list = [];
    try {
        list = await API.expenses.list(params);
    } catch (e) {
        wrap.innerHTML = `<p style="color: var(--danger-color);">Failed to load expenses: ${(e && e.message) ? e.message : ''}</p>`;
        return;
    }
    list = Array.isArray(list) ? list : [];

    const canApprove = (typeof hasPermission === 'function') ? await hasPermission('expenses.edit', CONFIG.BRANCH_ID) : true;

    if (!list.length) {
        const emptyHtml = (window.EmptyStateWatermark && window.EmptyStateWatermark.render)
            ? window.EmptyStateWatermark.render({ title: 'No expenses found', description: 'Record your first expense using “New Expense”.' })
            : '<p style="color: var(--text-secondary);">No expenses found.</p>';
        wrap.innerHTML = emptyHtml;
        return;
    }

    wrap.innerHTML = `
        <div class="table-container" style="overflow-x:auto;">
            <table style="width:100%; border-collapse: collapse;">
                <thead>
                    <tr>
                        <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align:left;">Date</th>
                        <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align:left;">Category</th>
                        <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align:left;">Description</th>
                        <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align:left;">Mode</th>
                        <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align:right;">Amount</th>
                        <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align:left;">Status</th>
                        <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align:left;">Actions</th>
                    </tr>
                </thead>
                <tbody>
                    ${list.map(r => {
                        const status = (r.status || '—').toLowerCase();
                        const statusCls = status === 'approved' ? 'badge-success' : status === 'pending' ? 'badge-warning' : 'badge-secondary';
                        const mode = (r.payment_mode || '').toLowerCase() || '—';
                        const modeLabel = mode === 'mpesa' ? 'M-Pesa' : mode === 'bank' ? 'Bank' : mode === 'cash' ? 'Cash' : mode;
                        const approveBtn = (status === 'pending' && canApprove)
                            ? `<button class="btn btn-primary btn-sm" onclick="approveExpense('${r.id}')">Approve</button>`
                            : '—';
                        return `
                            <tr>
                                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">${(r.expense_date || '').slice(0, 10)}</td>
                                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">${escapeHtml(r.category_name || '—')}</td>
                                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">${escapeHtml(r.description || '—')}</td>
                                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">${escapeHtml(modeLabel)}</td>
                                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color); text-align:right;">${_fmtMoney(r.amount)}</td>
                                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);"><span class="badge ${statusCls}">${escapeHtml(status)}</span></td>
                                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">${approveBtn}</td>
                            </tr>
                        `;
                    }).join('')}
                </tbody>
            </table>
        </div>
    `;
}

async function showNewExpenseModal() {
    let cats = [];
    try { cats = await API.expenses.listCategories({ include_inactive: false }); } catch (_) {}
    cats = Array.isArray(cats) ? cats : [];
    if (!cats.length) {
        showToast('Create at least one expense category first.', 'warning');
        if (typeof loadPage === 'function') loadPage('expenses-categories');
        else await loadExpensesSubPage('categories');
        return;
    }

    const options = cats.map(c => `<option value="${escapeHtml(c.id)}">${escapeHtml(c.name)}</option>`).join('');
    const today = _localDateStr(new Date());

    const content = `
        <form id="newExpenseForm" style="max-width: 640px;">
            <div class="form-row">
                <div class="form-group" style="flex: 1;">
                    <label class="form-label">Date *</label>
                    <input type="date" class="form-input" name="expense_date" value="${today}" required>
                </div>
                <div class="form-group" style="flex: 1;">
                    <label class="form-label">Category *</label>
                    <select class="form-select" name="category_id" required>${options}</select>
                </div>
            </div>
            <div class="form-group">
                <label class="form-label">Description *</label>
                <input type="text" class="form-input" name="description" placeholder="e.g. Rent, Salary, Snacks" required>
            </div>
            <div class="form-row">
                <div class="form-group" style="flex: 1;">
                    <label class="form-label">Amount (KES) *</label>
                    <input type="number" class="form-input" name="amount" min="0.01" step="0.01" required>
                </div>
                <div class="form-group" style="flex: 1;">
                    <label class="form-label">Payment mode *</label>
                    <select class="form-select" name="payment_mode" required>
                        <option value="cash">Cash</option>
                        <option value="mpesa">M-Pesa</option>
                        <option value="bank">Bank</option>
                    </select>
                </div>
            </div>
            <div class="form-group">
                <label class="form-label">Reference (optional)</label>
                <input type="text" class="form-input" name="reference_number" placeholder="M-Pesa code / bank ref">
            </div>
        </form>
    `;
    const footer = `
        <button type="button" class="btn btn-outline" onclick="closeModal()">Cancel</button>
        <button type="button" class="btn btn-primary" id="newExpenseSaveBtn"><i class="fas fa-save"></i> Save</button>
    `;
    showModal('New Expense', content, footer);

    const btn = document.getElementById('newExpenseSaveBtn');
    btn?.addEventListener('click', async () => {
        const form = document.getElementById('newExpenseForm');
        if (!form) return;
        const fd = new FormData(form);
        const payload = {
            company_id: CONFIG.COMPANY_ID,
            branch_id: CONFIG.BRANCH_ID,
            category_id: fd.get('category_id'),
            description: fd.get('description'),
            amount: parseFloat(fd.get('amount') || 0),
            expense_date: fd.get('expense_date'),
            payment_mode: fd.get('payment_mode'),
            reference_number: (fd.get('reference_number') || '').toString().trim() || null,
        };
        if (!payload.company_id || !payload.branch_id) {
            showToast('Company/Branch not set.', 'error');
            return;
        }
        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Saving…';
        try {
            const res = await API.expenses.create(payload);
            closeModal();
            const st = (res && res.status) ? String(res.status).toLowerCase() : 'approved';
            if (st === 'pending') showToast('Expense recorded and pending approval.', 'warning');
            else showToast('Expense recorded (approved).', 'success');
            await loadExpensesIntoTable();
        } catch (e) {
            showToast((e && e.message) ? e.message : 'Failed to save expense', 'error');
            btn.disabled = false;
            btn.innerHTML = '<i class="fas fa-save"></i> Save';
        }
    });
}

async function approveExpense(expenseId) {
    if (!expenseId) return;
    if (!confirm('Approve this expense? It will start affecting Net Profit in reports.')) return;
    try {
        await API.expenses.approve(expenseId);
        showToast('Expense approved', 'success');
        await loadExpensesIntoTable();
    } catch (e) {
        showToast((e && e.message) ? e.message : 'Failed to approve expense', 'error');
    }
}

async function renderExpenseCategories() {
    const body = document.getElementById('expensesBody');
    if (!body) return;

    body.innerHTML = `
        <div style="display:flex; justify-content: space-between; align-items: center; gap: 0.75rem; flex-wrap: wrap; margin-bottom: 1rem;">
            <p style="margin:0; color: var(--text-secondary);">Create categories like Rent, Salaries, Utilities, Misc.</p>
            <button class="btn btn-primary" id="newExpCatBtn"><i class="fas fa-plus"></i> New Category</button>
        </div>
        <div id="expCatTableWrap"></div>
    `;
    document.getElementById('newExpCatBtn')?.addEventListener('click', () => showNewCategoryModal());
    await loadCategoriesIntoTable();
}

async function loadCategoriesIntoTable() {
    const wrap = document.getElementById('expCatTableWrap');
    if (!wrap) return;
    wrap.innerHTML = '<div class="spinner" style="margin: 1rem auto;"></div>';
    let cats = [];
    try { cats = await API.expenses.listCategories({ include_inactive: true }); } catch (e) {
        wrap.innerHTML = `<p style="color: var(--danger-color);">Failed to load categories: ${(e && e.message) ? e.message : ''}</p>`;
        return;
    }
    cats = Array.isArray(cats) ? cats : [];
    if (!cats.length) {
        wrap.innerHTML = '<p style="color: var(--text-secondary);">No categories yet.</p>';
        return;
    }
    wrap.innerHTML = `
        <div class="table-container" style="overflow-x:auto;">
            <table style="width:100%; border-collapse: collapse;">
                <thead>
                    <tr>
                        <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align:left;">Name</th>
                        <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align:left;">Description</th>
                        <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align:left;">Status</th>
                        <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align:left;">Actions</th>
                    </tr>
                </thead>
                <tbody>
                    ${cats.map(c => {
                        const active = c.is_active !== false;
                        const badgeCls = active ? 'badge-success' : 'badge-danger';
                        const toggleLabel = active ? 'Deactivate' : 'Activate';
                        return `
                            <tr>
                                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);"><strong>${escapeHtml(c.name || '—')}</strong></td>
                                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">${escapeHtml(c.description || '—')}</td>
                                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);"><span class="badge ${badgeCls}">${active ? 'Active' : 'Inactive'}</span></td>
                                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color); display:flex; gap:0.5rem; flex-wrap: wrap;">
                                    <button class="btn btn-outline btn-sm" onclick="editExpenseCategory('${c.id}')">Edit</button>
                                    <button class="btn btn-outline btn-sm" onclick="toggleExpenseCategory('${c.id}', ${active ? 'false' : 'true'})">${toggleLabel}</button>
                                </td>
                            </tr>
                        `;
                    }).join('')}
                </tbody>
            </table>
        </div>
    `;
}

async function showNewCategoryModal(existing = null) {
    const isEdit = !!existing;
    const content = `
        <form id="expenseCategoryForm" style="max-width: 560px;">
            <div class="form-group">
                <label class="form-label">Name *</label>
                <input type="text" class="form-input" name="name" value="${escapeHtml(existing?.name || '')}" required>
            </div>
            <div class="form-group">
                <label class="form-label">Description</label>
                <textarea class="form-textarea" name="description" rows="2">${escapeHtml(existing?.description || '')}</textarea>
            </div>
        </form>
    `;
    const footer = `
        <button type="button" class="btn btn-outline" onclick="closeModal()">Cancel</button>
        <button type="button" class="btn btn-primary" id="saveExpCatBtn"><i class="fas fa-save"></i> ${isEdit ? 'Save' : 'Create'}</button>
    `;
    showModal(isEdit ? 'Edit Category' : 'New Category', content, footer);
    const btn = document.getElementById('saveExpCatBtn');
    btn?.addEventListener('click', async () => {
        const form = document.getElementById('expenseCategoryForm');
        if (!form) return;
        const fd = new FormData(form);
        const payload = {
            company_id: CONFIG.COMPANY_ID,
            name: fd.get('name'),
            description: (fd.get('description') || '').toString().trim() || null,
            is_active: true,
        };
        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Saving…';
        try {
            if (isEdit) {
                await API.expenses.updateCategory(existing.id, { name: payload.name, description: payload.description });
            } else {
                await API.expenses.createCategory(payload);
            }
            closeModal();
            showToast(isEdit ? 'Category updated' : 'Category created', 'success');
            await loadCategoriesIntoTable();
        } catch (e) {
            showToast((e && e.message) ? e.message : 'Failed to save category', 'error');
            btn.disabled = false;
            btn.innerHTML = '<i class="fas fa-save"></i> ' + (isEdit ? 'Save' : 'Create');
        }
    });
}

async function editExpenseCategory(categoryId) {
    let cats = [];
    try { cats = await API.expenses.listCategories({ include_inactive: true }); } catch (_) {}
    const c = (Array.isArray(cats) ? cats : []).find(x => String(x.id) === String(categoryId));
    if (!c) return showToast('Category not found', 'error');
    showNewCategoryModal(c);
}

async function toggleExpenseCategory(categoryId, isActive) {
    try {
        await API.expenses.updateCategory(categoryId, { is_active: !!isActive });
        showToast('Category updated', 'success');
        await loadCategoriesIntoTable();
    } catch (e) {
        showToast((e && e.message) ? e.message : 'Failed to update category', 'error');
    }
}

function _expInsightsStartOfWeekMonday(d) {
    const x = new Date(d);
    const wd = x.getDay();
    const diff = (wd === 0 ? -6 : 1 - wd);
    x.setDate(x.getDate() + diff);
    x.setHours(0, 0, 0, 0);
    return x;
}

function _expInsightsEndOfWeekSunday(d) {
    const s = _expInsightsStartOfWeekMonday(d);
    const e = new Date(s);
    e.setDate(e.getDate() + 6);
    e.setHours(0, 0, 0, 0);
    return e;
}

function _expInsightsStartOfMonth(d) {
    const x = new Date(d.getFullYear(), d.getMonth(), 1);
    x.setHours(0, 0, 0, 0);
    return x;
}

function _expInsightsEndOfMonth(d) {
    const x = new Date(d.getFullYear(), d.getMonth() + 1, 0);
    x.setHours(0, 0, 0, 0);
    return x;
}

function _expInsightsStartOfYear(d) {
    const x = new Date(d.getFullYear(), 0, 1);
    x.setHours(0, 0, 0, 0);
    return x;
}

function _expInsightsEndOfYear(d) {
    const x = new Date(d.getFullYear(), 11, 31);
    x.setHours(0, 0, 0, 0);
    return x;
}

function _expInsightsPresetRange(preset) {
    const now = new Date();
    now.setHours(0, 0, 0, 0);
    const p = (preset || '').toLowerCase();
    if (p === 'today') return { start: now, end: now };
    if (p === 'this_week') return { start: _expInsightsStartOfWeekMonday(now), end: _expInsightsEndOfWeekSunday(now) };
    if (p === 'last_week') {
        const end = new Date(_expInsightsStartOfWeekMonday(now));
        end.setDate(end.getDate() - 1);
        end.setHours(0, 0, 0, 0);
        return { start: _expInsightsStartOfWeekMonday(end), end };
    }
    if (p === 'this_month') return { start: _expInsightsStartOfMonth(now), end: _expInsightsEndOfMonth(now) };
    if (p === 'last_month') {
        const prev = new Date(now.getFullYear(), now.getMonth() - 1, 1);
        prev.setHours(0, 0, 0, 0);
        return { start: _expInsightsStartOfMonth(prev), end: _expInsightsEndOfMonth(prev) };
    }
    if (p === 'this_year') return { start: _expInsightsStartOfYear(now), end: _expInsightsEndOfYear(now) };
    if (p === 'last_year') {
        const prev = new Date(now.getFullYear() - 1, 0, 1);
        prev.setHours(0, 0, 0, 0);
        return { start: _expInsightsStartOfYear(prev), end: _expInsightsEndOfYear(prev) };
    }
    return { start: _expInsightsStartOfMonth(now), end: now };
}

function _expInsightsBranchId() {
    return (typeof BranchContext !== 'undefined' && BranchContext.getBranch && BranchContext.getBranch()?.id) || CONFIG.BRANCH_ID || null;
}

function _expInsightsPaymentLabel(mode) {
    const m = (mode || '').toLowerCase();
    if (m === 'mpesa') return 'M-Pesa';
    if (m === 'bank') return 'Bank';
    if (m === 'cash') return 'Cash';
    return m || 'Other';
}

async function renderExpenseInsights() {
    const body = document.getElementById('expensesBody');
    if (!body) return;

    const branchId = _expInsightsBranchId();
    const today = new Date();
    const defaultStart = _localDateStr(_expInsightsStartOfMonth(today));
    const defaultEnd = _localDateStr(today);

    body.innerHTML = `
        <p style="margin: 0 0 1rem; color: var(--text-secondary); font-size: 0.9rem;">
            Approved totals match <strong>Financial Reports → Net profit</strong>. Below: expense-specific breakdowns and pending items.
        </p>
        <div style="display:flex; flex-wrap:wrap; gap:0.75rem; align-items:end; margin-bottom: 1rem;">
            <div class="form-group" style="min-width: 200px; margin: 0;">
                <label class="form-label">Period</label>
                <select class="form-select" id="expInsightPreset">
                    <option value="this_month" selected>This month</option>
                    <option value="today">Today</option>
                    <option value="this_week">This week</option>
                    <option value="last_week">Last week</option>
                    <option value="last_month">Last month</option>
                    <option value="this_year">This year</option>
                    <option value="last_year">Last year</option>
                    <option value="custom">Custom</option>
                </select>
            </div>
            <div class="form-group" style="margin: 0;">
                <label class="form-label">From</label>
                <input type="date" class="form-input" id="expInsightFrom" value="${defaultStart}">
            </div>
            <div class="form-group" style="margin: 0;">
                <label class="form-label">To</label>
                <input type="date" class="form-input" id="expInsightTo" value="${defaultEnd}">
            </div>
            <button type="button" class="btn btn-primary" id="expInsightApply"><i class="fas fa-sync"></i> Apply</button>
            <button type="button" class="btn btn-outline" id="expInsightFinancial"><i class="fas fa-chart-line"></i> Financial Reports</button>
        </div>
        <div id="expInsightSummary" style="display:grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 0.75rem; margin-bottom: 1.25rem;"></div>
        <div id="expInsightPanels"></div>
    `;

    const presetEl = document.getElementById('expInsightPreset');
    const fromEl = document.getElementById('expInsightFrom');
    const toEl = document.getElementById('expInsightTo');

    presetEl?.addEventListener('change', () => {
        const p = presetEl.value;
        if (p === 'custom') return;
        const r = _expInsightsPresetRange(p);
        if (fromEl) fromEl.value = _localDateStr(r.start);
        if (toEl) toEl.value = _localDateStr(r.end);
    });

    document.getElementById('expInsightApply')?.addEventListener('click', () => loadExpenseInsightsData());
    document.getElementById('expInsightFinancial')?.addEventListener('click', () => {
        if (typeof loadPage === 'function') loadPage('reports-financial');
        else window.location.hash = '#reports-financial';
    });

    await loadExpenseInsightsData();
}

async function loadExpenseInsightsData() {
    const summaryEl = document.getElementById('expInsightSummary');
    const panelsEl = document.getElementById('expInsightPanels');
    if (!summaryEl || !panelsEl) return;

    const branchId = _expInsightsBranchId();
    if (!branchId) {
        panelsEl.innerHTML = '<p style="color: var(--warning-color);">Select a branch to view expense insights.</p>';
        return;
    }

    const start = document.getElementById('expInsightFrom')?.value;
    const end = document.getElementById('expInsightTo')?.value;
    if (!start || !end) {
        showToast('Pick a valid date range.', 'warning');
        return;
    }

    summaryEl.innerHTML = '';
    panelsEl.innerHTML = '<div class="spinner" style="margin: 1rem auto;"></div>';

    let summary = null;
    let allRows = [];
    try {
        const [sumRes, listRes] = await Promise.all([
            (API && API.expenses && typeof API.expenses.summary === 'function')
                ? API.expenses.summary({ branch_id: branchId, start_date: start, end_date: end, include_breakdown: true })
                : Promise.resolve(null),
            API.expenses.list({ branch_id: branchId, date_from: start, date_to: end, limit: 1000, offset: 0 }),
        ]);
        summary = sumRes;
        allRows = Array.isArray(listRes) ? listRes : [];
    } catch (e) {
        panelsEl.innerHTML = `<p style="color: var(--danger-color);">Failed to load insights: ${escapeHtml((e && e.message) ? e.message : '')}</p>`;
        return;
    }

    const approvedTotal = summary ? parseFloat(summary.total_expenses || 0) : 0;
    let pendingTotal = 0;
    let pendingCount = 0;
    const byCategory = {};
    const byMode = {};
    allRows.forEach((r) => {
        const amt = parseFloat(r.amount || 0);
        const st = (r.status || '').toLowerCase();
        if (st === 'pending') {
            pendingTotal += amt;
            pendingCount += 1;
            return;
        }
        if (st !== 'approved') return;
        const cat = r.category_name || 'Uncategorized';
        byCategory[cat] = (byCategory[cat] || 0) + amt;
        const mode = _expInsightsPaymentLabel(r.payment_mode);
        byMode[mode] = (byMode[mode] || 0) + amt;
    });

    const txnCount = allRows.length;
    const avgApproved = approvedTotal > 0 && summary && Array.isArray(summary.breakdown) && summary.breakdown.length
        ? approvedTotal / summary.breakdown.filter((b) => parseFloat(b.total_expenses || 0) > 0).length
        : (txnCount ? approvedTotal / Math.max(1, allRows.filter((r) => (r.status || '').toLowerCase() === 'approved').length) : 0);

    summaryEl.innerHTML = `
        <div class="card" style="padding: 1rem; margin: 0;">
            <h4 style="margin: 0 0 0.25rem; font-size: 1.25rem;">${_fmtMoney(approvedTotal)}</h4>
            <p style="margin: 0; color: var(--text-secondary); font-size: 0.85rem;">Approved (in Net profit)</p>
        </div>
        <div class="card" style="padding: 1rem; margin: 0;">
            <h4 style="margin: 0 0 0.25rem; font-size: 1.25rem;">${_fmtMoney(pendingTotal)}</h4>
            <p style="margin: 0; color: var(--text-secondary); font-size: 0.85rem;">Pending (${pendingCount})</p>
        </div>
        <div class="card" style="padding: 1rem; margin: 0;">
            <h4 style="margin: 0 0 0.25rem; font-size: 1.25rem;">${txnCount}</h4>
            <p style="margin: 0; color: var(--text-secondary); font-size: 0.85rem;">Transactions</p>
        </div>
        <div class="card" style="padding: 1rem; margin: 0;">
            <h4 style="margin: 0 0 0.25rem; font-size: 1.25rem;">${_fmtMoney(avgApproved)}</h4>
            <p style="margin: 0; color: var(--text-secondary); font-size: 0.85rem;">Avg / active day</p>
        </div>
    `;

    const catRows = Object.entries(byCategory).sort((a, b) => b[1] - a[1]);
    const modeRows = Object.entries(byMode).sort((a, b) => b[1] - a[1]);
    const dailyRows = (summary && Array.isArray(summary.breakdown) ? summary.breakdown : [])
        .filter((r) => parseFloat(r.total_expenses || 0) > 0)
        .sort((a, b) => String(a.date).localeCompare(String(b.date)));

    const pct = (part, whole) => (whole > 0 ? ((part / whole) * 100).toFixed(1) : '0.0');

    const catTable = catRows.length
        ? catRows.map(([name, total]) => `
            <tr>
                <td style="padding: 0.5rem; border-bottom: 1px solid var(--border-color);">${escapeHtml(name)}</td>
                <td style="padding: 0.5rem; border-bottom: 1px solid var(--border-color); text-align:right;">${_fmtMoney(total)}</td>
                <td style="padding: 0.5rem; border-bottom: 1px solid var(--border-color); text-align:right;">${pct(total, approvedTotal)}%</td>
            </tr>
        `).join('')
        : '<tr><td colspan="3" style="padding: 0.75rem; color: var(--text-secondary);">No approved expenses in range.</td></tr>';

    const modeTable = modeRows.length
        ? modeRows.map(([name, total]) => `
            <tr>
                <td style="padding: 0.5rem; border-bottom: 1px solid var(--border-color);">${escapeHtml(name)}</td>
                <td style="padding: 0.5rem; border-bottom: 1px solid var(--border-color); text-align:right;">${_fmtMoney(total)}</td>
                <td style="padding: 0.5rem; border-bottom: 1px solid var(--border-color); text-align:right;">${pct(total, approvedTotal)}%</td>
            </tr>
        `).join('')
        : '<tr><td colspan="3" style="padding: 0.75rem; color: var(--text-secondary);">No payment breakdown.</td></tr>';

    const dailyTable = dailyRows.length
        ? dailyRows.map((r) => {
            const d = (r.date || '').toString().slice(0, 10);
            const t = parseFloat(r.total_expenses || 0);
            return `
                <tr>
                    <td style="padding: 0.5rem; border-bottom: 1px solid var(--border-color);">${d}</td>
                    <td style="padding: 0.5rem; border-bottom: 1px solid var(--border-color); text-align:right;">${_fmtMoney(t)}</td>
                </tr>
            `;
        }).join('')
        : '<tr><td colspan="2" style="padding: 0.75rem; color: var(--text-secondary);">No daily spend in range.</td></tr>';

    panelsEl.innerHTML = `
        <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 1rem;">
            <div class="card" style="padding: 1rem;">
                <h4 style="margin: 0 0 0.75rem;"><i class="fas fa-folder"></i> By category</h4>
                <div style="overflow:auto;">
                    <table style="width:100%; border-collapse: collapse;">
                        <thead>
                            <tr>
                                <th style="padding: 0.5rem; border-bottom: 2px solid var(--border-color); text-align:left;">Category</th>
                                <th style="padding: 0.5rem; border-bottom: 2px solid var(--border-color); text-align:right;">Amount</th>
                                <th style="padding: 0.5rem; border-bottom: 2px solid var(--border-color); text-align:right;">Share</th>
                            </tr>
                        </thead>
                        <tbody>${catTable}</tbody>
                    </table>
                </div>
            </div>
            <div class="card" style="padding: 1rem;">
                <h4 style="margin: 0 0 0.75rem;"><i class="fas fa-wallet"></i> By payment mode</h4>
                <div style="overflow:auto;">
                    <table style="width:100%; border-collapse: collapse;">
                        <thead>
                            <tr>
                                <th style="padding: 0.5rem; border-bottom: 2px solid var(--border-color); text-align:left;">Mode</th>
                                <th style="padding: 0.5rem; border-bottom: 2px solid var(--border-color); text-align:right;">Amount</th>
                                <th style="padding: 0.5rem; border-bottom: 2px solid var(--border-color); text-align:right;">Share</th>
                            </tr>
                        </thead>
                        <tbody>${modeTable}</tbody>
                    </table>
                </div>
            </div>
            <div class="card" style="padding: 1rem; grid-column: 1 / -1;">
                <h4 style="margin: 0 0 0.75rem;"><i class="fas fa-calendar-day"></i> Daily approved spend</h4>
                <div style="overflow:auto; max-height: 320px;">
                    <table style="width:100%; border-collapse: collapse;">
                        <thead>
                            <tr>
                                <th style="padding: 0.5rem; border-bottom: 2px solid var(--border-color); text-align:left;">Date</th>
                                <th style="padding: 0.5rem; border-bottom: 2px solid var(--border-color); text-align:right;">Approved</th>
                            </tr>
                        </thead>
                        <tbody>${dailyTable}</tbody>
                    </table>
                </div>
            </div>
        </div>
    `;
}

// Export
if (typeof window !== 'undefined') {
    window.loadExpenses = loadExpenses;
    window.loadExpensesSubPage = loadExpensesSubPage;
    window.showNewExpenseModal = showNewExpenseModal;
    window.approveExpense = approveExpense;
    window.editExpenseCategory = editExpenseCategory;
    window.toggleExpenseCategory = toggleExpenseCategory;
}

