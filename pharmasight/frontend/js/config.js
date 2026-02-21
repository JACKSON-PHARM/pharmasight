// PharmaSight Configuration
// Use relative URL when served from same origin (e.g. Render); localhost => explicit API URL for local dev.
const CONFIG = {
    API_BASE_URL: (typeof window !== 'undefined' && window.location.hostname !== 'localhost' && window.location.hostname !== '127.0.0.1')
        ? ''
        : 'http://localhost:8000',
    // Public URL of the frontend (used for Supabase email redirects).
    // Defaults to current origin; can be overridden via localStorage key `pharmasight_app_public_url`.
    APP_PUBLIC_URL: (typeof window !== 'undefined' && window.location && window.location.origin) ? window.location.origin : '',
    // Supabase Configuration
    // Get these from: https://supabase.com/dashboard/project/kwvkkbofubsjiwqlqakt/settings/api
    SUPABASE_URL: 'https://kwvkkbofubsjiwqlqakt.supabase.co',  // Your Project URL
    SUPABASE_ANON_KEY: 'sb_publishable_9HyrUBwjvn0RND-HEzndkQ_C-Vw1-_u',  // Your publishable key
    API_ENDPOINTS: {
        items: '/api/items',
        inventory: '/api/inventory',
        sales: '/api/sales',
        purchases: '/api/purchases',
        companies: '/api/companies',
        branches: '/api/branches',
        suppliers: '/api/suppliers',
    },
    // Default values (should be set from settings or user selection)
    COMPANY_ID: null,
    BRANCH_ID: null,
    USER_ID: null,
    VAT_RATE: 16.00,
    // Print: 'normal' (A4) or 'thermal' (80mm receipt). Default thermal so receipt printers work without setup.
    PRINT_TYPE: 'thermal',
    // Optional message shown on printed documents (quotations, sales invoices, credit notes)
    TRANSACTION_MESSAGE: '',
    // Minimize margins on thermal print (thermal layout is already tight; this is extra)
    PRINT_REMOVE_MARGIN: true,
    // Default number of copies when printing (user can still change in print dialog)
    PRINT_COPIES: 1,
    // Auto-cut receipts: add extra feed so thermal printer cuts at end of content
    PRINT_AUTO_CUT: false,
    // Thermal receipt theme: 'theme1' | 'theme2' | 'theme3' | 'theme4' (layout/style)
    PRINT_THEME: 'theme1',
    // Thermal page width in mm: 58 (2"), 68 (3"), 80, 88 (4")
    PRINT_PAGE_WIDTH_MM: 80,
    // Header: what to print
    PRINT_HEADER_COMPANY: true,
    PRINT_HEADER_ADDRESS: true,
    PRINT_HEADER_EMAIL: true,
    PRINT_HEADER_PHONE: true,
    // Item table columns
    PRINT_ITEM_SNO: true,
    PRINT_ITEM_UNIT: true,
    PRINT_ITEM_CODE: true,
    PRINT_ITEM_DESCRIPTION: false,
    PRINT_ITEM_BATCH: false,
    PRINT_ITEM_EXP: false,
    PRINT_SHOW_VAT: false,
    // Totals & taxes
    PRINT_TOTAL_QTY: true,
    PRINT_RECEIVED: true,
    PRINT_BALANCE: true,
    PRINT_TAX_DETAILS: true,
    PRINT_AMOUNT_IN_WORDS: false,
    PRINT_AMOUNT_GROUPING: true,
    // Footer
    PRINT_FOOTER_TERMS: true,
};

// Load config from localStorage
function loadConfig() {
    // Load app config (company, branch, etc.)
    const saved = localStorage.getItem('pharmasight_config');
    if (saved) {
        const config = JSON.parse(saved);
        Object.assign(CONFIG, config);
    }
    
    // Load Supabase config (if set)
    const supabaseConfig = localStorage.getItem('pharmasight_supabase_config');
    if (supabaseConfig) {
        const supabase = JSON.parse(supabaseConfig);
        if (supabase.SUPABASE_URL) CONFIG.SUPABASE_URL = supabase.SUPABASE_URL;
        if (supabase.SUPABASE_ANON_KEY) CONFIG.SUPABASE_ANON_KEY = supabase.SUPABASE_ANON_KEY;
    }

    // Optional: override public app URL for email redirects (useful when testing locally but sending production links)
    try {
        const pub = localStorage.getItem('pharmasight_app_public_url');
        if (pub && typeof pub === 'string' && pub.trim()) {
            CONFIG.APP_PUBLIC_URL = pub.trim().replace(/\/+$/, '');
        }
    } catch (_) {}
    if (!CONFIG.APP_PUBLIC_URL && typeof window !== 'undefined' && window.location && window.location.origin) {
        CONFIG.APP_PUBLIC_URL = window.location.origin;
    }
}

/** Build print config object for API storage (company-level settings) */
function buildPrintConfigForApi() {
    const bool = (k) => CONFIG[k] === true;
    return {
        PRINT_TYPE: CONFIG.PRINT_TYPE || 'thermal',
        TRANSACTION_MESSAGE: CONFIG.TRANSACTION_MESSAGE || '',
        PRINT_REMOVE_MARGIN: bool('PRINT_REMOVE_MARGIN'),
        PRINT_COPIES: Math.max(1, parseInt(CONFIG.PRINT_COPIES, 10) || 1),
        PRINT_AUTO_CUT: bool('PRINT_AUTO_CUT'),
        PRINT_THEME: CONFIG.PRINT_THEME || 'theme1',
        PRINT_PAGE_WIDTH_MM: Math.min(88, Math.max(58, parseInt(CONFIG.PRINT_PAGE_WIDTH_MM, 10) || 80)),
        PRINT_HEADER_COMPANY: bool('PRINT_HEADER_COMPANY'),
        PRINT_HEADER_ADDRESS: bool('PRINT_HEADER_ADDRESS'),
        PRINT_HEADER_EMAIL: bool('PRINT_HEADER_EMAIL'),
        PRINT_HEADER_PHONE: bool('PRINT_HEADER_PHONE'),
        PRINT_ITEM_SNO: bool('PRINT_ITEM_SNO'),
        PRINT_ITEM_UNIT: bool('PRINT_ITEM_UNIT'),
        PRINT_ITEM_CODE: bool('PRINT_ITEM_CODE'),
        PRINT_ITEM_DESCRIPTION: bool('PRINT_ITEM_DESCRIPTION'),
        PRINT_ITEM_BATCH: bool('PRINT_ITEM_BATCH'),
        PRINT_ITEM_EXP: bool('PRINT_ITEM_EXP'),
        PRINT_SHOW_VAT: bool('PRINT_SHOW_VAT'),
        PRINT_TOTAL_QTY: bool('PRINT_TOTAL_QTY'),
        PRINT_RECEIVED: bool('PRINT_RECEIVED'),
        PRINT_BALANCE: bool('PRINT_BALANCE'),
        PRINT_TAX_DETAILS: bool('PRINT_TAX_DETAILS'),
        PRINT_AMOUNT_IN_WORDS: bool('PRINT_AMOUNT_IN_WORDS'),
        PRINT_AMOUNT_GROUPING: bool('PRINT_AMOUNT_GROUPING'),
        PRINT_FOOTER_TERMS: bool('PRINT_FOOTER_TERMS'),
    };
}

/** Load company print settings from API and merge into CONFIG */
async function loadCompanyPrintSettings() {
    const cid = CONFIG.COMPANY_ID;
    if (!cid || typeof window === 'undefined' || !window.API?.company?.getSettings) return;
    try {
        const res = await window.API.company.getSettings(cid, 'print_config');
        const v = res?.value;
        if (v && typeof v === 'object') {
            Object.keys(v).forEach(k => {
                if (k in CONFIG && v[k] !== undefined) CONFIG[k] = v[k];
            });
            if (typeof saveConfig === 'function') saveConfig();
        }
    } catch (e) {
        console.warn('[CONFIG] Could not load company print settings:', e.message);
    }
}

/** Save print config to company settings API (admin sets at company level) */
async function saveCompanyPrintSettings() {
    const cid = CONFIG.COMPANY_ID;
    if (!cid || typeof window === 'undefined' || !window.API?.company?.updateSetting) return;
    try {
        await window.API.company.updateSetting(cid, { key: 'print_config', value: buildPrintConfigForApi() });
    } catch (e) {
        console.warn('[CONFIG] Could not save company print settings:', e.message);
    }
}

// Save config to localStorage
function saveConfig() {
    const printBool = (k) => CONFIG[k] === true;
    localStorage.setItem('pharmasight_config', JSON.stringify({
        COMPANY_ID: CONFIG.COMPANY_ID,
        BRANCH_ID: CONFIG.BRANCH_ID,
        USER_ID: CONFIG.USER_ID,
        VAT_RATE: CONFIG.VAT_RATE,
        PRINT_TYPE: CONFIG.PRINT_TYPE,
        TRANSACTION_MESSAGE: CONFIG.TRANSACTION_MESSAGE || '',
        PRINT_REMOVE_MARGIN: printBool('PRINT_REMOVE_MARGIN'),
        PRINT_COPIES: Math.max(1, parseInt(CONFIG.PRINT_COPIES, 10) || 1),
        PRINT_AUTO_CUT: printBool('PRINT_AUTO_CUT'),
        PRINT_THEME: CONFIG.PRINT_THEME || 'theme1',
        PRINT_PAGE_WIDTH_MM: Math.min(88, Math.max(58, parseInt(CONFIG.PRINT_PAGE_WIDTH_MM, 10) || 80)),
        PRINT_HEADER_COMPANY: printBool('PRINT_HEADER_COMPANY'),
        PRINT_HEADER_ADDRESS: printBool('PRINT_HEADER_ADDRESS'),
        PRINT_HEADER_EMAIL: printBool('PRINT_HEADER_EMAIL'),
        PRINT_HEADER_PHONE: printBool('PRINT_HEADER_PHONE'),
        PRINT_ITEM_SNO: printBool('PRINT_ITEM_SNO'),
        PRINT_ITEM_UNIT: printBool('PRINT_ITEM_UNIT'),
        PRINT_ITEM_CODE: printBool('PRINT_ITEM_CODE'),
        PRINT_ITEM_DESCRIPTION: printBool('PRINT_ITEM_DESCRIPTION'),
        PRINT_ITEM_BATCH: printBool('PRINT_ITEM_BATCH'),
        PRINT_ITEM_EXP: printBool('PRINT_ITEM_EXP'),
        PRINT_SHOW_VAT: printBool('PRINT_SHOW_VAT'),
        PRINT_TOTAL_QTY: printBool('PRINT_TOTAL_QTY'),
        PRINT_RECEIVED: printBool('PRINT_RECEIVED'),
        PRINT_BALANCE: printBool('PRINT_BALANCE'),
        PRINT_TAX_DETAILS: printBool('PRINT_TAX_DETAILS'),
        PRINT_AMOUNT_IN_WORDS: printBool('PRINT_AMOUNT_IN_WORDS'),
        PRINT_AMOUNT_GROUPING: printBool('PRINT_AMOUNT_GROUPING'),
        PRINT_FOOTER_TERMS: printBool('PRINT_FOOTER_TERMS'),
    }));
}

// Save Supabase config to localStorage
function saveSupabaseConfig() {
    localStorage.setItem('pharmasight_supabase_config', JSON.stringify({
        SUPABASE_URL: CONFIG.SUPABASE_URL,
        SUPABASE_ANON_KEY: CONFIG.SUPABASE_ANON_KEY,
    }));
}

// Initialize
loadConfig();

// Expose CONFIG to window for global access
if (typeof window !== 'undefined') {
    window.CONFIG = CONFIG;
    window.saveConfig = saveConfig;
    window.loadConfig = loadConfig;
    window.loadCompanyPrintSettings = loadCompanyPrintSettings;
    window.saveCompanyPrintSettings = saveCompanyPrintSettings;
    window.buildPrintConfigForApi = buildPrintConfigForApi;
}
