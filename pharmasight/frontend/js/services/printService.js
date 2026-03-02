/**
 * Print Service — abstraction for A4 (browser) vs Thermal (QZ Tray ESC/POS)
 * A4 mode uses existing window.print() logic. Thermal mode uses QZ Tray.
 * DO NOT remove window.print() — A4 path always invokes it.
 */
(function () {
    'use strict';

    /**
     * Get effective printer mode from CONFIG.
     * PRINTER_MODE: 'A4' | 'THERMAL' | undefined
     * - undefined or 'A4': use browser print (existing behavior)
     * - 'THERMAL': use QZ Tray ESC/POS when layout is thermal
     * @param {string} layout - 'thermal' | 'normal' from choosePrintLayout or CONFIG.PRINT_TYPE
     * @returns {'A4'|'THERMAL'}
     */
    function getEffectiveMode(layout) {
        const mode = (typeof CONFIG !== 'undefined' && CONFIG.PRINTER_MODE) || 'A4';
        if (mode === 'THERMAL' && layout === 'thermal') {
            return 'THERMAL';
        }
        return 'A4';
    }

    /**
     * Print document via appropriate channel.
     * @param {Object} opts
     * @param {string} opts.type - 'RECEIPT' | 'INVOICE' | 'QUOTATION' | 'PURCHASE_ORDER'
     * @param {string} opts.mode - 'THERMAL' | 'A4'
     * @param {Object} opts.data - Document data (invoice, quotation, order, or receipt payload)
     * @param {Function} [opts.a4Handler] - When mode is A4, this is called to perform existing browser print. Receives (data). May return a Promise.
     * @returns {Promise<void>}
     */
    async function printDocument(opts) {
        const { type, mode, data, a4Handler } = opts;
        if (mode === 'A4') {
            if (typeof a4Handler === 'function') {
                const result = a4Handler(data);
                if (result && typeof result.then === 'function') {
                    await result;
                }
                return;
            }
            console.warn('[PrintService] A4 mode but no a4Handler provided');
            return;
        }
        if (mode === 'THERMAL') {
            if (typeof window.ThermalPrinter === 'undefined' || typeof window.ThermalPrinter.printReceipt !== 'function') {
                if (typeof showToast === 'function') {
                    showToast('Thermal printer (QZ Tray) not available. Use browser print or install QZ Tray.', 'warning');
                }
                console.warn('[PrintService] ThermalPrinter not loaded; falling back to A4');
                if (typeof a4Handler === 'function') {
                    const fallbackData = type === 'INVOICE' ? { invoice: data, layout: 'thermal' }
                        : type === 'QUOTATION' ? { quotation: data, layout: 'thermal' }
                        : type === 'PURCHASE_ORDER' ? { order: data, layout: 'thermal' } : data;
                    const result = a4Handler(fallbackData);
                    if (result && typeof result.then === 'function') await result;
                }
                return;
            }
            try {
                if (!window.ThermalPrinter.connected) {
                    const search = (typeof CONFIG !== 'undefined' && CONFIG.THERMAL_PRINTER_SEARCH) || 'receipt';
                    await window.ThermalPrinter.connectPrinter(search);
                }
                const payload = toThermalPayload(type, data);
                await window.ThermalPrinter.printReceipt(payload);
            } catch (e) {
                console.warn('[PrintService] QZ Tray thermal print failed:', e);
                if (typeof showToast === 'function') {
                    showToast(e.message || 'Thermal print failed. Ensure QZ Tray is running and a receipt printer is installed.', 'warning');
                }
                if (typeof a4Handler === 'function') {
                    const fallbackData = type === 'INVOICE' ? { invoice: data, layout: 'thermal' }
                        : type === 'QUOTATION' ? { quotation: data, layout: 'thermal' }
                        : type === 'PURCHASE_ORDER' ? { order: data, layout: 'thermal' } : data;
                    const result = a4Handler(fallbackData);
                    if (result && typeof result.then === 'function') await result;
                }
                return;
            }
            if (typeof showToast === 'function') showToast('Receipt sent to thermal printer', 'success');
            return;
        }
        console.warn('[PrintService] Unknown mode:', mode);
    }

    /**
     * Convert document data to thermal printer payload format.
     * @param {string} type
     * @param {Object} doc
     * @returns {Object}
     */
    function toThermalPayload(type, doc) {
        const formatDate = (d) => {
            if (!d) return '';
            try {
                const date = typeof d === 'string' ? new Date(d) : d;
                return isNaN(date.getTime()) ? '' : date.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
            } catch (_) { return ''; }
        };
        const formatTime = () => new Date().toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'short' });

        if (type === 'RECEIPT' || type === 'INVOICE') {
            const inv = doc;
            return {
                companyName: inv.company_name || 'PharmaSight',
                branchName: inv.branch_name || '',
                invoiceNo: inv.invoice_no || inv.id || '',
                date: formatDate(inv.invoice_date),
                customerName: inv.customer_name || '',
                customerPhone: inv.customer_phone || '',
                items: inv.items || [],
                total: inv.total_inclusive != null ? inv.total_inclusive : (inv.total_amount || 0),
                servedBy: inv.created_by_username || inv.created_by_name || '',
                generatedTime: formatTime(),
                transactionMessage: (typeof CONFIG !== 'undefined' && CONFIG.TRANSACTION_MESSAGE) ? CONFIG.TRANSACTION_MESSAGE : ''
            };
        }
        if (type === 'QUOTATION') {
            const q = doc;
            return {
                companyName: q.company_name || 'PharmaSight',
                branchName: q.branch_name || '',
                invoiceNo: q.quotation_no || q.id || '',
                date: formatDate(q.quotation_date),
                customerName: q.customer_name || '',
                customerPhone: q.customer_phone || '',
                items: q.items || [],
                total: q.total_inclusive != null ? q.total_inclusive : (q.total_amount || 0),
                servedBy: q.created_by_username || q.created_by_name || '',
                generatedTime: formatTime(),
                transactionMessage: (typeof CONFIG !== 'undefined' && CONFIG.TRANSACTION_MESSAGE) ? CONFIG.TRANSACTION_MESSAGE : ''
            };
        }
        if (type === 'PURCHASE_ORDER') {
            const o = doc;
            const poItems = (o.items || []).map(i => ({
                item_name: i.item_name || 'Item',
                quantity: i.quantity,
                unit_name: i.unit_name,
                unit_price_exclusive: i.unit_price,
                vat_amount: 0,
                line_total_inclusive: i.total_price || (parseFloat(i.quantity || 0) * parseFloat(i.unit_price || 0))
            }));
            return {
                companyName: o.company_name || 'PharmaSight',
                branchName: o.branch_name || '',
                invoiceNo: o.order_number || o.id || '',
                date: formatDate(o.order_date),
                customerName: o.supplier_name || '',
                customerPhone: '',
                items: poItems,
                total: o.total_amount || 0,
                servedBy: o.created_by_name || '',
                generatedTime: formatTime(),
                transactionMessage: ''
            };
        }
        return doc;
    }

    if (typeof window !== 'undefined') {
        window.PrintService = {
            printDocument,
            getEffectiveMode,
            toThermalPayload
        };
    }
})();
