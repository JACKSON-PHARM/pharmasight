// Reports Page - Sales / Inventory / Financial

console.log('[REPORTS.JS] Script loading...');

let currentReportsSubPage = 'financial';

function _fmtDateInput(d) {
    const yyyy = d.getFullYear();
    const mm = String(d.getMonth() + 1).padStart(2, '0');
    const dd = String(d.getDate()).padStart(2, '0');
    return `${yyyy}-${mm}-${dd}`;
}

function _parseDateInput(v) {
    if (!v) return null;
    const parts = String(v).split('-');
    if (parts.length !== 3) return null;
    const d = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]));
    if (isNaN(d.getTime())) return null;
    d.setHours(0, 0, 0, 0);
    return d;
}

function _startOfWeekMonday(d) {
    const x = new Date(d);
    const wd = x.getDay(); // 0..6 (Sun..Sat)
    const diff = (wd === 0 ? -6 : 1 - wd); // move to Monday
    x.setDate(x.getDate() + diff);
    x.setHours(0, 0, 0, 0);
    return x;
}

function _endOfWeekSunday(d) {
    const s = _startOfWeekMonday(d);
    const e = new Date(s);
    e.setDate(e.getDate() + 6);
    e.setHours(0, 0, 0, 0);
    return e;
}

function _startOfMonth(d) {
    const x = new Date(d.getFullYear(), d.getMonth(), 1);
    x.setHours(0, 0, 0, 0);
    return x;
}

function _endOfMonth(d) {
    const x = new Date(d.getFullYear(), d.getMonth() + 1, 0);
    x.setHours(0, 0, 0, 0);
    return x;
}

function _startOfYear(d) {
    const x = new Date(d.getFullYear(), 0, 1);
    x.setHours(0, 0, 0, 0);
    return x;
}

function _endOfYear(d) {
    const x = new Date(d.getFullYear(), 11, 31);
    x.setHours(0, 0, 0, 0);
    return x;
}

function _computePresetRange(preset) {
    const now = new Date();
    now.setHours(0, 0, 0, 0);
    const p = (preset || '').toLowerCase();
    if (p === 'today') return { start: now, end: now };
    if (p === 'this_week') return { start: _startOfWeekMonday(now), end: _endOfWeekSunday(now) };
    if (p === 'last_week') {
        const end = new Date(_startOfWeekMonday(now));
        end.setDate(end.getDate() - 1);
        end.setHours(0, 0, 0, 0);
        const start = _startOfWeekMonday(end);
        return { start, end };
    }
    if (p === 'this_month') return { start: _startOfMonth(now), end: _endOfMonth(now) };
    if (p === 'last_month') {
        const prev = new Date(now.getFullYear(), now.getMonth() - 1, 1);
        prev.setHours(0, 0, 0, 0);
        return { start: _startOfMonth(prev), end: _endOfMonth(prev) };
    }
    if (p === 'this_year') return { start: _startOfYear(now), end: _endOfYear(now) };
    if (p === 'last_year') {
        const prev = new Date(now.getFullYear() - 1, 0, 1);
        prev.setHours(0, 0, 0, 0);
        return { start: _startOfYear(prev), end: _endOfYear(prev) };
    }
    return { start: now, end: now };
}

async function loadReports(subPage = null) {
    const page = document.getElementById('reports');
    if (!page) {
        console.error('[REPORTS] Page element not found');
        return;
    }
    const target = subPage || currentReportsSubPage || 'financial';
    await loadReportsSubPage(target);
}

async function loadReportsSubPage(subPage) {
    currentReportsSubPage = subPage || 'financial';
    const page = document.getElementById('reports');
    if (!page) return;

    // Basic shell
    const titleMap = {
        'sales': 'Sales Reports',
        'inventory': 'Inventory Reports',
        'financial': 'Financial Reports',
        'item-movement': 'Item Movement Report',
        'custom': 'Custom Reports'
    };
    const title = titleMap[currentReportsSubPage] || 'Reports';

    page.innerHTML = `
        <div class="card">
            <div class="card-header">
                <h3 class="card-title"><i class="fas fa-chart-bar"></i> ${title}</h3>
            </div>
            <div class="card-body" id="reportsBody">
                <div class="spinner" style="margin: 1rem auto;"></div>
            </div>
        </div>
    `;

    if (currentReportsSubPage === 'item-movement') {
        await renderItemMovementReport();
        return;
    }
    if (currentReportsSubPage !== 'financial') {
        const body = document.getElementById('reportsBody');
        if (body) {
            body.innerHTML = `
                <div class="alert alert-info">
                    <i class="fas fa-info-circle"></i>
                    <p>This report is coming soon.</p>
                </div>
            `;
        }
        return;
    }

    await renderFinancialReports();
}

function _ensureBranchSelected() {
    const branchId = (typeof BranchContext !== 'undefined' && BranchContext.getBranch && BranchContext.getBranch()?.id) || CONFIG.BRANCH_ID || null;
    if (!branchId) {
        if (typeof showToast === 'function') showToast('Select a branch first.', 'warning');
        return null;
    }
    return branchId;
}

async function renderFinancialReports() {
    const body = document.getElementById('reportsBody');
    if (!body) return;

    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const defaultStart = _fmtDateInput(today);
    const defaultEnd = _fmtDateInput(today);

    body.innerHTML = `
        <div style="display:flex; flex-wrap:wrap; gap:0.75rem; align-items:end; margin-bottom: 1rem;">
            <div class="form-group" style="min-width: 220px; margin: 0;">
                <label class="form-label">Quick filter</label>
                <select class="form-input" id="plPreset">
                    <option value="today" selected>Today</option>
                    <option value="this_week">This week</option>
                    <option value="last_week">Last week</option>
                    <option value="this_month">This month</option>
                    <option value="last_month">Last month</option>
                    <option value="this_year">This year</option>
                    <option value="last_year">Last year</option>
                    <option value="custom">Custom</option>
                </select>
            </div>
            <div class="form-group" style="margin: 0;">
                <label class="form-label">Start date</label>
                <input type="date" class="form-input" id="plStart" value="${defaultStart}">
            </div>
            <div class="form-group" style="margin: 0;">
                <label class="form-label">End date</label>
                <input type="date" class="form-input" id="plEnd" value="${defaultEnd}">
            </div>
            <div style="margin: 0;">
                <button class="btn btn-primary" id="plApplyBtn"><i class="fas fa-filter"></i> Apply</button>
            </div>
        </div>

        <div class="stats-grid" style="margin-bottom: 1rem;">
            <div class="stat-card">
                <div class="stat-icon"><i class="fas fa-receipt"></i></div>
                <div class="stat-info">
                    <h3 id="plSales">—</h3>
                    <p>Sales (exclusive)</p>
                </div>
            </div>
            <div class="stat-card">
                <div class="stat-icon"><i class="fas fa-boxes-stacked"></i></div>
                <div class="stat-info">
                    <h3 id="plCogs">—</h3>
                    <p>Cost of goods sold (COGS)</p>
                </div>
            </div>
            <div class="stat-card">
                <div class="stat-icon"><i class="fas fa-chart-pie"></i></div>
                <div class="stat-info">
                    <h3 id="plGrossProfit">—</h3>
                    <p id="plMeta">Gross profit • Margin —</p>
                </div>
            </div>
        </div>

        <div class="card" style="margin-top: 0.5rem;">
            <div class="card-header">
                <h3 class="card-title"><i class="fas fa-calendar-day"></i> Breakdown</h3>
            </div>
            <div class="card-body" id="plBreakdown">
                <p style="color: var(--text-secondary);">Apply a filter to load results.</p>
            </div>
        </div>
    `;

    const presetEl = document.getElementById('plPreset');
    const startEl = document.getElementById('plStart');
    const endEl = document.getElementById('plEnd');
    const applyBtn = document.getElementById('plApplyBtn');

    function applyPreset(p) {
        if (p === 'custom') return;
        const r = _computePresetRange(p);
        startEl.value = _fmtDateInput(r.start);
        endEl.value = _fmtDateInput(r.end);
    }

    presetEl.addEventListener('change', () => {
        const p = presetEl.value;
        applyPreset(p);
    });

    applyBtn.addEventListener('click', async () => {
        await loadGrossProfitReport();
    });

    // Default: today
    await loadGrossProfitReport();
}

// --- Item Movement Report (shared by Reports and Inventory) ---
let itemMovementSelectedItem = null; // { id, name, sku }
/** Last API response for CSV/PDF export (same payload). */
let lastItemMovementReportData = null;

function _itemMovementReportThisMonth() {
    return _computePresetRange('this_month');
}

function _escapeHtml(s) {
    if (s == null) return '';
    const div = document.createElement('div');
    div.textContent = s;
    return div.innerHTML;
}
if (typeof window !== 'undefined') window.escapeHtml = window.escapeHtml || _escapeHtml;

function getItemMovementReportHTML() {
    const thisMonth = _itemMovementReportThisMonth();
    return `
        <div class="card" style="margin-bottom: 1rem;">
            <div class="card-header">
                <h4 class="card-title" style="font-size: 1rem;"><i class="fas fa-filter"></i> Report Parameters</h4>
            </div>
            <div class="card-body">
                <div style="display:flex; flex-wrap:wrap; gap:0.75rem; align-items:end;">
                    <div class="form-group" style="min-width: 180px; margin: 0;">
                        <label class="form-label">Date</label>
                        <select class="form-input" id="imPreset">
                            <option value="today">Today</option>
                            <option value="this_month" selected>This Month</option>
                            <option value="last_month">Last Month</option>
                            <option value="custom">Custom</option>
                        </select>
                    </div>
                    <div class="form-group" style="margin: 0;">
                        <label class="form-label">From</label>
                        <input type="date" class="form-input" id="imStart" value="${_fmtDateInput(thisMonth.start)}">
                    </div>
                    <div class="form-group" style="margin: 0;">
                        <label class="form-label">To</label>
                        <input type="date" class="form-input" id="imEnd" value="${_fmtDateInput(thisMonth.end)}">
                    </div>
                    <div class="form-group" style="min-width: 280px; margin: 0; flex: 1;">
                        <label class="form-label">Items</label>
                        <input type="text" class="form-input" id="imItemSearch" placeholder="Search item by name or SKU..." autocomplete="off">
                        <input type="hidden" id="imItemId" value="">
                        <div id="imItemDropdown" class="dropdown-list" style="display:none; position:absolute; z-index:100; max-height:220px; overflow:auto; background: var(--bg-secondary); border: 1px solid var(--border-color); border-radius: 6px; box-shadow: 0 4px 12px rgba(0,0,0,0.15); min-width: 280px;"></div>
                        <div id="imItemSelected" style="margin-top: 4px; font-size: 0.875rem; color: var(--text-secondary);"></div>
                    </div>
                    <div style="margin: 0; display: flex; gap: 0.5rem;">
                        <button class="btn btn-primary" id="imApplyBtn"><i class="fas fa-check"></i> Apply</button>
                        <button class="btn btn-secondary" id="imClearBtn">Clear</button>
                    </div>
                </div>
                <div id="imFiltersSummary" style="margin-top: 0.5rem; font-size: 0.875rem; color: var(--text-secondary);"></div>
            </div>
        </div>

        <div id="imReportContainer" style="display: none;">
            <div class="card" style="margin-bottom: 0.5rem;">
                <div class="card-body" style="padding: 0.5rem; display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem;">
                    <button type="button" class="btn btn-outline btn-sm" id="imPrintBtn"><i class="fas fa-print"></i> Print</button>
                    <button type="button" class="btn btn-outline btn-sm" id="imPdfBtn"><i class="fas fa-file-pdf"></i> Download PDF</button>
                    <button type="button" class="btn btn-outline btn-sm" id="imCsvBtn"><i class="fas fa-file-csv"></i> Download CSV</button>
                </div>
            </div>
            <div id="imReportContent" class="item-movement-report-doc" style="background: #fff; padding: 20px; max-width: 210mm; margin: 0 auto; border: 1px solid #ddd; box-shadow: 0 2px 8px rgba(0,0,0,0.08); font-family: 'Segoe UI', Arial, sans-serif; font-size: 12px; line-height: 1.4; color: #222;"></div>
        </div>

        <div id="imReportPlaceholder" style="color: var(--text-secondary); padding: 1rem;">Select date range and item, then click Apply to generate the report.</div>
    `;
}

function setupItemMovementReportHandlers(root) {
    if (!root) return;
    const branchId = (typeof _ensureBranchSelected === 'function' ? _ensureBranchSelected() : null) || (typeof getBranchIdForStock === 'function' ? getBranchIdForStock() : null);
    const presetEl = root.querySelector('#imPreset');
    const startEl = root.querySelector('#imStart');
    const endEl = root.querySelector('#imEnd');
    const itemSearchEl = root.querySelector('#imItemSearch');
    const itemIdEl = root.querySelector('#imItemId');
    const itemDropdownEl = root.querySelector('#imItemDropdown');
    const itemSelectedEl = root.querySelector('#imItemSelected');
    const applyBtn = root.querySelector('#imApplyBtn');
    const clearBtn = root.querySelector('#imClearBtn');
    const summaryEl = root.querySelector('#imFiltersSummary');
    if (!presetEl || !startEl || !endEl || !itemSearchEl || !itemIdEl || !itemDropdownEl || !applyBtn || !clearBtn) return;

    function applyPreset(p) {
        if (p === 'custom') return;
        const r = _computePresetRange(p);
        startEl.value = _fmtDateInput(r.start);
        endEl.value = _fmtDateInput(r.end);
    }
    presetEl.addEventListener('change', () => applyPreset(presetEl.value));

    let searchTimeout = null;
    itemSearchEl.addEventListener('input', () => {
        itemIdEl.value = '';
        itemMovementSelectedItem = null;
        if (itemSelectedEl) itemSelectedEl.textContent = '';
        const q = (itemSearchEl.value || '').trim();
        if (q.length < 2) {
            itemDropdownEl.style.display = 'none';
            return;
        }
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(async () => {
            try {
                const companyId = typeof CONFIG !== 'undefined' ? CONFIG.COMPANY_ID : null;
                const bid = branchId || (typeof getBranchIdForStock === 'function' ? getBranchIdForStock() : null);
                if (!companyId || !API || !API.items || !API.items.search) {
                    itemDropdownEl.innerHTML = '<div style="padding: 8px;">Company not set or items API not available.</div>';
                    itemDropdownEl.style.display = 'block';
                    return;
                }
                const res = await API.items.search(q, companyId, 15, bid, false);
                const items = Array.isArray(res) ? res : (res && res.items) || [];
                if (!items.length) {
                    itemDropdownEl.innerHTML = '<div style="padding: 8px;">No items found.</div>';
                } else {
                    itemDropdownEl.innerHTML = items.map(it => {
                        const stockNum = typeof it.current_stock === 'number' ? it.current_stock : (it.stock != null ? Number(it.stock) : null);
                        const stockDisplayStr = it.stock_display != null ? String(it.stock_display) : (stockNum != null ? stockNum + ' ' + (it.base_unit || '') : '');
                        let stockColor = 'var(--text-secondary)';
                        if (stockNum !== null && stockNum !== undefined) {
                            if (stockNum <= 0) stockColor = 'var(--danger-color)';
                            else if (stockNum > 0 && stockNum < 5) stockColor = 'var(--warning-color)';
                            else stockColor = 'var(--success-color)';
                        }
                        const stockLine = stockDisplayStr
                            ? `<div style="font-size: 0.75rem; color: ${stockColor}; margin-top: 2px;">Stock: ${_escapeHtml(stockDisplayStr)}</div>`
                            : '';
                        return `
                        <div class="dropdown-item" data-id="${it.id}" data-name="${_escapeHtml(it.name || '')}" data-sku="${_escapeHtml(it.sku || '')}" style="padding: 8px 12px; cursor: pointer; border-bottom: 1px solid var(--border-color);">
                            <div>${_escapeHtml(it.name || '')} ${it.sku ? '<span style="color: var(--text-secondary);">(' + _escapeHtml(it.sku) + ')</span>' : ''}</div>
                            ${stockLine}
                        </div>`;
                    }).join('');
                    itemDropdownEl.querySelectorAll('.dropdown-item').forEach(el => {
                        el.addEventListener('click', () => {
                            itemMovementSelectedItem = { id: el.dataset.id, name: el.dataset.name, sku: el.dataset.sku || '' };
                            itemIdEl.value = el.dataset.id;
                            itemSearchEl.value = el.dataset.name + (el.dataset.sku ? ' (' + el.dataset.sku + ')' : '');
                            if (itemSelectedEl) itemSelectedEl.textContent = 'Selected: ' + (el.dataset.sku || el.dataset.name);
                            itemDropdownEl.style.display = 'none';
                        });
                    });
                }
                itemDropdownEl.style.display = 'block';
            } catch (err) {
                itemDropdownEl.innerHTML = '<div style="padding: 8px; color: var(--danger-color);">Search failed.</div>';
                itemDropdownEl.style.display = 'block';
            }
        }, 300);
    });
    itemSearchEl.addEventListener('blur', () => {
        setTimeout(() => { itemDropdownEl.style.display = 'none'; }, 200);
    });

    clearBtn.addEventListener('click', () => {
        presetEl.value = 'this_month';
        applyPreset('this_month');
        itemSearchEl.value = '';
        itemIdEl.value = '';
        itemMovementSelectedItem = null;
        if (itemSelectedEl) itemSelectedEl.textContent = '';
        if (summaryEl) summaryEl.textContent = '';
        const cont = root.querySelector('#imReportContainer');
        const place = root.querySelector('#imReportPlaceholder');
        if (cont) cont.style.display = 'none';
        if (place) place.style.display = 'block';
    });

    applyBtn.addEventListener('click', async () => {
        await loadItemMovementReport();
    });
}

async function renderItemMovementReport() {
    const body = document.getElementById('reportsBody');
    if (!body) return;

    const branchId = _ensureBranchSelected();
    if (!branchId) {
        body.innerHTML = '<div class="alert alert-warning"><i class="fas fa-exclamation-triangle"></i> Select a branch first (Settings → Branches → Set as Current).</div>';
        return;
    }

    body.innerHTML = getItemMovementReportHTML();
    setupItemMovementReportHandlers(body);
    window.__itemMovementReportRoot = body;
}

/** Render the same Item Movement report UI into an arbitrary container (e.g. Inventory → Item Movement). */
function renderItemMovementReportInto(container) {
    if (!container) return;
    container.innerHTML = getItemMovementReportHTML();
    setupItemMovementReportHandlers(container);
    window.__itemMovementReportRoot = container;
}
if (typeof window !== 'undefined') {
    window.renderItemMovementReportInto = renderItemMovementReportInto;
}

async function loadItemMovementReport() {
    const root = window.__itemMovementReportRoot || document;
    const branchId = (typeof _ensureBranchSelected === 'function' ? _ensureBranchSelected() : null) || (typeof getBranchIdForStock === 'function' ? getBranchIdForStock() : null);
    if (!branchId) {
        if (typeof showToast === 'function') showToast('Select a branch first.', 'warning');
        return;
    }

    const itemIdEl = root.querySelector('#imItemId');
    const itemId = itemIdEl && itemIdEl.value;
    const startEl = root.querySelector('#imStart');
    const endEl = root.querySelector('#imEnd');
    const summaryEl = root.querySelector('#imFiltersSummary');
    const containerEl = root.querySelector('#imReportContainer');
    const placeholderEl = root.querySelector('#imReportPlaceholder');
    const contentEl = root.querySelector('#imReportContent');

    if (!itemId || !startEl || !endEl) {
        if (typeof showToast === 'function') showToast('Please select an item and date range.', 'warning');
        return;
    }

    const sd = _parseDateInput(startEl.value);
    const ed = _parseDateInput(endEl.value);
    if (!sd || !ed) {
        if (typeof showToast === 'function') showToast('Please pick valid start and end dates.', 'warning');
        return;
    }
    if (sd > ed) {
        if (typeof showToast === 'function') showToast('Start date must be before or equal to end date.', 'warning');
        return;
    }

    const start = _fmtDateInput(sd);
    const end = _fmtDateInput(ed);
    if (summaryEl) summaryEl.textContent = 'Filters: from ' + start + ' to ' + end + ' Item ' + (itemMovementSelectedItem ? (itemMovementSelectedItem.sku || itemMovementSelectedItem.name) : itemId);
    if (contentEl) contentEl.innerHTML = '<div class="spinner" style="margin: 1rem auto;"></div>';
    if (containerEl) containerEl.style.display = 'block';
    if (placeholderEl) placeholderEl.style.display = 'none';

    try {
        if (!API || !API.reports || typeof API.reports.getItemMovement !== 'function') {
            throw new Error('Item Movement report API not available.');
        }
        const res = await API.reports.getItemMovement(itemId, start, end);
        lastItemMovementReportData = res;

        const opts = res.display_options || {};
        const showBatch = !!opts.show_batch_number;
        const showExpiry = !!opts.show_expiry_date;

        const th = (t, align) => '<th style="padding: 8px 10px; border: 1px solid #333; background: #f5f5f5; text-align: ' + (align || 'left') + '; font-weight: 600;">' + t + '</th>';
        let tableHeaders = th('Date') + th('Document type') + th('Reference') + th('Qty In', 'right') + th('Qty Out', 'right') + th('Run Bal', 'right');
        if (showBatch) tableHeaders += th('Batch');
        if (showExpiry) tableHeaders += th('Expiry');

        const rows = Array.isArray(res.rows) ? res.rows : [];
        const trs = rows.map(r => {
            const dateStr = r.date ? (typeof r.date === 'string' ? r.date.slice(0, 19).replace('T', ' ') : r.date) : '';
            const docType = (r.document_type != null && r.document_type !== undefined) ? String(r.document_type) : '';
            const ref = (r.reference != null && r.reference !== undefined) ? String(r.reference) : '';
            const qtyIn = (r.qty_in != null && r.qty_in !== undefined) ? Number(r.qty_in) : 0;
            const qtyOut = (r.qty_out != null && r.qty_out !== undefined) ? Number(r.qty_out) : 0;
            const runBal = (r.running_balance != null && r.running_balance !== undefined) ? Number(r.running_balance) : 0;
            const batch = showBatch ? (r.batch_number != null ? String(r.batch_number) : '') : '';
            const expiry = showExpiry ? (r.expiry_date != null ? String(r.expiry_date).slice(0, 10) : '') : '';
            const td = (v, align) => '<td style="padding: 6px 10px; border: 1px solid #ddd;">' + (align === 'right' ? '<span style="text-align:right;display:block;">' + v + '</span>' : _escapeHtml(v)) + '</td>';
            let row = td(dateStr) + td(docType) + td(ref) + td(String(qtyIn), 'right') + td(String(qtyOut), 'right') + td(String(runBal), 'right');
            if (showBatch) row += td(batch);
            if (showExpiry) row += td(expiry);
            return '<tr>' + row + '</tr>';
        }).join('');

        const reportHtml = `
            <div style="border-bottom: 2px solid #333; padding-bottom: 12px; margin-bottom: 12px;">
                <div style="font-weight: 700; font-size: 16px; color: #111;">${_escapeHtml(res.company_name || '')}</div>
                <div style="font-size: 13px; color: #444; margin-top: 4px;">${_escapeHtml(res.branch_name || '')}</div>
            </div>
            <div style="font-size: 18px; font-weight: 700; margin-bottom: 12px; text-align: center;">ITEM MOVEMENT REPORT</div>
            <div style="font-size: 12px; color: #444; margin-bottom: 8px;">from ${_escapeHtml(String(res.start_date || ''))} to ${_escapeHtml(String(res.end_date || ''))}</div>
            <div style="font-size: 12px; margin-bottom: 12px;">Item ${_escapeHtml(res.item_sku || '')} ${_escapeHtml(res.item_name || '')}</div>
            <table style="width: 100%; border-collapse: collapse; margin-top: 8px;">
                <thead><tr>${tableHeaders}</tr></thead>
                <tbody>${trs}</tbody>
            </table>
            <div style="margin-top: 12px; font-size: 12px; padding-top: 8px; border-top: 1px solid #ddd;">Opening balance: ${res.opening_balance != null ? res.opening_balance : 0} &nbsp;|&nbsp; Closing balance: ${res.closing_balance != null ? res.closing_balance : 0}</div>
        `;
        if (contentEl) contentEl.innerHTML = reportHtml;

        const printBtn = root.querySelector('#imPrintBtn');
        const pdfBtn = root.querySelector('#imPdfBtn');
        const csvBtn = root.querySelector('#imCsvBtn');
        const printArea = root.querySelector('#imReportContent');
        const printStyles = 'body{ font-family: "Segoe UI", Arial, sans-serif; font-size: 12px; padding: 16px; color: #222; } table { border-collapse: collapse; width: 100%; } th, td { border: 1px solid #ddd; padding: 6px 10px; } th { background: #f5f5f5; font-weight: 600; }';
        if (printBtn && printArea) {
            printBtn.onclick = () => {
                const win = window.open('', '_blank');
                win.document.write('<html><head><title>Item Movement Report</title><style>' + printStyles + '</style></head><body>' + printArea.innerHTML + '</body></html>');
                win.document.close();
                win.focus();
                setTimeout(() => { win.print(); win.close(); }, 250);
            };
        }
        if (pdfBtn && printArea) {
            pdfBtn.onclick = () => {
                const win = window.open('', '_blank');
                win.document.write('<html><head><title>Item Movement Report</title><style>' + printStyles + '</style></head><body>' + printArea.innerHTML + '</body></html>');
                win.document.close();
                win.focus();
                setTimeout(() => { win.print(); win.close(); }, 250);
            };
        }
        if (csvBtn) {
            csvBtn.onclick = () => downloadItemMovementCSV();
        }
    } catch (err) {
        console.error('[REPORTS] Item movement load failed:', err);
        if (contentEl) contentEl.innerHTML = '<p style="color: var(--danger-color);">Failed to load report. ' + (err && err.message ? err.message : '') + '</p>';
        if (typeof showToast === 'function') showToast('Failed to load Item Movement report', 'error');
    }
}

function downloadItemMovementCSV() {
    const res = lastItemMovementReportData;
    if (!res || !Array.isArray(res.rows) || res.rows.length === 0) {
        if (typeof showToast === 'function') showToast('Generate the report first, then download CSV.', 'warning');
        return;
    }
    const opts = res.display_options || {};
    const showBatch = !!opts.show_batch_number;
    const showExpiry = !!opts.show_expiry_date;
    const escapeCsv = (v) => {
        const s = v == null ? '' : String(v);
        if (/[",\n\r]/.test(s)) return '"' + s.replace(/"/g, '""') + '"';
        return s;
    };
    let headers = ['Date', 'Document type', 'Reference', 'Qty In', 'Qty Out', 'Running balance'];
    if (showBatch) headers.push('Batch');
    if (showExpiry) headers.push('Expiry');
    const lines = [headers.map(escapeCsv).join(',')];
    res.rows.forEach(r => {
        const dateStr = r.date ? (typeof r.date === 'string' ? r.date.slice(0, 19).replace('T', ' ') : r.date) : '';
        const row = [
            dateStr,
            (r.document_type != null ? String(r.document_type) : ''),
            (r.reference != null ? String(r.reference) : ''),
            (r.qty_in != null ? r.qty_in : 0),
            (r.qty_out != null ? r.qty_out : 0),
            (r.running_balance != null ? r.running_balance : 0)
        ];
        if (showBatch) row.push(r.batch_number != null ? String(r.batch_number) : '');
        if (showExpiry) row.push(r.expiry_date != null ? String(r.expiry_date).slice(0, 10) : '');
        lines.push(row.map(escapeCsv).join(','));
    });
    const csv = lines.join('\r\n');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'item-movement-report-' + (res.start_date || '') + '-to-' + (res.end_date || '') + '.csv';
    a.click();
    URL.revokeObjectURL(url);
    if (typeof showToast === 'function') showToast('CSV downloaded.', 'success');
}

async function loadGrossProfitReport() {
    const branchId = _ensureBranchSelected();
    if (!branchId) return;

    const startEl = document.getElementById('plStart');
    const endEl = document.getElementById('plEnd');
    const salesEl = document.getElementById('plSales');
    const cogsEl = document.getElementById('plCogs');
    const gpEl = document.getElementById('plGrossProfit');
    const metaEl = document.getElementById('plMeta');
    const breakdownEl = document.getElementById('plBreakdown');

    if (!startEl || !endEl || !salesEl || !cogsEl || !gpEl || !metaEl || !breakdownEl) return;

    const sd = _parseDateInput(startEl.value);
    const ed = _parseDateInput(endEl.value);
    if (!sd || !ed) {
        if (typeof showToast === 'function') showToast('Please pick a valid start and end date.', 'warning');
        return;
    }

    const start = _fmtDateInput(sd);
    const end = _fmtDateInput(ed);

    breakdownEl.innerHTML = '<div class="spinner" style="margin: 1rem auto;"></div>';
    salesEl.textContent = '—';
    cogsEl.textContent = '—';
    gpEl.textContent = '—';
    metaEl.textContent = 'Gross profit • Margin —';

    try {
        if (!API || !API.sales || typeof API.sales.getGrossProfit !== 'function') {
            throw new Error('Gross profit API not available');
        }
        const res = await API.sales.getGrossProfit(branchId, { start_date: start, end_date: end, include_breakdown: true });
        const sales = parseFloat(res.sales_exclusive || 0);
        const cogs = parseFloat(res.cogs || 0);
        const gp = parseFloat(res.gross_profit || 0);
        const margin = parseFloat(res.margin_percent || 0);

        salesEl.textContent = (typeof formatCurrency === 'function') ? formatCurrency(sales) : String(sales);
        cogsEl.textContent = (typeof formatCurrency === 'function') ? formatCurrency(cogs) : String(cogs);
        gpEl.textContent = (typeof formatCurrency === 'function') ? formatCurrency(gp) : String(gp);
        metaEl.textContent = `Gross profit • Margin ${margin.toFixed(1)}%`;

        const rows = Array.isArray(res.breakdown) ? res.breakdown : [];
        if (!rows.length) {
            breakdownEl.innerHTML = '<p style="color: var(--text-secondary);">No transactions in this date range.</p>';
            return;
        }

        const tr = rows.map(r => {
            const d = (r.date || '').slice(0, 10);
            const s = parseFloat(r.sales_exclusive || 0);
            const c = parseFloat(r.cogs || 0);
            const g = parseFloat(r.gross_profit || 0);
            const m = parseFloat(r.margin_percent || 0);
            const fc = (v) => (typeof formatCurrency === 'function') ? formatCurrency(v) : String(v);
            return `
                <tr>
                    <td style="padding: 0.5rem; border-bottom: 1px solid var(--border-color);">${d}</td>
                    <td style="padding: 0.5rem; border-bottom: 1px solid var(--border-color); text-align:right;">${fc(s)}</td>
                    <td style="padding: 0.5rem; border-bottom: 1px solid var(--border-color); text-align:right;">${fc(c)}</td>
                    <td style="padding: 0.5rem; border-bottom: 1px solid var(--border-color); text-align:right;">${fc(g)}</td>
                    <td style="padding: 0.5rem; border-bottom: 1px solid var(--border-color); text-align:right;">${m.toFixed(1)}%</td>
                </tr>
            `;
        }).join('');

        breakdownEl.innerHTML = `
            <div style="overflow:auto;">
                <table style="width:100%; border-collapse: collapse;">
                    <thead>
                        <tr>
                            <th style="padding: 0.5rem; border-bottom: 2px solid var(--border-color); text-align:left;">Date</th>
                            <th style="padding: 0.5rem; border-bottom: 2px solid var(--border-color); text-align:right;">Sales (excl)</th>
                            <th style="padding: 0.5rem; border-bottom: 2px solid var(--border-color); text-align:right;">COGS</th>
                            <th style="padding: 0.5rem; border-bottom: 2px solid var(--border-color); text-align:right;">Gross profit</th>
                            <th style="padding: 0.5rem; border-bottom: 2px solid var(--border-color); text-align:right;">Margin</th>
                        </tr>
                    </thead>
                    <tbody>${tr}</tbody>
                </table>
            </div>
        `;
    } catch (err) {
        console.error('[REPORTS] Gross profit load failed:', err);
        breakdownEl.innerHTML = `<p style="color: var(--danger-color);">Failed to load report. ${(err && err.message) ? err.message : ''}</p>`;
        if (typeof showToast === 'function') showToast('Failed to load gross profit report', 'error');
    }
}

// Export
if (typeof window !== 'undefined') {
    window.loadReports = loadReports;
    window.loadReportsSubPage = loadReportsSubPage;
}

