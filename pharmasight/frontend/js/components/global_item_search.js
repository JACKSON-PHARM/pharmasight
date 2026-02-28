/**
 * Global Item Search - Sticky bar on all app pages.
 * Search items with dropdown showing stock & selling price; on select show icon actions:
 * Sales invoice (first), Quotation, Purchase order. Creates draft and navigates.
 */
(function () {
    'use strict';

    const DEBOUNCE_MS = 320;
    const SEARCH_MIN_LEN = 2;
    const SEARCH_LIMIT = 15;

    let searchTimeout = null;
    let selectedItem = null;
    let lastResults = [];
    let currentSearchQuery = '';
    let searchAbortController = null;

    function getBranchId() {
        if (typeof BranchContext !== 'undefined' && BranchContext.getBranch) {
            const b = BranchContext.getBranch();
            if (b && b.id) return b.id;
        }
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

    function esc(s) {
        if (s == null || s === '') return '';
        const d = document.createElement('div');
        d.textContent = s;
        return d.innerHTML;
    }

    function formatPrice(val) {
        if (typeof window.formatCurrency === 'function') return window.formatCurrency(val);
        return (Number(val) || 0).toFixed(2);
    }

    function hideDropdown() {
        const dropdown = document.getElementById('globalItemSearchDropdown');
        if (dropdown) {
            dropdown.style.display = 'none';
            dropdown.innerHTML = '';
            dropdown.setAttribute('aria-hidden', 'true');
        }
    }

    function showDropdownLoading() {
        const dropdown = document.getElementById('globalItemSearchDropdown');
        if (!dropdown) return;
        dropdown.innerHTML = '<div class="global-item-search-hit global-item-search-loading"><i class="fas fa-spinner fa-spin"></i> Searching...</div>';
        dropdown.style.display = 'block';
        dropdown.setAttribute('aria-hidden', 'false');
    }

    function showSelectedRow(item) {
        selectedItem = item;
        const row = document.getElementById('globalSelectedItemRow');
        const nameEl = document.getElementById('globalSelectedItemName');
        const metaEl = document.getElementById('globalSelectedItemMeta');
        if (!row || !nameEl || !metaEl) return;
        nameEl.textContent = item.name || item.item_name || 'Item';
        const stockStr = item.stock_display != null ? item.stock_display : (item.current_stock != null ? String(item.current_stock) : '—');
        const priceStr = formatPrice(item.sale_price != null ? item.sale_price : item.price);
        metaEl.textContent = 'Stock: ' + stockStr + ' · Price: ' + priceStr;
        row.style.display = 'flex';
    }

    function clearSelection() {
        selectedItem = null;
        const row = document.getElementById('globalSelectedItemRow');
        if (row) row.style.display = 'none';
        /* Do not clear input.value here – that was wiping the text as the user typed (when q.length < 2). */
    }

    function itemToTableShape(item) {
        const price = item.sale_price != null ? item.sale_price : (item.price != null ? item.price : 0);
        return {
            item_id: item.id || item.item_id,
            item_name: item.name || item.item_name,
            item_sku: item.sku || item.item_code,
            item_code: item.item_code || item.sku,
            unit_name: item.base_unit || item.unit_name || 'Unit',
            quantity: 1,
            unit_price: price,
            discount_percent: 0,
            discount_amount: 0,
            tax_percent: item.vat_rate != null ? item.vat_rate : 0
        };
    }

    function goToDocument(type, item) {
        const payload = { type: type, item: itemToTableShape(item), prefillSearchOnly: true };
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

    function runSearch(q) {
        if (typeof CONFIG === 'undefined' || !CONFIG.COMPANY_ID || typeof API === 'undefined' || !API.items || !API.items.search) {
            const dropdown = document.getElementById('globalItemSearchDropdown');
            if (dropdown) {
                dropdown.innerHTML = '<div class="global-item-search-hit" style="color: var(--text-secondary);">Search not available.</div>';
                dropdown.style.display = 'block';
                dropdown.setAttribute('aria-hidden', 'false');
            }
            return;
        }
        if (searchAbortController) {
            searchAbortController.abort();
        }
        searchAbortController = new AbortController();
        currentSearchQuery = q;
        showDropdownLoading();
        const branchId = getBranchId() || (typeof CONFIG !== 'undefined' ? CONFIG.BRANCH_ID : null);
        var requestSignal = searchAbortController.signal;
        API.items.search(q, CONFIG.COMPANY_ID, SEARCH_LIMIT, branchId, true, null, { signal: requestSignal })
            .then(function (items) {
                if (currentSearchQuery !== q) return;
                lastResults = items || [];
                const dropdown = document.getElementById('globalItemSearchDropdown');
                if (!dropdown) return;
                if (!items || items.length === 0) {
                    dropdown.innerHTML = '<div class="global-item-search-hit" style="color: var(--text-secondary);">No items found.</div>';
                } else {
                    dropdown.innerHTML = items.map(function (it, idx) {
                        const name = (it.name || it.item_name || '').trim() || '—';
                        const sku = (it.sku || it.item_code || '').trim();
                        const stock = it.stock_display != null ? it.stock_display : (it.current_stock != null ? String(it.current_stock) : '—');
                        const price = formatPrice(it.sale_price != null ? it.sale_price : it.price);
                        return '<div class="global-item-search-hit" data-idx="' + idx + '">' +
                            '<span class="hit-name">' + esc(name) + '</span>' +
                            (sku ? ' <span class="hit-meta">(' + esc(sku) + ')</span>' : '') +
                            '<div class="hit-stock-price">Stock: ' + esc(stock) + ' · ' + price + '</div>' +
                            '</div>';
                    }).join('');
                }
                dropdown.style.display = 'block';
                dropdown.setAttribute('aria-hidden', 'false');
            })
            .catch(function (err) {
                if (err && err.name === 'AbortError') return;
                if (currentSearchQuery !== q) return;
                const dropdown = document.getElementById('globalItemSearchDropdown');
                if (dropdown) {
                    dropdown.innerHTML = '<div class="global-item-search-hit" style="color: var(--danger-color);">Search failed. Try again.</div>';
                    dropdown.style.display = 'block';
                    dropdown.setAttribute('aria-hidden', 'false');
                }
            });
    }

    /**
     * Called from inline oninput on the search field (same pattern as Items page filterItems()).
     * Ensures typing always triggers search regardless of when/if addEventListener bound.
     */
    function handleGlobalSearchInput(inputEl) {
        if (!inputEl) return;
        var q = (inputEl.value || '').trim();
        if (searchTimeout) clearTimeout(searchTimeout);
        hideDropdown();
        if (q.length < SEARCH_MIN_LEN) {
            clearSelection();
            return;
        }
        searchTimeout = setTimeout(function () {
            searchTimeout = null;
            runSearch(q);
        }, DEBOUNCE_MS);
    }
    window.handleGlobalSearchInput = handleGlobalSearchInput;

    function bind() {
        const input = document.getElementById('globalItemSearchInput');
        const dropdown = document.getElementById('globalItemSearchDropdown');
        const btnInvoice = document.getElementById('globalCreateInvoiceBtn');
        const btnQuotation = document.getElementById('globalCreateQuotationBtn');
        const btnOrder = document.getElementById('globalCreateOrderBtn');
        if (!input || !dropdown) return;

        input.removeAttribute('readonly');
        input.removeAttribute('disabled');

        // When user clicks anywhere in the search bar (not the dropdown), focus the input
        // so focus is never on a wrapper div and typing always goes to the input
        var bar = document.getElementById('globalItemSearchBar');
        if (bar) {
            bar.addEventListener('mousedown', function (e) {
                if (e.target.closest && e.target.closest('#globalItemSearchDropdown')) return;
                var inp = document.getElementById('globalItemSearchInput');
                if (inp && e.target !== inp) {
                    e.preventDefault();
                    inp.focus();
                }
            }, true);
        }

        input.addEventListener('blur', function () {
            setTimeout(hideDropdown, 180);
        });

        function selectDropdownItem(e) {
            const hit = e.target.closest('.global-item-search-hit');
            if (!hit || hit.dataset.idx === undefined) return;
            const idx = parseInt(hit.dataset.idx, 10);
            const item = lastResults[idx];
            if (!item) return;
            e.preventDefault();
            e.stopPropagation();
            input.value = (item.name || item.item_name || '') + (item.sku || item.item_code ? ' (' + (item.sku || item.item_code) + ')' : '');
            hideDropdown();
            showSelectedRow(item);
        }
        dropdown.addEventListener('mousedown', selectDropdownItem);
        dropdown.addEventListener('click', selectDropdownItem);

        if (btnInvoice) btnInvoice.addEventListener('click', function () {
            if (!selectedItem) return;
            goToDocument('sales_invoice', selectedItem);
        });
        if (btnQuotation) btnQuotation.addEventListener('click', function () {
            if (!selectedItem) return;
            goToDocument('quotation', selectedItem);
        });
        if (btnOrder) btnOrder.addEventListener('click', function () {
            if (!selectedItem) return;
            goToDocument('purchase_order', selectedItem);
        });

        // Focus search input when app is ready so user can type without clicking
        setTimeout(function () {
            if (input && document.getElementById('appLayout') && document.getElementById('appLayout').style.display !== 'none') {
                input.focus();
            }
        }, 250);
    }

    function init() {
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', bind);
        } else {
            bind();
        }
    }

    init();
    window.initGlobalItemSearch = bind;
})();
