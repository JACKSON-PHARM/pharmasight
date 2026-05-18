/**
 * Shared UI helpers for Finance Operations Console.
 */
(function (global) {
    const L = () => global.FinanceOpsLabels || {};

    function escapeHtml(text) {
        if (text == null) return '';
        return String(text)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function localDateStr(d) {
        const x = d ? new Date(d) : new Date();
        const yyyy = x.getFullYear();
        const mm = String(x.getMonth() + 1).padStart(2, '0');
        const dd = String(x.getDate()).padStart(2, '0');
        return `${yyyy}-${mm}-${dd}`;
    }

    function defaultDateRange() {
        const today = new Date();
        return {
            since: localDateStr(new Date(today.getFullYear(), today.getMonth(), 1)),
            until: localDateStr(today),
        };
    }

    function fmtMoney(v, currency) {
        const n = parseFloat(v || 0);
        const cur = currency || 'KES';
        if (typeof formatCurrency === 'function') return formatCurrency(n, cur);
        return `${cur} ${n.toLocaleString('en-KE', { minimumFractionDigits: 2 })}`;
    }

    function fmtDateTime(iso) {
        if (!iso) return '—';
        try {
            return new Date(iso).toLocaleString();
        } catch (_) {
            return String(iso);
        }
    }

    function migrationBannerHtml() {
        return `
            <div class="finance-ops-banner" style="margin-bottom:1rem;padding:0.75rem 1rem;border-radius:8px;background:var(--surface-alt, rgba(59,130,246,0.08));border:1px solid var(--border-color);font-size:0.9rem;line-height:1.45;">
                <strong>Operational financial intelligence</strong> — business meaning from governed lineage (liquidity, recovery, confidence).
                Operational records remain authoritative; intelligence is explainable and traceable to lineage — not a stored ledger.
                <span style="display:block;margin-top:0.35rem;opacity:0.85;">Legacy Cashbook stays under Compatibility until your branch reaches projection-trusted maturity.</span>
            </div>`;
    }

    function pageShell(title, icon, bodyHtml) {
        return `
            ${migrationBannerHtml()}
            <div class="card">
                <div class="card-header" style="display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:0.5rem;">
                    <h3 class="card-title" style="margin:0;"><i class="fas ${icon}"></i> ${escapeHtml(title)}</h3>
                </div>
                <div class="card-body">${bodyHtml}</div>
            </div>`;
    }

    async function populateBranchSelect(selectEl, selectedId) {
        if (!selectEl) return;
        const current = selectedId || (typeof CONFIG !== 'undefined' && CONFIG.BRANCH_ID) || '';
        selectEl.innerHTML = `<option value="${escapeHtml(current)}">Current branch</option>`;
        try {
            if (!API || !API.branch || !CONFIG || !CONFIG.COMPANY_ID) return;
            const list = await API.branch.listAll(CONFIG.COMPANY_ID);
            const branches = Array.isArray(list) ? list : [];
            selectEl.innerHTML = branches
                .map((b) => {
                    const id = b.id;
                    const name = (b.name || '').trim();
                    const label = name ? name + (b.is_hq ? ' (HQ)' : '') : `Branch (${String(id).slice(0, 6)})`;
                    const sel = id === current ? ' selected' : '';
                    return `<option value="${escapeHtml(id)}"${sel}>${escapeHtml(label)}</option>`;
                })
                .join('');
            if (current && !branches.some((b) => b.id === current)) {
                selectEl.innerHTML =
                    `<option value="${escapeHtml(current)}" selected>Current branch</option>` + selectEl.innerHTML;
            }
        } catch (e) {
            console.warn('[FinanceOps] branch list failed', e);
        }
    }

    function filterToolbarHtml(opts) {
        const { since, until, showEventType, eventTypeOptions, showBranch } = opts;
        let eventSelect = '';
        if (showEventType && eventTypeOptions) {
            const optsHtml = eventTypeOptions
                .map(
                    (o) =>
                        `<option value="${escapeHtml(o.value)}"${o.value === opts.selectedEventType ? ' selected' : ''}>${escapeHtml(o.label)}</option>`
                )
                .join('');
            eventSelect = `
                <div class="form-group" style="margin:0;min-width:200px;">
                    <label class="form-label">Activity type</label>
                    <select class="form-select" id="foEventType">
                        <option value="">All types</option>
                        ${optsHtml}
                    </select>
                </div>`;
        }
        const branchBlock = showBranch !== false
            ? `
                <div class="form-group" style="margin:0;min-width:200px;">
                    <label class="form-label">Branch</label>
                    <select class="form-select" id="foBranch">${escapeHtml(CONFIG.BRANCH_ID || '')}</select>
                </div>`
            : '';
        return `
            <div style="display:flex;flex-wrap:wrap;gap:0.75rem;align-items:end;margin-bottom:1rem;">
                ${branchBlock}
                <div class="form-group" style="margin:0;">
                    <label class="form-label">From</label>
                    <input type="date" class="form-input" id="foDateFrom" value="${escapeHtml(since)}">
                </div>
                <div class="form-group" style="margin:0;">
                    <label class="form-label">To</label>
                    <input type="date" class="form-input" id="foDateTo" value="${escapeHtml(until)}">
                </div>
                ${eventSelect}
                <button type="button" class="btn btn-primary" id="foRefreshBtn"><i class="fas fa-sync-alt"></i> Refresh</button>
            </div>`;
    }

    function readFilterParams() {
        const branchEl = document.getElementById('foBranch');
        const fromEl = document.getElementById('foDateFrom');
        const toEl = document.getElementById('foDateTo');
        const typeEl = document.getElementById('foEventType');
        return {
            branch_id: branchEl && branchEl.value ? branchEl.value : CONFIG.BRANCH_ID,
            since: fromEl ? fromEl.value : null,
            until: toEl ? toEl.value : null,
            event_type: typeEl ? typeEl.value : null,
        };
    }

    function bindRefresh(handler) {
        const btn = document.getElementById('foRefreshBtn');
        if (btn) btn.onclick = () => handler();
    }

    function showError(el, err) {
        if (!el) return;
        const msg = (err && err.message) || String(err);
        el.innerHTML = `<p style="color:var(--danger-color);margin:0;">${escapeHtml(msg)}</p>`;
    }

    function statusPill(text, tone) {
        const colors = {
            ok: 'var(--success-color, #16a34a)',
            warn: 'var(--warning-color, #ca8a04)',
            err: 'var(--danger-color, #dc2626)',
            muted: 'var(--text-muted, #6b7280)',
            info: 'var(--primary-color, #2563eb)',
        };
        const c = colors[tone] || colors.muted;
        return `<span style="display:inline-block;padding:0.15rem 0.5rem;border-radius:999px;font-size:0.8rem;border:1px solid ${c};color:${c};">${escapeHtml(text)}</span>`;
    }

    function renderKeyValueTable(obj, keyPairs) {
        const rows = (keyPairs || [])
            .filter((pair) => pair && pair[1] != null && obj[pair[1]] != null && obj[pair[1]] !== '')
            .map(
                ([label, key]) =>
                    `<tr><td style="padding:0.4rem 0.75rem 0.4rem 0;color:var(--text-muted);">${escapeHtml(label)}</td><td style="padding:0.4rem 0;">${escapeHtml(String(obj[key]))}</td></tr>`
            )
            .join('');
        if (!rows) return '<p style="opacity:0.7;margin:0;">No summary fields.</p>';
        return `<table style="width:100%;border-collapse:collapse;">${rows}</table>`;
    }

    function summarizeProjectionData(data) {
        if (!data || typeof data !== 'object') return [];
        const skip = new Set(['contract', 'freshness', 'projection_id', 'derived', 'authoritative']);
        const rows = [];
        Object.keys(data).forEach((k) => {
            if (skip.has(k)) return;
            const v = data[k];
            if (v && typeof v === 'object' && !Array.isArray(v)) {
                Object.keys(v).forEach((sk) => {
                    rows.push([`${k}: ${sk}`, `${k}.${sk}`, v[sk]]);
                });
            } else {
                const label = k.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
                rows.push([label, k, v]);
            }
        });
        return rows;
    }

    global.FinanceOps = {
        escapeHtml,
        localDateStr,
        defaultDateRange,
        fmtMoney,
        fmtDateTime,
        migrationBannerHtml,
        pageShell,
        populateBranchSelect,
        filterToolbarHtml,
        readFilterParams,
        bindRefresh,
        showError,
        statusPill,
        renderKeyValueTable,
        summarizeProjectionData,
        labels: () => L(),
    };
})(typeof window !== 'undefined' ? window : global);
