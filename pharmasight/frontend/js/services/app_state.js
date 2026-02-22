/**
 * App State Service
 * 
 * Manages global app state and logout functionality.
 * Ensures all state is cleared on logout.
 */

/**
 * Clear all app state
 */
async function clearAppState() {
    // Clear branch context
    if (window.BranchContext) {
        BranchContext.clearBranch();
    }
    
    // Clear config
    if (CONFIG) {
        CONFIG.COMPANY_ID = null;
        CONFIG.BRANCH_ID = null;
        CONFIG.USER_ID = null;
        if (typeof saveConfig === 'function') {
            saveConfig();
        }
    }
    
    // Clear localStorage items (keep Supabase config)
    const keysToKeep = ['pharmasight_supabase_config'];
    const keysToRemove = [];
    for (let i = 0; i < localStorage.length; i++) {
        const key = localStorage.key(i);
        if (key && key.startsWith('pharmasight_') && !keysToKeep.includes(key)) {
            keysToRemove.push(key);
        }
    }
    keysToRemove.forEach(key => localStorage.removeItem(key));
    
    // Clear sessionStorage
    sessionStorage.clear();
}

/**
 * Build login URL without any tenant query param so the next user can sign in to any tenant.
 * Prevents "invalid token" when a user from another tenant opens the same browser.
 */
function getCleanLoginUrl() {
    const origin = typeof window !== 'undefined' && window.location.origin ? window.location.origin : '';
    const pathname = (typeof window !== 'undefined' && window.location.pathname) ? window.location.pathname : '/';
    const base = origin + (pathname === '' ? '/' : pathname);
    return (base.endsWith('/') ? base : base + '/') + '#login';
}

/**
 * Global logout function
 * Forces immediate redirect to login, then signs out and clears state.
 * Resets URL to a tenant-free login URL so the next user can sign in to any tenant.
 */
async function globalLogout() {
    console.log('[LOGOUT] Starting logout process...');
    
    try {
        // STEP 1: Force immediate switch to auth layout and #login (CRITICAL: before signOut)
        if (window.renderAuthLayout) {
            window.renderAuthLayout();
        }
        
        // Force hash to login and strip tenant (and any other query) from URL so next user gets clean login
        const cleanLoginUrl = getCleanLoginUrl();
        window.location.hash = '#login';
        window.history.replaceState(null, '', cleanLoginUrl);
        
        console.log('[LOGOUT] Switched to auth layout and set URL to tenant-free login:', cleanLoginUrl);
        
        // STEP 2: Sign out from Supabase (this will trigger auth state change)
        if (window.AuthBootstrap && window.AuthBootstrap.signOut) {
            await AuthBootstrap.signOut();
        }
        
        // STEP 3: Clear app state after successful sign out
        await clearAppState();
        
        // STEP 4: Ensure login page is loaded (redundant but safe)
        if (window.loadPage) {
            window.loadPage('login');
        }
        
        console.log('[LOGOUT] Logout completed successfully');
        
    } catch (error) {
        console.error('[LOGOUT] Error during logout:', error);
        if (window.renderAuthLayout) {
            window.renderAuthLayout();
        }
        await clearAppState();
        const cleanLoginUrl = getCleanLoginUrl();
        window.location.hash = '#login';
        window.history.replaceState(null, '', cleanLoginUrl);
        if (window.loadPage) {
            window.loadPage('login');
        }
    }
}

// Export AppState service
const AppState = {
    clear: clearAppState,
    logout: globalLogout
};

// Expose to window
if (typeof window !== 'undefined') {
    window.AppState = AppState;
    window.globalLogout = globalLogout;
    window.getCleanLoginUrl = getCleanLoginUrl; // For auth-state-change logout path
}
