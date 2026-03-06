/**
 * EmptyStateWatermark - Reusable empty state with subtle PharmaSight branding
 * Used when a page has no data (list length === 0).
 * NOT rendered in print mode (use .no-print class).
 */
(function (global) {
    'use strict';

    /** PharmaSight logo SVG (eye with pill) - inline for reliability */
    var LOGO_SVG = '<svg class="empty-state-watermark-logo" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 24" width="64" height="32" aria-hidden="true"><path fill="currentColor" d="M24 2C12 2 4 10 4 12s8 10 20 10 20-8 20-10-8-10-20-10zm0 18c-6.6 0-12-4.5-14-6 2-1.5 7.4-6 14-6s12 4.5 14 6c-2 1.5-7.4 6-14 6z"/><circle fill="currentColor" cx="24" cy="12" r="4"/><rect x="21" y="10.5" width="6" height="3" rx="1" fill="currentColor" opacity="0.9"/></svg>';

    /**
     * Render empty state watermark HTML
     * @param {Object} opts - { title: string, description?: string }
     * @returns {string} HTML string
     */
    function render(opts) {
        var title = (opts && opts.title) || 'No data yet';
        var description = (opts && opts.description) || '';
        return (
            '<div class="empty-state-watermark no-print">' +
                '<div class="empty-state-watermark-inner">' +
                    '<div class="empty-state-watermark-illustration" aria-hidden="true">' + LOGO_SVG + '</div>' +
                    '<h3 class="empty-state-watermark-title">' + escapeHtml(title) + '</h3>' +
                    (description ? '<p class="empty-state-watermark-desc">' + escapeHtml(description) + '</p>' : '') +
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
