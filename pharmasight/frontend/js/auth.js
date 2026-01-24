/**
 * Supabase Authentication Service (Legacy)
 * 
 * DEPRECATED: This module is kept for backward compatibility.
 * New code should use AuthBootstrap service instead.
 * All Supabase client access now goes through the shared supabase_client.js module.
 */

/**
 * Initialize Supabase client (legacy wrapper)
 * @deprecated Use window.getSupabaseClient() or window.SupabaseClient.get() instead
 */
function initSupabase() {
    // Use shared client module
    if (typeof window !== 'undefined' && window.getSupabaseClient) {
        return window.getSupabaseClient();
    }
    console.warn('[AUTH LEGACY] Supabase client module not available');
    return null;
}

/**
 * Get Supabase client (direct access to shared module)
 */
function getClient() {
    if (typeof window !== 'undefined' && window.initSupabaseClient) {
        return window.initSupabaseClient();
    }
    return null;
}

/**
 * Get current authenticated user
 */
async function getCurrentUser() {
    const supabaseClient = getClient();
    if (!supabaseClient) {
        return null;
    }
    
    try {
        const { data: { user }, error } = await supabaseClient.auth.getUser();
        if (error) {
            console.error('Error getting user:', error);
            return null;
        }
        return user;
    } catch (error) {
        console.error('Error getting current user:', error);
        return null;
    }
}

/**
 * Get current session
 */
async function getCurrentSession() {
    const supabaseClient = getClient();
    if (!supabaseClient) {
        return null;
    }
    
    try {
        const { data: { session }, error } = await supabaseClient.auth.getSession();
        if (error) {
            console.error('Error getting session:', error);
            return null;
        }
        return session;
    } catch (error) {
        console.error('Error getting session:', error);
        return null;
    }
}

/**
 * Sign in with email and password
 */
async function signIn(email, password) {
    const supabaseClient = getClient();
    if (!supabaseClient) {
        throw new Error('Supabase client not available');
    }
    
    try {
        const { data, error } = await supabaseClient.auth.signInWithPassword({
            email,
            password
        });
        
        if (error) {
            throw error;
        }
        
        return data;
    } catch (error) {
        console.error('Sign in error:', error);
        throw error;
    }
}

/**
 * Sign out
 */
async function signOut() {
    const supabaseClient = getClient();
    if (!supabaseClient) {
        return;
    }
    
    try {
        const { error } = await supabaseClient.auth.signOut();
        if (error) {
            throw error;
        }
        
        // Clear local config
        CONFIG.COMPANY_ID = null;
        CONFIG.BRANCH_ID = null;
        CONFIG.USER_ID = null;
        saveConfig();
        
        // Redirect to login
        window.location.hash = '#login';
    } catch (error) {
        console.error('Sign out error:', error);
        throw error;
    }
}

/**
 * Check if user needs to complete setup
 */
async function checkSetupStatus(userId) {
    try {
        const response = await API.invite.getSetupStatus(userId);
        return response;
    } catch (error) {
        console.error('Error checking setup status:', error);
        // Default to needing setup if check fails
        return {
            needs_setup: true,
            company_exists: false
        };
    }
}

/**
 * Check user metadata for must_setup_company flag
 */
function getUserMetadata(user) {
    if (!user || !user.user_metadata) {
        return null;
    }
    
    return user.user_metadata;
}

/**
 * Check if user should be redirected to setup
 */
async function shouldRedirectToSetup() {
    const user = await getCurrentUser();
    
    if (!user) {
        // Not logged in - redirect to login
        return { redirect: 'login', reason: 'not_authenticated' };
    }
    
    // Check user metadata
    const metadata = getUserMetadata(user);
    const mustSetupCompany = metadata?.must_setup_company === 'true' || metadata?.must_setup_company === true;
    
    // Check database status with timeout
    let setupStatus = { needs_setup: true, company_exists: false };
    try {
        // Use Promise.race to timeout after 5 seconds
        const statusPromise = checkSetupStatus(user.id);
        const timeoutPromise = new Promise((_, reject) => 
            setTimeout(() => reject(new Error('Setup check timeout')), 5000)
        );
        
        setupStatus = await Promise.race([statusPromise, timeoutPromise]);
    } catch (error) {
        console.warn('Setup status check failed or timed out:', error);
        // Default to needing setup if check fails
        setupStatus = { needs_setup: true, company_exists: false };
    }
    
    if (mustSetupCompany || setupStatus.needs_setup || !setupStatus.company_exists) {
        return { redirect: 'setup', reason: 'setup_required' };
    }
    
    return { redirect: null, reason: null };
}

/**
 * Listen for auth state changes
 */
function onAuthStateChange(callback) {
    const supabaseClient = getClient();
    if (!supabaseClient) {
        return null;
    }
    
    return supabaseClient.auth.onAuthStateChange((event, session) => {
        callback(event, session);
    });
}

// Export functions
window.Auth = {
    initSupabase,
    getCurrentUser,
    getCurrentSession,
    signIn,
    signOut,
    checkSetupStatus,
    getUserMetadata,
    shouldRedirectToSetup,
    onAuthStateChange
};
