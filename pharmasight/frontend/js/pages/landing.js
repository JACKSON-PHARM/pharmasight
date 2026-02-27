/**
 * Landing Page - Lightweight home with minimal queries.
 * Shows welcome (user name, not email), current branch, quick stats, quick item search, and navigation tiles.
 */

/** Prefer full name or username over email for display (aligned with status bar). */
async function getLandingDisplayName(user) {
    if (!user) return 'User';
    if (user.full_name && user.full_name.trim()) return user.full_name.trim();
    if (user.username && user.username.trim()) return user.username.trim();
    if (user.user_metadata) {
        if (user.user_metadata.full_name && user.user_metadata.full_name.trim()) return user.user_metadata.full_name.trim();
        if (user.user_metadata.username && user.user_metadata.username.trim()) return user.user_metadata.username.trim();
    }
    const fromStorage = typeof localStorage !== 'undefined' && localStorage.getItem('pharmasight_username');
    if (fromStorage && fromStorage.trim()) return fromStorage.trim();
    if (typeof window.resolveUserDisplayName === 'function') {
        try { return await window.resolveUserDisplayName(user) || user.email || 'User'; } catch (_) {}
    }
    return user.email || 'User';
}

function getBranchIdForLanding() {
    const branch = typeof BranchContext !== 'undefined' && BranchContext.getBranch ? BranchContext.getBranch() : null;
    if (branch && branch.id) return branch.id;
    if (typeof CONFIG !== 'undefined' && CONFIG.BRANCH_ID) return CONFIG.BRANCH_ID;
    try {
        const saved = localStorage.getItem('pharmasight_config');
        if (saved) {
            const c = JSON.parse(saved);
            if (c.BRANCH_ID) return c.BRANCH_ID;
        }
    } catch (e) { /* ignore */ }
    return null;
}

async function loadLanding() {
    const active = (typeof currentPage !== 'undefined' ? currentPage : (window.currentPage || ''));
    if (active !== 'landing') return;
    const page = document.getElementById('landing');
    if (!page) return;

    const user = typeof AuthBootstrap !== 'undefined' && AuthBootstrap.getCurrentUser ? AuthBootstrap.getCurrentUser() : null;
    const displayName = await getLandingDisplayName(user);
    const branch = typeof BranchContext !== 'undefined' && BranchContext.getBranch ? BranchContext.getBranch() : null;
    const branchName = branch ? (branch.name || 'This branch') : 'No branch selected';

    const welcomeEl = document.getElementById('landingWelcome');
    const branchEl = document.getElementById('landingBranch');
    if (welcomeEl) welcomeEl.textContent = 'Welcome, ' + (displayName || 'User');
    if (branchEl) branchEl.textContent = branchName;

    // Optional: one lightweight call for "pending orders today" (single count) - only if we have branch + company
    const branchId = getBranchIdForLanding();
    const pendingEl = document.getElementById('landingPendingOrders');
    if (pendingEl && branchId && typeof CONFIG !== 'undefined' && CONFIG.COMPANY_ID && typeof API !== 'undefined' && API.orderBook && typeof API.orderBook.getTodaySummary === 'function') {
        try {
            const summary = await API.orderBook.getTodaySummary(branchId, CONFIG.COMPANY_ID, 0);
            const count = (summary && summary.pending_count != null) ? summary.pending_count : 0;
            pendingEl.textContent = count;
        } catch (e) {
            pendingEl.textContent = '—';
        }
    } else if (pendingEl) {
        pendingEl.textContent = '—';
    }

    bindLandingQuickSearch();
}

let landingSearchTimeout = null;
let landingSelectedItem = null;
let landingSearchLastResults = [];

function bindLandingQuickSearch() {
    const input = document.getElementById('landingItemSearch');
    const dropdown = document.getElementById('landingItemSearchDropdown');
    const row = document.getElementById('landingSelectedItemRow');
    const nameEl = document.getElementById('landingSelectedItemName');
    const btnInvoice = document.getElementById('landingCreateInvoiceBtn');
    const btnQuotation = document.getElementById('landingCreateQuotationBtn');
    const btnOrder = document.getElementById('landingCreateOrderBtn');
    if (!input || !dropdown || !row) return;

    function hideDropdown() {
        dropdown.style.display = 'none';
        dropdown.innerHTML = '';
    }

    function showSelectedRow(item) {
        landingSelectedItem = item;
        if (nameEl) nameEl.textContent = item.name || item.item_name || 'Item';
        row.style.display = 'block';
    }

    function clearSelection() {
        landingSelectedItem = null;
        row.style.display = 'none';
        if (input) input.value = '';
    }

    input.addEventListener('input', function () {
        const q = (this.value || '').trim();
        if (landingSearchTimeout) clearTimeout(landingSearchTimeout);
        hideDropdown();
        if (q.length < 2) {
            clearSelection();
            return;
        }
        landingSearchTimeout = setTimeout(async function () {
            try {
                if (typeof CONFIG === 'undefined' || !CONFIG.COMPANY_ID || typeof API === 'undefined' || !API.items || !API.items.search) {
                    dropdown.innerHTML = '<div style="padding: 8px; color: var(--text-secondary);">Search not available.</div>';
                    dropdown.style.display = 'block';
                    return;
                }
                const branchId = getBranchIdForLanding() || (typeof CONFIG !== 'undefined' ? CONFIG.BRANCH_ID : null);
                const items = await API.items.search(q, CONFIG.COMPANY_ID, 15, branchId, true);
                landingSearchLastResults = items || [];
                if (!items || items.length === 0) {
                    dropdown.innerHTML = '<div style="padding: 8px; color: var(--text-secondary);">No items found.</div>';
                } else {
                    dropdown.innerHTML = items.map(function (it, idx) {
                        const name = (it.name || it.item_name || '').trim() || '—';
                        const sku = (it.sku || it.item_code || '').trim();
                        return '<div class="landing-search-hit" data-idx="' + idx + '" style="padding: 8px 12px; cursor: pointer; border-bottom: 1px solid var(--border-color, #eee);" onmouseover="this.style.background=\'#f0f4ff\'" onmouseout="this.style.background=\'\'">' + (typeof escapeHtml === 'function' ? escapeHtml(name) : name) + (sku ? ' <span style="color: var(--text-secondary);">(' + (typeof escapeHtml === 'function' ? escapeHtml(sku) : sku) + ')</span>' : '') + '</div>';
                    }).join('');
                }
                dropdown.style.display = 'block';
            } catch (e) {
                dropdown.innerHTML = '<div style="padding: 8px; color: var(--danger-color);">Search failed.</div>';
                dropdown.style.display = 'block';
            }
        }, 280);
    });

    input.addEventListener('blur', function () {
        setTimeout(hideDropdown, 180);
    });

    dropdown.addEventListener('click', function (e) {
        const hit = e.target.closest('.landing-search-hit');
        if (!hit || hit.dataset.idx === undefined) return;
        const idx = parseInt(hit.dataset.idx, 10);
        const item = landingSearchLastResults[idx];
        if (!item) return;
        input.value = (item.name || item.item_name || '') + (item.sku || item.item_code ? ' (' + (item.sku || item.item_code) + ')' : '');
        hideDropdown();
        showSelectedRow(item);
    });

    function itemToTableShape(item) {
        return {
            item_id: item.id || item.item_id,
            item_name: item.name || item.item_name,
            item_sku: item.sku || item.item_code,
            item_code: item.item_code || item.sku,
            unit_name: item.base_unit || item.unit_name || 'Unit',
            quantity: 1,
            unit_price: item.price != null ? item.price : (item.unit_price != null ? item.unit_price : 0),
            discount_percent: 0,
            discount_amount: 0,
            tax_percent: item.vat_rate != null ? item.vat_rate : 0
        };
    }

    function goToDocument(type, item) {
        const payload = { type: type, item: itemToTableShape(item) };
        try {
            sessionStorage.setItem('pendingLandingDocument', JSON.stringify(payload));
        } catch (_) {}
        if (type === 'sales_invoice' || type === 'quotation') {
            window.location.hash = '#sales';
        } else if (type === 'purchase_order') {
            window.location.hash = '#purchases';
        }
        if (typeof showToast === 'function') showToast('Opening document…', 'info');
    }

    if (btnInvoice) btnInvoice.addEventListener('click', function () {
        if (!landingSelectedItem) return;
        goToDocument('sales_invoice', landingSelectedItem);
    });
    if (btnQuotation) btnQuotation.addEventListener('click', function () {
        if (!landingSelectedItem) return;
        goToDocument('quotation', landingSelectedItem);
    });
    if (btnOrder) btnOrder.addEventListener('click', function () {
        if (!landingSelectedItem) return;
        goToDocument('purchase_order', landingSelectedItem);
    });
}

window.loadLanding = loadLanding;
window.getLandingDisplayName = getLandingDisplayName;
