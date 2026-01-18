// PharmaSight Configuration

const CONFIG = {
    API_BASE_URL: 'http://localhost:8000',
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
    
    // Also expose saveConfig for external use
    window.saveConfig = saveConfig;
    window.loadConfig = loadConfig;
}
