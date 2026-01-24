/**
 * Global Supabase Client
 * 
 * Single source of truth for Supabase client initialization.
 * ONE private variable, ONE init function, no getters wrapping getters.
 */

// ONE private variable - the Supabase client instance
let supabaseClient = null;

/**
 * ONE init function - initializes the client once
 * @returns {Object|null} Supabase client instance or null if initialization fails
 */
function initSupabaseClient() {
    // Return existing client if already initialized
    if (supabaseClient) {
        return supabaseClient;
    }
    
    // Check if Supabase library is loaded
    if (typeof supabase === 'undefined') {
        console.error('[SUPABASE CLIENT] Supabase JS library not loaded');
        return null;
    }
    
    // Check if CONFIG is available
    if (typeof CONFIG === 'undefined') {
        console.error('[SUPABASE CLIENT] CONFIG not available');
        return null;
    }
    
    const supabaseUrl = CONFIG.SUPABASE_URL || '';
    const supabaseAnonKey = CONFIG.SUPABASE_ANON_KEY || '';
    
    if (!supabaseUrl || !supabaseAnonKey) {
        console.error('[SUPABASE CLIENT] Supabase URL or Anon Key not configured');
        return null;
    }
    
    // Initialize client (only once)
    try {
        supabaseClient = supabase.createClient(supabaseUrl, supabaseAnonKey);
        console.log('[SUPABASE CLIENT] Client initialized successfully');
        return supabaseClient;
    } catch (error) {
        console.error('[SUPABASE CLIENT] Failed to initialize client:', error);
        return null;
    }
}

// Export ONLY the init function to window (no wrappers, no getters)
if (typeof window !== 'undefined') {
    window.initSupabaseClient = initSupabaseClient;
}
