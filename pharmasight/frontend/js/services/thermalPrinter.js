/**
 * Thermal Printer Service — QZ Tray ESC/POS
 * Sends raw ESC/POS commands to thermal printers via QZ Tray.
 * Requires QZ Tray desktop app to be running.
 * Format for 80mm: max 32 chars/line to avoid right-edge overflow (~3mm margin).
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

    function getMaxLineChars() {
        return Math.min(48, Math.max(28, parseInt((typeof CONFIG !== 'undefined' && CONFIG.PRINT_THERMAL_MAX_CHARS), 10) || 32));
    }

    /** Truncate for center display; max chars per line */
    function centerLine(str, maxChars) {
        const m = maxChars || getMaxLineChars();
        const s = String(str || '').trim();
        if (s.length <= m) return s;
        return s.substring(0, m - 1) + '.';
    }

    /** Truncate for left-aligned display */
    function truncate(str, len) {
        const s = String(str || '').trim();
        if (s.length <= len) return s;
        return s.substring(0, len - 1) + '.';
    }

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
     * Generate QR PNG data URL from kraQrCode using qrcode.vendor.iife.js.
     * Returns null when QRCode library is not available.
     * @param {string} text
     * @returns {Promise<string|null>}
     */
    async function buildQrImageData(text) {
        const value = (text != null && text !== '') ? String(text) : '';
        if (!value) return null;
        // QRCode global comes from js/qrcode.vendor.iife.js
        if (typeof QRCode === 'undefined') return null;
        try {
            return await new Promise((resolve, reject) => {
                try {
                    const canvas = document.createElement('canvas');
                    QRCode.toCanvas(canvas, value, { width: 180 }, function (err) {
                        if (err) return reject(err);
                        try {
                            const url = canvas.toDataURL('image/png');
                            resolve(url);
                        } catch (e) {
                            reject(e);
                        }
                    });
                } catch (e) {
                    reject(e);
                }
            });
        } catch (_) {
            return null;
        }
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
        const addCenter = (str) => { add(CMD_CENTER); add(centerLine(str)); };
        const fmt = (val) => (val != null && val !== '' ? String(val) : '—');

        add(CMD_INIT);
        add(CMD_LEFT);

        // Header — center each line explicitly (some printers need alignment before every line)
        add(CMD_CENTER);
        add(CMD_BOLD_ON);
        if (data.companyName) addCenter(data.companyName);
        if (data.branchName) addCenter(data.branchName);
        add(CMD_BOLD_OFF);
        add(CMD_CENTER);
        add('');
        add(CMD_LEFT);

        const maxChars = getMaxLineChars();
        add(truncate('SALES INVOICE', maxChars));
        add(truncate(`Inv: ${fmt(data.invoiceNo)} ${fmt(data.date)}`, maxChars));
        if (data.customerName) add(truncate(`Customer: ${fmt(data.customerName)}`, maxChars));
        if (data.customerPhone) add(truncate(`Phone: ${fmt(data.customerPhone)}`, maxChars));
        add('');

        // Item table — compact layout, max chars/line to avoid right-edge overflow
        const colName = Math.min(16, Math.floor(maxChars * 0.45));
        const colQty = 5;
        const colPrice = 7;
        const colTotal = Math.max(6, maxChars - colName - colQty - colPrice);
        add(CMD_BOLD_ON);
        add(truncate('Item'.padEnd(colName) + 'Qty'.padStart(colQty) + 'Price'.padStart(colPrice) + 'Total'.padStart(colTotal), maxChars));
        add(CMD_BOLD_OFF);
        add('-'.repeat(maxChars));

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
            const name = truncate(item.item_name || item.item?.name || 'Item', colName).padEnd(colName);
            const qty = formatQty(item.quantity);
            const unit = (item.unit_display_short || item.unit_name || '').trim();
            const qtyStr = unit ? `${qty} ${unit}` : qty;
            const price = formatCurrency(item.unit_price_exclusive || 0);
            const total = formatCurrency(item.line_total_inclusive != null ? item.line_total_inclusive : (parseFloat(item.quantity || 0) * parseFloat(item.unit_price_exclusive || 0)));
            const line = name + qtyStr.padStart(colQty) + price.padStart(colPrice) + total.padStart(Math.max(6, colTotal));
            add(truncate(line, maxChars));
        }

        add('-'.repeat(maxChars));
        add(CMD_BOLD_ON);
        add(truncate(`Total: ${formatCurrency(data.total || 0)}`, maxChars));
        add(CMD_BOLD_OFF);
        add('');
        if (data.transactionMessage) add(truncate(fmt(data.transactionMessage), maxChars));
        if (data.servedBy) add(truncate(`Served by: ${fmt(data.servedBy)}`, maxChars));
        add(truncate(`Generated: ${fmt(data.generatedTime)}`, maxChars));
        // KRA receipt / verification section (text only; QR image printed separately when available)
        if (data.kraReceiptNumber) {
            add('');
            add(truncate(`KRA Receipt: ${fmt(data.kraReceiptNumber)}`, maxChars));
        }
        if (data.kraQrCode) {
            add(truncate('Scan to verify with KRA', maxChars));
        }
        add('');
        add(CMD_CENTER);
        add(centerLine('powered by PharmaSight Solutions', maxChars));
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
        const payload = rawData.slice(); // text receipt
        // Optional QR image (printer-agnostic bitmap via QZ Tray)
        if (data.kraQrCode) {
            const qrDataUrl = await buildQrImageData(data.kraQrCode).catch(() => null);
            if (qrDataUrl) {
                payload.push({ type: 'image', data: qrDataUrl, options: { language: 'escp', dotDensity: 'single' } });
            }
        }
        const config = qz.configs.create(name, { encoding: 'UTF-8' });
        await qz.print(config, payload);
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
