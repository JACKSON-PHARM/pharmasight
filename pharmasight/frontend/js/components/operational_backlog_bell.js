/**
 * Operational backlog bell — prior-date unposted documents (stock-blocking vs informational).
 */
(function () {
    'use strict';

    var _cache = null;
    var _cacheKey = '';
    var _pollTimer = null;

    function businessDateToday() {
        return new Date().toISOString().split('T')[0];
    }

    function cacheKey() {
        var cfg = typeof CONFIG !== 'undefined' ? CONFIG : (window.CONFIG || {});
        return (cfg.BRANCH_ID || '') + '|' + businessDateToday();
    }

    function escapeHtml(s) {
        if (typeof window.escapeHtml === 'function') return window.escapeHtml(s);
        return String(s || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function formatDocDate(iso) {
        if (!iso) return '—';
        try {
            return new Date(iso + 'T12:00:00').toLocaleDateString();
        } catch (_) {
            return iso;
        }
    }

    async function fetchBacklog(force) {
        var cfg = typeof CONFIG !== 'undefined' ? CONFIG : (window.CONFIG || {});
        if (!cfg.BRANCH_ID || !window.API || !window.API.branchOps) return null;
        var key = cacheKey();
        if (!force && _cache && _cacheKey === key) return _cache;
        try {
            _cache = await window.API.branchOps.getOperationalBacklog(cfg.BRANCH_ID, businessDateToday());
            _cacheKey = key;
            return _cache;
        } catch (e) {
            console.warn('operational backlog fetch failed', e);
            return _cache;
        }
    }

    function isModuleBlocked(summary, module) {
        if (!summary || !summary.blocked_modules) return false;
        return summary.blocked_modules.indexOf(module) >= 0;
    }

    function navigateToDocument(doc) {
        if (!doc || !doc.id) return;
        var type = doc.document_type;
        var id = doc.id;
        var bell = document.getElementById('operationalBacklogBell');
        if (bell) bell.classList.remove('open');

        if (type === 'sales_invoice') {
            window.currentInvoice = { id: id, mode: 'edit', invoiceData: { id: id, status: 'DRAFT' } };
            if (window.loadPage) window.loadPage('sales-create-invoice');
            return;
        }
        if (type === 'supplier_invoice') {
            if (window.viewSupplierInvoice) {
                window.viewSupplierInvoice(id);
            } else if (window.loadPage) {
                window.loadPage('purchases-create-invoice');
            }
            return;
        }
        if (type === 'branch_transfer') {
            window.branchTransfersView = 'view';
            window.branchTransferViewId = id;
            if (window.loadPage) window.loadPage('inventory-branch-transfers');
            return;
        }
        if (type === 'department_supply_transfer') {
            try {
                sessionStorage.setItem('pendingDepartmentTransferId', id);
            } catch (_) {}
            if (window.loadPage) window.loadPage('inventory-department-transfers');
            return;
        }
        if (type === 'credit_note') {
            try {
                sessionStorage.setItem('pendingCreditNoteId', id);
            } catch (_) {}
            if (window.loadPage) window.loadPage('sales-returns');
            if (typeof window.showToast === 'function') {
                window.showToast('Open the credit note from the returns list and complete posting.', 'info');
            }
            return;
        }
        if (type === 'supplier_return') {
            if (window.loadPage) window.loadPage('purchases-credit-notes');
            if (typeof window.showToast === 'function') {
                window.showToast('Open supplier returns / credit notes to approve or post this document.', 'info');
            }
            return;
        }
        if (type === 'branch_order') {
            if (window.loadPage) window.loadPage('inventory-branch-orders');
            return;
        }
        if (type === 'department_supply_order') {
            if (window.loadPage) window.loadPage('inventory-department-transfers');
            return;
        }
        if (type === 'purchase_order') {
            if (window.loadPurchaseSubPage) {
                window.loadPurchaseSubPage('orders');
            } else if (window.loadPage) {
                window.loadPage('purchases-orders');
            }
            return;
        }
        if (type === 'quotation') {
            window.currentQuotation = { id: id, mode: 'edit' };
            if (window.loadPage) window.loadPage('sales-create-quotation');
        }
    }

    function renderListItems(docs, blocking) {
        if (!docs || !docs.length) {
            return '<div class="op-backlog-empty">None</div>';
        }
        return docs
            .map(function (doc) {
                var cls = blocking ? 'op-backlog-item op-backlog-item-blocking' : 'op-backlog-item op-backlog-item-info';
                return (
                    '<button type="button" class="' +
                    cls +
                    '" data-doc-type="' +
                    escapeHtml(doc.document_type) +
                    '" data-doc-id="' +
                    escapeHtml(doc.id) +
                    '">' +
                    '<span class="op-backlog-item-title">' +
                    escapeHtml(doc.label) +
                    ' · <strong>' +
                    escapeHtml(doc.document_no) +
                    '</strong></span>' +
                    '<span class="op-backlog-item-meta">' +
                    escapeHtml(formatDocDate(doc.document_date)) +
                    ' · ' +
                    escapeHtml(doc.status) +
                    '</span>' +
                    '</button>'
                );
            })
            .join('');
    }

    function renderDropdown(summary) {
        var panel = document.getElementById('operationalBacklogPanel');
        if (!panel) return;
        if (!summary) {
            panel.innerHTML = '<div class="op-backlog-panel-inner"><p class="op-backlog-hint">Could not load backlog.</p></div>';
            return;
        }
        var blocking = summary.blocking_documents || [];
        var info = summary.informational_documents || [];
        var biz = summary.business_date || businessDateToday();
        panel.innerHTML =
            '<div class="op-backlog-panel-inner">' +
            '<div class="op-backlog-panel-header">' +
            '<strong>Unposted from before ' +
            escapeHtml(formatDocDate(biz)) +
            '</strong>' +
            '<button type="button" class="op-backlog-refresh" id="operationalBacklogRefresh" title="Refresh"><i class="fas fa-sync-alt"></i></button>' +
            '</div>' +
            '<p class="op-backlog-hint">Batch, delete, or update dated documents before starting new stock-affecting work today.</p>' +
            '<div class="op-backlog-section">' +
            '<div class="op-backlog-section-title"><i class="fas fa-exclamation-circle"></i> Blocking stock workflows (' +
            blocking.length +
            ')</div>' +
            renderListItems(blocking, true) +
            '</div>' +
            (info.length
                ? '<div class="op-backlog-section op-backlog-section-muted">' +
                  '<div class="op-backlog-section-title"><i class="fas fa-info-circle"></i> Open only (no block) (' +
                  info.length +
                  ')</div>' +
                  renderListItems(info, false) +
                  '</div>'
                : '') +
            '</div>';
        panel.querySelectorAll('.op-backlog-item').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var doc = {
                    document_type: btn.getAttribute('data-doc-type'),
                    id: btn.getAttribute('data-doc-id'),
                };
                navigateToDocument(doc);
            });
        });
        var refreshBtn = document.getElementById('operationalBacklogRefresh');
        if (refreshBtn) {
            refreshBtn.addEventListener('click', function (e) {
                e.stopPropagation();
                void refresh(true);
            });
        }
    }

    function updateBadge(summary) {
        var badge = document.getElementById('operationalBacklogBadge');
        var bell = document.getElementById('operationalBacklogBell');
        if (!badge || !bell) return;
        var n = summary ? summary.blocking_count || 0 : 0;
        badge.textContent = n > 99 ? '99+' : String(n);
        badge.style.display = n > 0 ? 'flex' : 'none';
        bell.classList.toggle('has-blocking', n > 0);
        bell.title =
            n > 0
                ? n + ' unposted document(s) from earlier dates — click to review'
                : 'No blocking unposted documents';
    }

    function applyQuickActionBlocks(summary) {
        var saleBtn = document.getElementById('globalAddSaleBtn');
        var purchaseBtn = document.getElementById('globalAddSupplierInvoiceBtn');
        if (saleBtn) {
            var blocked = isModuleBlocked(summary, 'sales');
            saleBtn.disabled = blocked;
            saleBtn.title = blocked
                ? 'Blocked: clear prior-date sales drafts (notification bell)'
                : 'New sales invoice';
        }
        if (purchaseBtn) {
            var blockedP = isModuleBlocked(summary, 'purchases');
            purchaseBtn.disabled = blockedP;
            purchaseBtn.title = blockedP
                ? 'Blocked: clear prior-date supplier drafts (notification bell)'
                : 'New supplier invoice (receive stock)';
        }
    }

    async function refresh(force) {
        var summary = await fetchBacklog(force);
        updateBadge(summary);
        renderDropdown(summary);
        applyQuickActionBlocks(summary);
        window.operationalBacklogSummary = summary;
        try {
            window.dispatchEvent(new CustomEvent('operational-backlog-updated', { detail: summary }));
        } catch (_) {}
        return summary;
    }

    function initBell() {
        var bell = document.getElementById('operationalBacklogBell');
        if (!bell || bell.dataset.initialized === '1') return;
        bell.dataset.initialized = '1';
        bell.addEventListener('click', function (e) {
            e.stopPropagation();
            bell.classList.toggle('open');
            if (bell.classList.contains('open')) void refresh(false);
        });
        document.addEventListener('click', function (e) {
            if (!bell.contains(e.target)) bell.classList.remove('open');
        });
        void refresh(true);
        if (_pollTimer) clearInterval(_pollTimer);
        _pollTimer = setInterval(function () {
            if (document.hidden) return;
            void refresh(true);
        }, 90000);
    }

    window.operationalBacklogBell = {
        refresh: refresh,
        isModuleBlocked: function (module) {
            return isModuleBlocked(window.operationalBacklogSummary, module);
        },
        navigateToDocument: navigateToDocument,
        init: initBell,
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initBell);
    } else {
        initBell();
    }

    window.addEventListener('pharmasight-branch-changed', function () {
        _cache = null;
        void refresh(true);
    });
})();
