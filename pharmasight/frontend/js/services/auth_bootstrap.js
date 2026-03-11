/**
 * Auth Bootstrap Service
 * 
 * Centralized authentication state management that:
 * - Initializes once and is refresh-safe
 * - Supports multiple tabs via BroadcastChannel
 * - Never navigates inside auth listeners
 * - Exposes reactive auth state
 */

// Private state (not exposed to window)
let currentUser = null;
let currentSession = null;
let authInitialized = false;
let authInitializing = false;
let authStateListeners = new Set();

// BroadcastChannel for multi-tab sync
const AUTH_CHANNEL_NAME = 'pharmasight_auth';
let authChannel = null;

/**
 * PharmaSight internal auth only.
 * Supabase must not be used for session restoration or identity verification.
 */

/**
 * Initialize BroadcastChannel for multi-tab communication
 */
function initAuthChannel() {
    if (typeof BroadcastChannel === 'undefined') {
        console.warn('BroadcastChannel not supported, multi-tab sync disabled');
        return;
    }
    
    if (!authChannel) {
        authChannel = new BroadcastChannel(AUTH_CHANNEL_NAME);
        
        authChannel.onmessage = (event) => {
            if (event.data.type === 'AUTH_STATE_CHANGE') {
                // Another tab changed auth state, sync
                const { user, session } = event.data;
                if (user !== currentUser?.id || session?.access_token !== currentSession?.access_token) {
                    refreshAuthState();
                }
            }
        };
    }
}

/**
 * Broadcast auth state change to other tabs
 */
function broadcastAuthStateChange(user, session) {
    if (authChannel) {
        authChannel.postMessage({
            type: 'AUTH_STATE_CHANGE',
            user: user?.id || null,
            session: session?.access_token || null,
            timestamp: Date.now()
        });
    }
}

/**
 * Notify all auth state listeners
 */
function notifyAuthStateListeners(user, session) {
    authStateListeners.forEach(callback => {
        try {
            callback(user, session);
        } catch (error) {
            console.error('Error in auth state listener:', error);
        }
    });
}

/**
 * Check if we have a valid internal auth session (Bearer token + user id in storage).
 */
function getInternalAuthState() {
    try {
        if (typeof localStorage === 'undefined') return null;
        const token = localStorage.getItem('pharmasight_access_token');
        const userId = localStorage.getItem('pharmasight_user_id');
        if (!token || !userId) return null;
        return {
            user: { id: userId, email: localStorage.getItem('pharmasight_user_email') || '' },
            session: { access_token: token }
        };
    } catch (_) {
        return null;
    }
}

/**
 * Attempt internal refresh-token rotation via PharmaSight backend.
 */
async function tryRefreshInternalSession() {
    try {
        if (typeof localStorage === 'undefined') return null;
        const refresh = localStorage.getItem('pharmasight_refresh_token');
        const userId = localStorage.getItem('pharmasight_user_id');
        if (!refresh || !userId) return null;
        const base = (typeof CONFIG !== 'undefined' && CONFIG.API_BASE_URL != null) ? CONFIG.API_BASE_URL : '';
        const resp = await fetch(`${base}/api/auth/refresh`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ refresh_token: refresh })
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok || !data || !data.access_token) {
            return null;
        }
        try {
            localStorage.setItem('pharmasight_access_token', data.access_token);
            if (data.refresh_token) localStorage.setItem('pharmasight_refresh_token', data.refresh_token);
        } catch (_) {}
        return getInternalAuthState();
    } catch (_) {
        return null;
    }
}

/**
 * Refresh auth state: internal tokens only (with optional refresh rotation).
 */
async function refreshAuthState() {
    const internal = getInternalAuthState();
    if (internal) {
        currentUser = internal.user;
        currentSession = internal.session;
        notifyAuthStateListeners(currentUser, currentSession);
        return { user: currentUser, session: currentSession };
    }
    const refreshed = await tryRefreshInternalSession();
    if (refreshed) {
        currentUser = refreshed.user;
        currentSession = refreshed.session;
        notifyAuthStateListeners(currentUser, currentSession);
        return { user: currentUser, session: currentSession };
    }
    currentSession = null;
    currentUser = null;
    notifyAuthStateListeners(null, null);
    return { user: null, session: null };
}

/**
 * Initialize auth bootstrap (runs once, refresh-safe)
 */
async function initAuthBootstrap() {
    // Prevent multiple initializations
    if (authInitialized) {
        return { user: currentUser, session: currentSession };
    }
    
    if (authInitializing) {
        // Wait for ongoing initialization
        return new Promise((resolve) => {
            const checkInterval = setInterval(() => {
                if (authInitialized) {
                    clearInterval(checkInterval);
                    resolve({ user: currentUser, session: currentSession });
                }
            }, 50);
        });
    }
    
    authInitializing = true;
    
    // Internal auth only: initialize channel and hydrate from storage/refresh.
    initAuthChannel();
    await refreshAuthState();
    authInitialized = true;
    authInitializing = false;
    return { user: currentUser, session: currentSession };
}

/**
 * Get current user (synchronous, from cache). Prefers internal auth if present.
 */
function getCurrentUser() {
    const internal = getInternalAuthState();
    if (internal) return internal.user;
    return currentUser;
}

/**
 * Get current session (synchronous, from cache). Prefers internal auth if present.
 */
function getCurrentSession() {
    const internal = getInternalAuthState();
    if (internal) return internal.session;
    return currentSession;
}

/**
 * Subscribe to auth state changes
 * @param {Function} callback - Called with (user, session) when auth state changes
 * @returns {Function} Unsubscribe function
 */
function onAuthStateChange(callback) {
    authStateListeners.add(callback);
    
    // Immediately call with current state
    try {
        callback(currentUser, currentSession);
    } catch (error) {
        console.error('Error in initial auth state callback:', error);
    }
    
    // Return unsubscribe function
    return () => {
        authStateListeners.delete(callback);
    };
}

/**
 * Sign in with email and password
 */
async function signIn(email, password) {
    // PharmaSight is the single authentication authority.
    // This method now delegates to the PharmaSight backend and stores internal tokens.
    const base = (typeof CONFIG !== 'undefined' && CONFIG.API_BASE_URL != null) ? CONFIG.API_BASE_URL : '';
    const resp = await fetch(`${base}/api/auth/username-login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: email, password })
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
        const msg = (typeof data.detail === 'string' ? data.detail : (data.detail && data.detail.message)) || data.message || 'Login failed';
        throw new Error(msg);
    }
    if (!data.access_token || !data.refresh_token) {
        throw new Error('Account is not enabled for internal authentication');
    }
    try {
        if (typeof localStorage !== 'undefined') {
            localStorage.setItem('pharmasight_access_token', data.access_token);
            localStorage.setItem('pharmasight_refresh_token', data.refresh_token);
            localStorage.setItem('pharmasight_user_id', data.user_id);
            localStorage.setItem('pharmasight_user_email', data.email || '');
        }
    } catch (_) {}
    // Update cached state immediately
    await refreshAuthState();
    return { user: { id: data.user_id, email: data.email || '' }, session: { access_token: data.access_token } };
}

/**
 * Sign out (clears internal tokens and Supabase session).
 */
async function signOut() {
    try {
        // Best-effort server-side logout (revokes current access token) if available.
        try {
            const base = (typeof CONFIG !== 'undefined' && CONFIG.API_BASE_URL != null) ? CONFIG.API_BASE_URL : '';
            const token = typeof localStorage !== 'undefined' ? localStorage.getItem('pharmasight_access_token') : null;
            if (token) {
                await fetch(`${base}/api/auth/logout`, {
                    method: 'POST',
                    headers: { 'Authorization': 'Bearer ' + token }
                }).catch(() => {});
            }
        } catch (_) {}
        if (typeof localStorage !== 'undefined') {
            localStorage.removeItem('pharmasight_access_token');
            localStorage.removeItem('pharmasight_refresh_token');
            localStorage.removeItem('pharmasight_user_id');
            localStorage.removeItem('pharmasight_user_email');
        }
    } catch (_) {}
    currentUser = null;
    currentSession = null;
    notifyAuthStateListeners(null, null);
    if (authChannel) authChannel.postMessage({ type: 'AUTH_STATE_CHANGE', user: null, session: null, timestamp: Date.now() });
}

/**
 * Update password (for invited users)
 */
async function updatePassword(newPassword) {
    // Supabase auth removed. Password changes are handled via PharmaSight backend endpoints.
    throw new Error('Password update is not available via AuthBootstrap (Supabase auth removed).');
}

/**
 * Check if user needs to set password
 *
 * Semantics:
 * - password_set: true  => user has already set a password via the app
 * - password_set: false => user has NEVER set a password via the app
 *
 * Handles:
 * - Seeded users (is_pending: false, password_set: false, no invitation_token)
 * - Invited users (is_pending: true, password_set: false, invitation_token present)
 * - Ignores password reset flows (handled by password_reset.js)
 *
 * @param {Object} user - The user object
 * @param {string} context - Context: 'login', 'reset', 'normal', 'invitation'
 * @returns {Promise<boolean>} - True if password setup is needed
 */
async function needsPasswordSetup(user, context = 'login') {
    if (!user) return false;
    
    try {
        const localStorageKey = `user_${user.id}_password_set`;
        const cachedPasswordSet = localStorage.getItem(localStorageKey);
        const justSetPassword = sessionStorage.getItem('just_set_password') === 'true';

        // If we've explicitly cached that password is set, or we just set it in this session,
        // trust that and skip remote checks to avoid race conditions.
        if (cachedPasswordSet === 'true' || justSetPassword) {
            console.log('[AUTH] Using cached password_set=true / just_set_password flag');
            return false;
        }

        // Check URL parameters first to determine flow type
        const hash = window.location.hash || '';
        const fullUrl = window.location.href || '';
        
        // Parse URL parameters - handle both hash and full URL formats
        let paramsString = '';
        if (hash.includes('?')) {
            paramsString = hash.split('?')[1];
        } else if (hash.includes('=')) {
            // Hash might be in root format: #key=value&...
            paramsString = hash.replace('#', '');
        } else if (fullUrl.includes('?')) {
            paramsString = fullUrl.split('?')[1].split('#')[0];
        }
        
        const urlParams = new URLSearchParams(paramsString);
        const routeBase = (hash || '').replace('#', '').split('?')[0];
        const isPasswordReset = routeBase === 'password-reset' || routeBase === 'reset-password';
        const hasInvitationTokenInUrl = !!urlParams.get('invitation_token') ||
                                      hash.includes('invitation_token') ||
                                      fullUrl.includes('invitation_token');
        
        // Fetch user profile from API to get persistent flags
        // Add timestamp param to bypass any intermediate caches
        const profile = await API.users.get(user.id, { _t: Date.now() });
        
        console.log('[AUTH] Password setup check for:', user.email);
        console.log('[AUTH] Profile:', {
            password_set: profile?.password_set,
            is_pending: profile?.is_pending,
            hasInvitationToken: !!profile?.invitation_token
        });
        
        // Case 1: Password reset flow - handled entirely by password_reset.js
        if (isPasswordReset) {
            console.log('[AUTH] Password reset flow detected - password_set page not required');
            return false;
        }
        
        // Case 2: User already set password
        if (profile && profile.password_set === true) {
            console.log('[AUTH] User already has password set');
            // Cache for future checks
            localStorage.setItem(localStorageKey, 'true');
            return false;
        }
        
        // Case 3: Invited user with invitation token (URL or profile)
        const hasInvitationToken = hasInvitationTokenInUrl || !!profile?.invitation_token;
        if (hasInvitationToken) {
            console.log('[AUTH] Invited user needs password setup');
            return true;
        }
        
        // Case 4: Seeded user (first login)
        // is_pending: false, password_set: false, no invitation token
        if (profile &&
            profile.is_pending === false &&
            profile.password_set === false &&
            !profile.invitation_token) {
            console.log('[AUTH] Seeded user needs password setup (first login)');
            return true;
        }
        
        // Case 5: All other cases - no password setup
        console.log('[AUTH] No password setup required');
        return false;
        
    } catch (error) {
        console.error('[AUTH] Error checking password setup:', error);
        // On error, default to not requiring password setup (avoid blocking)
        return false;
    }
}

// Export AuthBootstrap service
const AuthBootstrap = {
    init: initAuthBootstrap,
    getCurrentUser,
    getCurrentSession,
    onAuthStateChange,
    signIn,
    signOut,
    updatePassword,
    needsPasswordSetup,
    refresh: refreshAuthState
};

// Expose to window
if (typeof window !== 'undefined') {
    window.AuthBootstrap = AuthBootstrap;
}
