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
let authListener = null;
let currentUser = null;
let currentSession = null;
let authInitialized = false;
let authInitializing = false;
let authStateListeners = new Set();

// BroadcastChannel for multi-tab sync
const AUTH_CHANNEL_NAME = 'pharmasight_auth';
let authChannel = null;

// Store the Supabase client instance once after initialization
let supabaseClientInstance = null;

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
 * Refresh auth state from Supabase
 */
async function refreshAuthState() {
    if (!supabaseClientInstance) return { user: null, session: null };
    
    try {
        const { data: { session }, error: sessionError } = await supabaseClientInstance.auth.getSession();
        if (sessionError) {
            console.error('Error getting session:', sessionError);
            currentSession = null;
            currentUser = null;
        } else {
            currentSession = session;
            currentUser = session?.user || null;
        }
        
        // Notify listeners (but don't navigate here!)
        notifyAuthStateListeners(currentUser, currentSession);
        
        return { user: currentUser, session: currentSession };
    } catch (error) {
        console.error('Error refreshing auth state:', error);
        currentSession = null;
        currentUser = null;
        notifyAuthStateListeners(null, null);
        return { user: null, session: null };
    }
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
    
    try {
        // Initialize Supabase client ONCE and store the result
        if (!window.initSupabaseClient) {
            throw new Error('Supabase client init function not available. Ensure supabase_client.js loads before auth_bootstrap.js');
        }
        
        supabaseClientInstance = window.initSupabaseClient();
        if (!supabaseClientInstance) {
            throw new Error('Supabase client initialization failed');
        }
        
        // Initialize BroadcastChannel
        initAuthChannel();
        
        // Get initial session
        await refreshAuthState();
        
        // Set up auth state change listener
        // CRITICAL: This listener NEVER navigates or calls startAppFlow
        // It ONLY updates state and notifies listeners (UI updates only)
        authListener = supabaseClientInstance.auth.onAuthStateChange((event, session) => {
            console.log('[AUTH BOOTSTRAP] Auth state changed:', event);
            
            currentSession = session;
            currentUser = session?.user || null;
            
            // Broadcast to other tabs
            broadcastAuthStateChange(currentUser, currentSession);
            
            // Notify listeners (ONLY state updates, NO navigation)
            // Listeners should only update UI elements, never navigate
            notifyAuthStateListeners(currentUser, currentSession);
        });
        
        authInitialized = true;
        authInitializing = false;
        
        return { user: currentUser, session: currentSession };
    } catch (error) {
        console.error('Error initializing auth bootstrap:', error);
        authInitializing = false;
        return { user: null, session: null };
    }
}

/**
 * Get current user (synchronous, from cache)
 */
function getCurrentUser() {
    return currentUser;
}

/**
 * Get current session (synchronous, from cache)
 */
function getCurrentSession() {
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
    if (!supabaseClientInstance) {
        throw new Error('Supabase client not initialized');
    }
    
    const { data, error } = await supabaseClientInstance.auth.signInWithPassword({
        email,
        password
    });
    
    if (error) throw error;
    
    // State will be updated by auth listener
    return data;
}

/**
 * Sign out
 */
async function signOut() {
    if (!supabaseClientInstance) {
        return;
    }
    
    try {
        await supabaseClientInstance.auth.signOut();
        // State will be updated by auth listener
    } catch (error) {
        console.error('Sign out error:', error);
        throw error;
    }
}

/**
 * Update password (for invited users)
 */
async function updatePassword(newPassword) {
    if (!supabaseClientInstance) {
        throw new Error('Supabase client not initialized');
    }
    
    const { data, error } = await supabaseClientInstance.auth.updateUser({
        password: newPassword
    });
    
    if (error) throw error;
    
    // State will be updated by auth listener
    return data;
}

/**
 * Check if user needs to set password
 * Uses persistent password_set flag from user profile in database
 */
async function needsPasswordSetup(user) {
    if (!user) return false;
    
    try {
        // Fetch user profile from API to get password_set flag
        const profile = await API.users.get(user.id);
        // password_set is false if user hasn't set password yet
        return profile && profile.password_set === false;
    } catch (error) {
        console.error('Error checking password_set flag:', error);
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
