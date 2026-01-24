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
 * Global logout function
 * Forces immediate redirect to login, then signs out and clears state
 */
async function globalLogout() {
    console.log('[LOGOUT] Starting logout process...');
    
    try {
        // STEP 1: Force immediate switch to auth layout and #login (CRITICAL: before signOut)
        // This prevents any app pages from trying to render during logout
        if (window.renderAuthLayout) {
            window.renderAuthLayout();
        }
        
        // Force hash to login immediately (before any async operations)
        window.location.hash = '#login';
        window.history.replaceState(null, '', window.location.href.split('#')[0] + '#login');
        
        console.log('[LOGOUT] Switched to auth layout and set hash to #login');
        
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
        // Even if signOut fails, ensure auth layout and login page
        if (window.renderAuthLayout) {
            window.renderAuthLayout();
        }
        await clearAppState();
        window.location.hash = '#login';
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
    window.globalLogout = globalLogout; // Also expose as global function
}
