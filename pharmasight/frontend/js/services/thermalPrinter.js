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
    async function buildQrImageData(text, pixelWidth) {
        const value = (text != null && text !== '') ? String(text) : '';
        if (!value) return null;
        const w = (pixelWidth != null && parseInt(pixelWidth, 10) > 0) ? parseInt(pixelWidth, 10) : 180;
        // QRCode global comes from js/qrcode.vendor.iife.js
        if (typeof QRCode === 'undefined') return null;
        try {
            return await new Promise((resolve, reject) => {
                try {
                    const canvas = document.createElement('canvas');
                    QRCode.toCanvas(canvas, value, { width: w }, function (err) {
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

    /** KRA submission time for receipt (ISO string or Date). */
    function formatKraVerifiedLine(isoOrDate) {
        if (isoOrDate == null || isoOrDate === '') return '';
        try {
            const d = typeof isoOrDate === 'string' || typeof isoOrDate === 'number' ? new Date(isoOrDate) : isoOrDate;
            if (!(d instanceof Date) || isNaN(d.getTime())) return '';
            const pad = (n) => (n < 10 ? '0' + n : String(n));
            return `${pad(d.getDate())}/${pad(d.getMonth() + 1)}/${d.getFullYear()} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
        } catch (_) {
            return '';
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

        const maxChars = getMaxLineChars();
        const documentTitle = data.documentTitle || 'TAX INVOICE';
        const nonFiscalWarning = data.nonFiscalWarning || '';

        // Header — TAX INVOICE letterhead (center each line; some printers need alignment per line)
        add(CMD_CENTER);
        add(CMD_BOLD_ON);
        if (data.companyName) addCenter(data.companyName);
        add(CMD_BOLD_OFF);
        if (data.companyPin) addCenter(`PIN: ${fmt(data.companyPin)}`);
        if (data.branchPhone) addCenter(`TEL: ${fmt(data.branchPhone)}`);
        const addrParts = [];
        if (data.companyAddress && String(data.companyAddress).trim()) addrParts.push(String(data.companyAddress).trim());
        if (data.branchName || data.branchAddress) {
            const bb = [data.branchName, data.branchAddress].filter(Boolean).map((s) => String(s).trim()).filter(Boolean);
            if (bb.length) addrParts.push(bb.join(' — '));
        }
        const addrLine = addrParts.join(' | ');
        if (addrLine) {
            for (let i = 0; i < addrLine.length; i += maxChars) {
                addCenter(addrLine.slice(i, i + maxChars));
            }
        }
        add(CMD_CENTER);
        add('-'.repeat(Math.min(maxChars, 32)));
        add(CMD_BOLD_ON);
        addCenter(documentTitle);
        add(CMD_BOLD_OFF);
        if (nonFiscalWarning) {
            add(CMD_BOLD_ON);
            addCenter(nonFiscalWarning);
            add(CMD_BOLD_OFF);
        }
        add('');
        add(CMD_LEFT);
        add(truncate(`Invoice No: ${fmt(data.invoiceNo)}`, maxChars));
        const dateTimeLine = data.invoiceTime
            ? `Date: ${fmt(data.date)}  Time: ${fmt(data.invoiceTime)}`
            : `Date: ${fmt(data.date)}`;
        add(truncate(dateTimeLine, maxChars));
        const cust = (data.customerName && String(data.customerName).trim()) ? String(data.customerName).trim() : 'WALK-IN CUSTOMER';
        add(truncate(`Customer: ${cust}`, maxChars));
        const cpin = data.customerPin && String(data.customerPin).trim();
        add(truncate(cpin ? `Customer PIN: ${cpin}` : 'Customer PIN: OPTIONAL', maxChars));
        if (data.customerPhone && String(data.customerPhone).trim()) {
            add(truncate(`Phone: ${fmt(data.customerPhone)}`, maxChars));
        }
        if (data.paymentMode && String(data.paymentMode).trim()) {
            add(truncate(`Payment: ${fmt(data.paymentMode)}`, maxChars));
        }
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

        const hasKra = !!(data.kraReceiptNumber || data.kraSignature || data.kraQrCode);
        if (hasKra) {
            add('');
            add(CMD_CENTER);
            add(CMD_BOLD_ON);
            add(centerLine('KRA eTIMS', maxChars));
            add(CMD_BOLD_OFF);
            if (data.companyPin) addCenter(`PIN: ${fmt(data.companyPin)}`);
            if (data.kraInvoiceNumber) addCenter(`KRA Invoice No: ${fmt(data.kraInvoiceNumber)}`);
            if (data.kraReceiptNumber) addCenter(`KRA Receipt No: ${fmt(data.kraReceiptNumber)}`);
            if (data.cuDeviceSerial) addCenter(`Control Unit Serial No: ${fmt(data.cuDeviceSerial)}`);
            if (data.tisName) addCenter(`TIS: ${fmt(data.tisName)}`);
            add(CMD_LEFT);
        }
        add('');

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
        const payload = rawData.slice();
        const maxChars = getMaxLineChars();
        const hasKraFiscal = !!(data.kraReceiptNumber || data.kraSignature || data.kraQrCode);

        if (data.kraSignature) {
            let preQr = CMD_CENTER + LF;
            preQr += CMD_BOLD_ON + centerLine('Internal Data:', maxChars) + CMD_BOLD_OFF + LF;
            const sig = String(data.kraSignature);
            const chunk = maxChars;
            for (let i = 0; i < sig.length; i += chunk) {
                preQr += CMD_CENTER + centerLine(sig.slice(i, i + chunk), maxChars) + LF;
            }
            preQr += CMD_LEFT + LF;
            payload.push(preQr);
        }

        if (data.kraQrCode) {
            const qrDataUrl = await buildQrImageData(data.kraQrCode, 112).catch(() => null);
            if (qrDataUrl) {
                payload.push({
                    type: 'image',
                    data: qrDataUrl,
                    options: { language: 'escp', dotDensity: 'single' },
                });
            }
        }

        if (hasKraFiscal) {
            let tail = CMD_CENTER + LF;
            const verified = formatKraVerifiedLine(data.kraSubmittedAt);
            if (verified) {
                tail += CMD_BOLD_ON + centerLine('Date/Time Verified:', maxChars) + CMD_BOLD_OFF + LF;
                tail += CMD_CENTER + centerLine(verified, maxChars) + LF;
            }
            tail += CMD_BOLD_ON + centerLine('END OF FISCAL RECEIPT', maxChars) + CMD_BOLD_OFF + LF;
            tail += CMD_CENTER + centerLine('THANK YOU FOR SHOPPING WITH US', maxChars) + LF;
            tail += CMD_BOLD_ON + centerLine('Powered by SightOps', maxChars) + CMD_BOLD_OFF + LF;
            tail += CMD_LEFT + LF;
            payload.push(tail);
        } else {
            payload.push(
                CMD_CENTER +
                    CMD_BOLD_ON +
                    centerLine('Powered by SightOps', maxChars) +
                    CMD_BOLD_OFF +
                    LF +
                    CMD_LEFT +
                    LF
            );
        }
        payload.push(CMD_CUT);
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
