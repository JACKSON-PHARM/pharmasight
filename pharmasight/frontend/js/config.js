// PharmaSight Configuration

const CONFIG = {
    API_BASE_URL: 'http://localhost:8000',
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
};

// Load config from localStorage
function loadConfig() {
    const saved = localStorage.getItem('pharmasight_config');
    if (saved) {
        const config = JSON.parse(saved);
        Object.assign(CONFIG, config);
    }
}

// Save config to localStorage
function saveConfig() {
    localStorage.setItem('pharmasight_config', JSON.stringify({
        COMPANY_ID: CONFIG.COMPANY_ID,
        BRANCH_ID: CONFIG.BRANCH_ID,
        USER_ID: CONFIG.USER_ID,
        VAT_RATE: CONFIG.VAT_RATE,
    }));
}

// Initialize
loadConfig();

