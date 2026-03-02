/**
 * Thermal Printer Service — QZ Tray ESC/POS
 * Sends raw ESC/POS commands to thermal printers via QZ Tray.
 * Requires QZ Tray desktop app to be running.
 * Format for 80mm (576 dots width assumption).
 */
(function () {
    'use strict';

    const ESC = '\x1B';
    const GS = '\x1D';
    const LF = '\x0A';

    const CMD_INIT = ESC + '\x40';
    const CMD_LEFT = ESC + '\x61\x00';
    const CMD_CENTER = ESC + '\x61\x01';
    const CMD_RIGHT = ESC + '\x61\x02';
    const CMD_BOLD_ON = ESC + '\x45\x01';
    const CMD_BOLD_OFF = ESC + '\x45\x00';
    const CMD_CUT = GS + '\x56\x41\x10';

    let _connected = false;
    let _defaultPrinterName = null;

    /**
     * Connect to QZ Tray and optionally find thermal printer.
     * @param {string} [printerSearch] - Optional search string to find printer (e.g. "POS", "XP-80", "receipt")
     * @returns {Promise<string|null>} Resolved with printer name or null if not found
     */
    async function connectPrinter(printerSearch) {
        if (typeof qz === 'undefined') {
            throw new Error('QZ Tray is not loaded. Ensure the QZ Tray script is included and QZ Tray desktop app is installed and running.');
        }
        try {
            if (!_connected) {
                await qz.websocket.connect();
                _connected = true;
            }
            if (printerSearch && typeof printerSearch === 'string') {
                const found = await qz.printers.find(printerSearch);
                _defaultPrinterName = (found && typeof found === 'string') ? found : (Array.isArray(found) && found.length > 0 ? found[0] : null);
                return _defaultPrinterName;
            }
            return _defaultPrinterName;
        } catch (e) {
            _connected = false;
            _defaultPrinterName = null;
            throw e;
        }
    }

    /**
     * Get list of available printers (requires connection).
     * @returns {Promise<string[]>}
     */
    async function listPrinters() {
        if (typeof qz === 'undefined') {
            throw new Error('QZ Tray is not loaded.');
        }
        if (!_connected) {
            await connectPrinter();
        }
        const list = await qz.printers.find();
        return Array.isArray(list) ? list : (list ? [list] : []);
    }

    /**
     * Set the default printer name for thermal printing.
     * @param {string} name - Exact printer name from OS
     */
    function setDefaultPrinter(name) {
        _defaultPrinterName = name;
    }

    /**
     * Build ESC/POS receipt from structured data.
     * @param {Object} data - Receipt/invoice data
     * @param {string} [data.companyName] - Company name
     * @param {string} [data.branchName] - Branch name
     * @param {string} [data.invoiceNo] - Invoice number
     * @param {string} [data.date] - Formatted date
     * @param {string} [data.customerName] - Customer name
     * @param {Array} [data.items] - Line items { item_name, quantity, unit_name, unit_price_exclusive, vat_amount, line_total_inclusive, ... }
     * @param {number|string} [data.total] - Total amount
     * @param {string} [data.servedBy] - Served by name
     * @param {string} [data.generatedTime] - Generated timestamp
     * @param {string} [data.transactionMessage] - Optional message
     * @returns {string[]} Array of ESC/POS command strings for qz.print()
     */
    function buildEscPosReceipt(data) {
        const lines = [];
        const add = (str) => lines.push(str + LF);
        const fmt = (val) => (val != null && val !== '' ? String(val) : '—');

        add(CMD_INIT);
        add(CMD_CENTER);
        add(CMD_BOLD_ON);
        if (data.companyName) add(fmt(data.companyName));
        if (data.branchName) add(fmt(data.branchName));
        add(CMD_BOLD_OFF);
        add('');
        add(CMD_LEFT);
        add('SALES INVOICE');
        add(`Invoice #: ${fmt(data.invoiceNo)}  Date: ${fmt(data.date)}`);
        if (data.customerName) add(`Customer: ${fmt(data.customerName)}`);
        if (data.customerPhone) add(`Phone: ${fmt(data.customerPhone)}`);
        add('');
        add(CMD_BOLD_ON);
        add('Item                    Qty   Price    VAT    Total');
        add(CMD_BOLD_OFF);
        add('------------------------------------------------');

        const items = data.items || [];
        const formatCurrency = (n) => {
            const val = parseFloat(n);
            if (isNaN(val)) return '0.00';
            return val.toLocaleString('en-KE', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
        };
        const formatQty = (q) => {
            const n = parseFloat(q);
            if (isNaN(n) || !isFinite(n)) return '0';
            return n % 1 === 0 ? String(Math.round(n)) : Number(n.toFixed(2)).toString();
        };

        for (const item of items) {
            const name = (item.item_name || item.item?.name || 'Item').substring(0, 22).padEnd(22);
            const qty = formatQty(item.quantity);
            const unit = (item.unit_display_short || item.unit_name || '').trim();
            const qtyUnit = unit ? `${qty} ${unit}` : qty;
            const price = formatCurrency(item.unit_price_exclusive || 0);
            const vat = formatCurrency(item.vat_amount || 0);
            const total = formatCurrency(item.line_total_inclusive != null ? item.line_total_inclusive : (parseFloat(item.quantity || 0) * parseFloat(item.unit_price_exclusive || 0)));
            add(`${name} ${qtyUnit.padStart(6)} ${price.padStart(8)} ${vat.padStart(6)} ${total.padStart(10)}`);
        }

        add('------------------------------------------------');
        add(CMD_BOLD_ON);
        add(`Total: ${formatCurrency(data.total || 0)}`);
        add(CMD_BOLD_OFF);
        add('');
        if (data.transactionMessage) add(fmt(data.transactionMessage));
        if (data.servedBy) add(`Served by: ${fmt(data.servedBy)}`);
        add(`Generated: ${fmt(data.generatedTime)}`);
        add('');
        add(CMD_CENTER);
        add('powered by pharmaSight solutions');
        add(CMD_LEFT);
        add('');
        add(CMD_CUT);

        return [lines.join('')];
    }

    /**
     * Print receipt using QZ Tray ESC/POS.
     * @param {Object} data - Receipt data (same shape as buildEscPosReceipt)
     * @param {string} [printerName] - Printer name; uses default if omitted
     * @returns {Promise<void>}
     */
    async function printReceipt(data, printerName) {
        const name = printerName || _defaultPrinterName;
        if (!name) {
            throw new Error('No thermal printer selected. Connect with a printer search term or call setDefaultPrinter().');
        }
        if (typeof qz === 'undefined') {
            throw new Error('QZ Tray is not loaded. Include the QZ Tray script.');
        }
        if (!_connected) {
            await connectPrinter();
        }
        const rawData = buildEscPosReceipt(data);
        const config = qz.configs.create(name, { encoding: 'UTF-8' });
        await qz.print(config, rawData);
    }

    if (typeof window !== 'undefined') {
        window.ThermalPrinter = {
            connectPrinter,
            listPrinters,
            setDefaultPrinter,
            buildEscPosReceipt,
            printReceipt,
            get connected() { return _connected; }
        };
    }
})();
