/**
 * Shared item mapping utility for converting API item objects to display objects.
 * Used by items.js and inventory.js to avoid duplicated fragile mapping logic.
 *
 * Assumptions: escapeHtml and formatNumber are global (defined in items.js / inventory.js / utils).
 */
(function () {
    'use strict';

    /**
     * Maps a raw item object from API.items.search() or API.items.overview()
     * to a consistent display object used in tables.
     */
    function mapApiItemToDisplay(item) {
        return {
            id: item.id,
            name: item.name,
            sku: item.sku || '',
            base_unit: item.base_unit,
            category: item.category || '',
            current_stock: item.current_stock !== undefined && item.current_stock !== null
                ? Number(item.current_stock)
                : null,
            stock_display: item.stock_display !== undefined && item.stock_display !== null
                ? String(item.stock_display)
                : null,
            stock_availability: item.stock_availability || null,
            last_supplier: item.last_supplier != null ? String(item.last_supplier) : '',
            last_unit_cost: item.last_unit_cost != null ? item.last_unit_cost : (item.purchase_price != null ? item.purchase_price : null),
            default_cost: item.default_cost != null ? item.default_cost : (item.price != null ? item.price : 0),
            is_active: item.is_active !== undefined ? item.is_active : true,
            minimum_stock: item.minimum_stock != null ? Number(item.minimum_stock) : null,
            pricing_3tier: item.pricing_3tier || {},
            vat_rate: item.vat_rate || 0,
            vat_category: item.vat_category || 'ZERO_RATED',
            track_expiry: item.track_expiry || false
        };
    }

    /**
     * Formats stock for display in table cells.
     * Returns HTML string with appropriate styling and low-stock warning.
     * Uses global escapeHtml and formatNumber.
     */
    function formatStockCell(item) {
        if (item.current_stock === null && !item.stock_display) {
            return '—';
        }

        var display = '';
        var isLowStock = item.minimum_stock !== null &&
            item.current_stock !== null &&
            item.current_stock < item.minimum_stock;
        var warningStyle = isLowStock ? ' style="color: #dc3545;"' : '';

        // Prefer stock_availability.unit_breakdown if present (items.js convention)
        if (item.stock_availability && item.stock_availability.unit_breakdown && item.stock_availability.unit_breakdown.length > 0) {
            var ub = item.stock_availability.unit_breakdown[0];
            display = '<strong' + warningStyle + '>' + (typeof escapeHtml === 'function' ? escapeHtml(ub.display) : String(ub.display)) + '</strong>';
        } else if (item.stock_display) {
            display = '<strong' + warningStyle + '>' + (typeof escapeHtml === 'function' ? escapeHtml(item.stock_display) : String(item.stock_display)) + '</strong>';
        } else if (item.current_stock !== null) {
            display = '<strong' + warningStyle + '>' + (typeof formatNumber === 'function' ? formatNumber(item.current_stock) : Number(item.current_stock)) + ' ' + (item.base_unit || '') + '</strong>';
        }
        return display;
    }

    window.mapApiItemToDisplay = mapApiItemToDisplay;
    window.formatStockCell = formatStockCell;
})();
