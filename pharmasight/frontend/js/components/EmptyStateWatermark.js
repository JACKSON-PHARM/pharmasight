/**
 * EmptyStateWatermark - Reusable empty state with subtle SightOps mark
 * Used when a page has no data (list length === 0).
 * NOT rendered in print mode (use .no-print class).
 */
(function (global) {
    'use strict';

    /** SightOps aperture mark (monochrome watermark) */
    var LOGO_SVG =
        '<svg class="empty-state-watermark-logo" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" width="64" height="64" fill="none" aria-hidden="true">' +
        '<path d="M24 9 A15 15 0 0 1 36.98 31.2 L24 24 Z" fill="currentColor" opacity="0.22"/>' +
        '<path d="M24 9 A15 15 0 0 1 36.98 31.2 L24 24 Z" fill="currentColor" opacity="0.18" transform="rotate(120 24 24)"/>' +
        '<path d="M24 9 A15 15 0 0 1 36.98 31.2 L24 24 Z" fill="currentColor" opacity="0.14" transform="rotate(240 24 24)"/>' +
        '<ellipse cx="24" cy="24.5" rx="6.2" ry="4.65" fill="currentColor" opacity="0.06" transform="rotate(-11 24 24.5)"/>' +
        '</svg>';

    /** Allow only in-app hash routes for optional CTA (e.g. #items). */
    function safeActionHref(href) {
        var h = String(href || '').trim();
        if (!h || h.indexOf('#') !== 0) return '';
        if (!/^#[a-zA-Z0-9_-]+$/.test(h)) return '';
        return h;
    }

    /**
     * Render empty state watermark HTML
     * @param {Object} opts - { title: string, description?: string, actionLabel?: string, actionHref?: string (hash only), panel?: boolean }
     * @returns {string} HTML string
     */
    function render(opts) {
        opts = opts || {};
        var title = opts.title || 'No data yet';
        var description = opts.description || '';
        var actionLabel = opts.actionLabel || '';
        var actionHref = safeActionHref(opts.actionHref);
        var actionHtml = '';
        if (actionLabel && actionHref) {
            actionHtml =
                '<div class="empty-state-actions">' +
                '<a class="btn btn-primary btn-sm empty-state-action" href="' +
                escapeHtml(actionHref) +
                '">' +
                escapeHtml(actionLabel) +
                '</a></div>';
        }
        var wrapClass = 'empty-state-watermark no-print' + (opts.panel ? ' empty-state-panel' : '');
        return (
            '<div class="' +
            wrapClass +
            '">' +
                '<div class="empty-state-watermark-inner">' +
                    '<div class="empty-state-watermark-illustration" aria-hidden="true">' + LOGO_SVG + '</div>' +
                    '<h3 class="empty-state-watermark-title">' + escapeHtml(title) + '</h3>' +
                    (description ? '<p class="empty-state-watermark-desc">' + escapeHtml(description) + '</p>' : '') +
                    actionHtml +
                '</div>' +
            '</div>'
        );
    }

    function escapeHtml(s) {
        if (typeof s !== 'string') return '';
        var div = document.createElement('div');
        div.textContent = s;
        return div.innerHTML;
    }

    if (typeof module !== 'undefined' && module.exports) {
        module.exports = { render: render };
    } else {
        global.EmptyStateWatermark = { render: render };
    }
})(typeof window !== 'undefined' ? window : this);
