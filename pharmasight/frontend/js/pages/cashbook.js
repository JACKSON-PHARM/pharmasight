// Cashbook page: unified money movement tracking (expenses + supplier payments).

function _localDateStr(d) {
    const x = d ? new Date(d) : new Date();
    const yyyy = x.getFullYear();
    const mm = String(x.getMonth() + 1).padStart(2, '0');
    const dd = String(x.getDate()).padStart(2, '0');
    return `${yyyy}-${mm}-${dd}`;
}

function _fmtMoney(v) {
    const n = parseFloat(v || 0);
    return (typeof formatCurrency === 'function')
        ? formatCurrency(n)
        : ('KES ' + n.toLocaleString('en-KE', { minimumFractionDigits: 2 }));
}

function _sourceLabel(sourceType) {
    const s = (sourceType || '').toLowerCase();
    if (s === 'expense') return 'Expense';
    if (s === 'supplier_payment') return 'Supplier Payment';
    if (s === 'sale') return 'Sale';
    return sourceType || '—';
}

function _typeLabel(t) {
    const x = (t || '').toLowerCase();
    if (x === 'inflow') return 'Inflow';
    if (x === 'outflow') return 'Outflow';
    return t || '—';
}

async function loadCashbook() {
    const page = document.getElementById('cashbook');
    if (!page) return;

    const today = new Date();
    const start = _localDateStr(new Date(today.getFullYear(), today.getMonth(), 1));
    const end = _localDateStr(today);

    page.innerHTML = `
        <div class="card">
            <div class="card-header">
                <h3 class="card-title"><i class="fas fa-cash-register"></i> Cashbook</h3>
            </div>
            <div class="card-body" id="cashbookBody">
                <div style="display:flex; flex-wrap:wrap; gap:0.75rem; align-items:end; margin-bottom: 1rem;">
                    <div class="form-group" style="margin:0;">
                        <label class="form-label">From</label>
                        <input type="date" class="form-input" id="cbDateFrom" value="${start}">
                    </div>
                    <div class="form-group" style="margin:0;">
                        <label class="form-label">To</label>
                        <input type="date" class="form-input" id="cbDateTo" value="${end}">
                    </div>
                    <div class="form-group" style="min-width: 180px; margin:0;">
                        <label class="form-label">Payment Mode</label>
                        <select class="form-select" id="cbPaymentMode">
                            <option value="">All</option>
                            <option value="cash">Cash</option>
                            <option value="mpesa">M-Pesa</option>
                            <option value="bank">Bank</option>
                        </select>
                    </div>
                    <div class="form-group" style="min-width: 200px; margin:0;">
                        <label class="form-label">Source Type</label>
                        <select class="form-select" id="cbSourceType">
                            <option value="">All</option>
                            <option value="expense">Expense</option>
                            <option value="supplier_payment">Supplier Payment</option>
                            <option value="sale">Sale</option>
                        </select>
                    </div>
                    <div class="form-group" style="min-width: 220px; margin:0; opacity: 0.95;">
                        <label class="form-label">Branch</label>
                        <select class="form-select" id="cbBranch">
                            <option value="${escapeHtml(CONFIG.BRANCH_ID || '')}">Loading branches…</option>
                        </select>
                    </div>
                    <div style="margin-left:auto;">
                        <button class="btn btn-primary" id="cbApplyBtn"><i class="fas fa-filter"></i> Apply</button>
                        <button class="btn btn-secondary" id="cbBackfillBtn" title="Populate cashbook from existing records (idempotent)."><i class="fas fa-rotate"></i> Backfill</button>
                    </div>
                </div>

                <div id="cbSummaryWrap" style="margin-bottom: 1rem;"></div>
                <div id="cbTableWrap"></div>
            </div>
        </div>
    `;

    document.getElementById('cbApplyBtn')?.addEventListener('click', () => void renderCashbook());
    document.getElementById('cbBackfillBtn')?.addEventListener('click', async () => {
        const df = document.getElementById('cbDateFrom')?.value || null;
        const dt = document.getElementById('cbDateTo')?.value || null;
        const branchId = document.getElementById('cbBranch')?.value || CONFIG.BRANCH_ID;
        if (!df || !dt) {
            showToast && showToast('Select start/end dates first.', 'warning');
            return;
        }
        try {
            showToast && showToast('Backfilling cashbook entries…', 'info');
            await API.cashbook.backfill({
                branch_id: branchId,
                start_date: df,
                end_date: dt,
            });
            showToast && showToast('Backfill complete.', 'success');
            await renderCashbook();
        } catch (e) {
            console.error('Cashbook backfill failed:', e);
            showToast && showToast((e && e.message) ? e.message : 'Backfill failed', 'error');
        }
    });
    document.getElementById('cbBranch')?.addEventListener('change', () => {
        // Keep "Apply" as the explicit trigger, but ensure UI feels responsive (and also
        // avoids too many requests when user is just browsing options).
        // renderCashbook will be called on Apply.
    });

    // Populate branches so the dropdown shows human-readable names.
    await loadCashbookBranches();
    await renderCashbook();
}

async function loadCashbookBranches() {
    const sel = document.getElementById('cbBranch');
    if (!sel) return;

    const currentBranchId = CONFIG.BRANCH_ID;
    if (!CONFIG.COMPANY_ID) {
        sel.disabled = true;
        sel.innerHTML = `<option value="${escapeHtml(currentBranchId || '')}">Current Branch</option>`;
        return;
    }

    let branches = [];
    try {
        branches = await API.branch.list(CONFIG.COMPANY_ID);
    } catch (e) {
        branches = [];
    }

    branches = Array.isArray(branches) ? branches : [];
    sel.disabled = false;

    if (!branches.length) {
        sel.innerHTML = `<option value="${escapeHtml(currentBranchId || '')}">Current Branch</option>`;
        return;
    }

    const optionsHtml = branches.map(b => {
        const id = b.id;
        const name = (b.name || '').trim();
        const label = name ? name : `Branch (${String(id).slice(0, 6)})`;
        const suffix = b.is_hq ? ' (HQ)' : '';
        const isSelected = currentBranchId && String(id) === String(currentBranchId);
        return `<option value="${escapeHtml(id)}"${isSelected ? ' selected' : ''}>${escapeHtml(label + suffix)}</option>`;
    }).join('');

    sel.innerHTML = optionsHtml;
}

async function renderCashbook() {
    const body = document.getElementById('cashbookBody');
    const wrapSummary = document.getElementById('cbSummaryWrap');
    const wrapTable = document.getElementById('cbTableWrap');
    if (!body || !wrapSummary || !wrapTable) return;

    const df = document.getElementById('cbDateFrom')?.value || null;
    const dt = document.getElementById('cbDateTo')?.value || null;
    const pm = document.getElementById('cbPaymentMode')?.value || '';
    const st = document.getElementById('cbSourceType')?.value || '';
    const branchId = document.getElementById('cbBranch')?.value || CONFIG.BRANCH_ID;

    wrapTable.innerHTML = '<div class="spinner" style="margin: 1rem auto;"></div>';

    const params = {
        branch_id: branchId,
        date_from: df,
        date_to: dt,
        payment_mode: pm || null,
        source_type: st || null,
        limit: 500,
        offset: 0,
    };

    const summaryParams = {
        ...params,
        start_date: df,
        end_date: dt,
    };
    delete summaryParams.limit;
    delete summaryParams.offset;
    delete summaryParams.date_from;
    delete summaryParams.date_to;
    summaryParams.payment_mode = pm || null;
    summaryParams.source_type = st || null;

    try {
        const [list, summary] = await Promise.all([
            API.cashbook.list(params),
            API.cashbook.summary(summaryParams),
        ]);

        const entries = Array.isArray(list) ? list : [];
        const s = summary || {};

        wrapSummary.innerHTML = `
            <div style="display:flex; flex-wrap:wrap; gap:0.75rem; margin-bottom: 1rem;">
                <div class="stat-card" style="flex: 1; min-width: 200px;">
                    <div class="stat-icon"><i class="fas fa-arrow-down"></i></div>
                    <div class="stat-info">
                        <h3>${_fmtMoney(s.total_inflow)}</h3>
                        <p>Total Inflow</p>
                    </div>
                </div>
                <div class="stat-card" style="flex: 1; min-width: 200px;">
                    <div class="stat-icon"><i class="fas fa-arrow-up"></i></div>
                    <div class="stat-info">
                        <h3>${_fmtMoney(s.total_outflow)}</h3>
                        <p>Total Outflow</p>
                    </div>
                </div>
                <div class="stat-card" style="flex: 1; min-width: 200px;">
                    <div class="stat-icon"><i class="fas fa-balance-scale"></i></div>
                    <div class="stat-info">
                        <h3>${_fmtMoney(s.net_cashflow)}</h3>
                        <p>Net Cashflow</p>
                    </div>
                </div>
            </div>
            <div class="table-container" style="overflow-x:auto;">
                <table style="width:100%; border-collapse: collapse;">
                    <thead>
                        <tr>
                            <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align:left;">Date</th>
                            <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align:right;">Inflow</th>
                            <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align:right;">Outflow</th>
                            <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align:right;">Net</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${(Array.isArray(s.breakdown) ? s.breakdown : []).map(r => `
                            <tr>
                                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">${escapeHtml((r.date || '').slice(0, 10))}</td>
                                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color); text-align:right;">${_fmtMoney(r.total_inflow)}</td>
                                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color); text-align:right;">${_fmtMoney(r.total_outflow)}</td>
                                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color); text-align:right;">${_fmtMoney(r.net_cashflow)}</td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            </div>
        `;

        if (!entries.length) {
            wrapTable.innerHTML = (window.EmptyStateWatermark && window.EmptyStateWatermark.render)
                ? window.EmptyStateWatermark.render({ title: 'No cashbook entries', description: 'Cashbook entries will appear when expenses are approved and when supplier payments are recorded.' })
                : '<p style="color: var(--text-secondary);">No cashbook entries found.</p>';
            return;
        }

        wrapTable.innerHTML = `
            <div class="table-container" style="overflow-x:auto;">
                <table style="width:100%; border-collapse: collapse;">
                    <thead>
                        <tr>
                            <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align:left;">Date</th>
                            <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align:left;">Type</th>
                            <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align:right;">Amount</th>
                            <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align:left;">Payment Mode</th>
                            <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align:left;">Source</th>
                            <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align:left;">Reference</th>
                            <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align:left;">Description</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${entries.map(e => {
                            const amount = (e.amount != null) ? _fmtMoney(e.amount) : '—';
                            const mode = (e.payment_mode || '').toLowerCase() || '—';
                            const modeLabel = mode === 'mpesa' ? 'M-Pesa' : (mode === 'bank' ? 'Bank' : (mode === 'cash' ? 'Cash' : mode));
                            return `
                                <tr>
                                    <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">${escapeHtml((e.date || '').slice(0, 10))}</td>
                                    <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">${escapeHtml(_typeLabel(e.type))}</td>
                                    <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color); text-align:right;">${amount}</td>
                                    <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">${escapeHtml(modeLabel)}</td>
                                    <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">${escapeHtml(_sourceLabel(e.source_type))}</td>
                                    <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">${escapeHtml(e.reference_number || '—')}</td>
                                    <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">${escapeHtml(e.description || '—')}</td>
                                </tr>
                            `;
                        }).join('')}
                    </tbody>
                </table>
            </div>
        `;
    } catch (err) {
        wrapTable.innerHTML = `<p style="color: var(--danger-color); margin: 0.75rem 0;">Failed to load cashbook: ${escapeHtml((err && err.message) ? err.message : String(err))}</p>`;
    }
}

window.loadCashbook = loadCashbook;

