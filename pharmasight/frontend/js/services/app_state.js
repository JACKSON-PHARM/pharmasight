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
/**
 * Call backend to terminate session (revoke token server-side).
 * Uses current access token so the backend can revoke it; safe to call even if no token.
 */
async function callBackendLogout() {
    try {
        const token = typeof localStorage !== 'undefined' ? localStorage.getItem('pharmasight_access_token') : null;
        if (!token) return;
        const base = (typeof CONFIG !== 'undefined' && CONFIG.API_BASE_URL) ? CONFIG.API_BASE_URL : '';
        const url = (base ? base.replace(/\/$/, '') : '') + '/api/auth/logout';
        await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
        });
    } catch (_) {
        // Best effort; don't block logout if backend is unreachable
    }
}

async function globalLogout() {
    console.log('[LOGOUT] Starting logout process...');
    
    try {
        // STEP 1: Revoke token on backend so session is terminated (token cannot be used again)
        await callBackendLogout();
        
        // STEP 2: Force immediate switch to auth layout and #login (CRITICAL: before signOut)
        if (window.renderAuthLayout) {
            window.renderAuthLayout();
        }
        
        // Force hash to login and strip tenant (and any other query) from URL so next user gets clean login
        const cleanLoginUrl = getCleanLoginUrl();
        window.location.hash = '#login';
        window.history.replaceState(null, '', cleanLoginUrl);
        
        console.log('[LOGOUT] Switched to auth layout and set URL to tenant-free login:', cleanLoginUrl);
        
        // STEP 3: Sign out from Supabase (this will trigger auth state change)
        if (window.AuthBootstrap && window.AuthBootstrap.signOut) {
            await AuthBootstrap.signOut();
        }
        
        // STEP 4: Clear app state after successful sign out
        await clearAppState();
        
        // STEP 5: Ensure login page is loaded (redundant but safe)
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
