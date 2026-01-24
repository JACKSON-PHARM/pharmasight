// Main Application Logic

let currentPage = 'dashboard';
let isInitializing = false;
let isNavigatingFromAuth = false; // Prevent redirect loops
let currentScreen = null; // Track current screen to prevent duplicate navigation
let layoutRendered = false; // Track which layout is rendered

/**
 * Check if user is authenticated
 * Single source of truth for auth state
 */
function isAuthenticated() {
    if (!window.AuthBootstrap) {
        return false;
    }
    const session = AuthBootstrap.getCurrentSession();
    return Boolean(session && session.access_token);
}

/**
 * Check if current route is an auth route (login, password-set, etc.)
 */
function isAuthRoute(hash) {
    const authRoutes = ['login', 'password-set', 'password-reset', 'reset-password'];
    const route = hash.replace('#', '').split('?')[0];
    return authRoutes.includes(route) || hash.includes('access_token') || hash.includes('invite');
}

/**
 * Render Auth Layout (Unauthenticated routes only)
 * Contains ONLY login/auth pages - NO sidebar, NO top bar, NO app shell
 */
function renderAuthLayout() {
    if (layoutRendered === 'auth') return; // Already rendered
    
    console.log('[LAYOUT] Rendering Auth Layout');
    
    const authLayout = document.getElementById('authLayout');
    const appLayout = document.getElementById('appLayout');
    
    if (!authLayout || !appLayout) {
        console.error('[LAYOUT] Layout containers not found');
        return;
    }
    
    // Show auth layout, hide app layout
    // CRITICAL: Must use 'flex' not 'block' to prevent container collapse
    // The CSS uses flexbox with align-items/justify-content which requires display: flex
    authLayout.style.display = 'flex';
    authLayout.style.height = '100vh';
    authLayout.style.minHeight = '100vh';
    authLayout.style.width = '100%';
    appLayout.style.display = 'none';
    
    layoutRendered = 'auth';
    
    // Move auth pages to auth layout if needed
    // Pages will be rendered dynamically by their loaders
}

/**
 * Render App Layout (Authenticated routes only)
 * Contains sidebar, top bar, branch selector, and all app pages
 */
function renderAppLayout() {
    if (layoutRendered === 'app') return; // Already rendered
    
    console.log('[LAYOUT] Rendering App Layout');
    
    const authLayout = document.getElementById('authLayout');
    const appLayout = document.getElementById('appLayout');
    
    if (!authLayout || !appLayout) {
        console.error('[LAYOUT] Layout containers not found');
        return;
    }
    
    // Show app layout, hide auth layout
    authLayout.style.display = 'none';
    appLayout.style.display = 'flex';
    
    layoutRendered = 'app';
    
    // Initialize app shell components (sidebar, top bar, navigation)
    // This only runs once when app layout is first rendered
    if (!window.appShellInitialized) {
        initializeAppShell();
        window.appShellInitialized = true;
    }
}

/**
 * Initialize app shell components
 * Called ONLY after AppLayout is rendered (authenticated state)
 */
function initializeAppShell() {
    console.log('[APP SHELL] Initializing app shell components...');
    
    try {
        // Initialize navigation and menu toggle (only for app layout)
        initializeNavigation();
        initializeMenuToggle();
        initializeHashRouting();
        
        // Set up branch change listener (only for app layout)
        if (window.BranchContext) {
            BranchContext.onBranchChange((branch) => {
                if (branch) {
                    console.log('[BRANCH CHANGED] Selected:', branch.name);
                    const user = AuthBootstrap.getCurrentUser();
                    if (user) {
                        updateStatusBar(user);
                    }
                }
            });
        }
    } catch (error) {
        console.error('❌ Error initializing app shell:', error);
    }
}

// Initialize app - AUTH GATE FIRST
document.addEventListener('DOMContentLoaded', async () => {
    console.log('✅ DOM Content Loaded - Initializing app...');
    
    // CRITICAL: Check for password reset token IMMEDIATELY before anything else
    // This must happen before any other processing
    const initialHash = window.location.hash || '';
    const initialUrl = window.location.href;
    const earlyHasAccessToken = initialHash.includes('access_token') || initialUrl.includes('access_token');
    const earlyHasRecoveryType = initialHash.includes('type=recovery') || 
                            initialHash.includes('type%3Drecovery') || 
                            initialUrl.includes('type=recovery') ||
                            initialUrl.includes('type%3Drecovery');
    
    console.log('🔍 [EARLY CHECK] Initial hash:', initialHash);
    console.log('🔍 [EARLY CHECK] Initial URL:', initialUrl);
    console.log('🔍 [EARLY CHECK] Has access_token:', earlyHasAccessToken);
    console.log('🔍 [EARLY CHECK] Has type=recovery:', earlyHasRecoveryType);
    
    // If this is a password reset token, DO NOT REWRITE THE HASH
    // Supabase needs the token in root format: #access_token=...&type=recovery
    if (earlyHasAccessToken && earlyHasRecoveryType && !initialHash.includes('password-reset')) {
        console.log('🚨 [EARLY CHECK] PASSWORD RESET TOKEN DETECTED - NOT modifying hash (Supabase needs root format)');
    }
    
    // Hide loading indicator if it exists
    const loadingIndicator = document.getElementById('appLoading');
    if (loadingIndicator) {
        loadingIndicator.style.display = 'none';
    }
    
    // Hide all layouts initially
    const authLayout = document.getElementById('authLayout');
    const appLayout = document.getElementById('appLayout');
    if (authLayout) authLayout.style.display = 'none';
    if (appLayout) appLayout.style.display = 'none';
    
    // Check if we're on the invite route or have an access token in hash
    // CRITICAL: Don't treat password-reset links as invite links
    const hash = window.location.hash || '';
    const pathname = window.location.pathname || '';
    const fullUrl = window.location.href;
    
    console.log('[INIT] Checking URL for password reset token...');
    console.log('[INIT] Hash:', hash);
    console.log('[INIT] Full URL:', fullUrl);
    
    const isPasswordReset = hash.includes('password-reset');
    
    // Check if this is a password reset token (Supabase format: #access_token=...&type=recovery)
    // Also check full URL in case token is in query params
    const hasAccessToken = hash.includes('access_token') || fullUrl.includes('access_token');
    const hasRecoveryType = hash.includes('type=recovery') || 
                            hash.includes('type%3Drecovery') || 
                            fullUrl.includes('type=recovery') ||
                            fullUrl.includes('type%3Drecovery');
    
    const isPasswordResetToken = hasAccessToken && hasRecoveryType;
    
    console.log('[INIT] isPasswordReset:', isPasswordReset);
    console.log('[INIT] hasAccessToken:', hasAccessToken);
    console.log('[INIT] hasRecoveryType:', hasRecoveryType);
    console.log('[INIT] isPasswordResetToken:', isPasswordResetToken);
    
    // Persist a flag for password reset flow so we can still detect it after Supabase cleans the hash
    if (isPasswordResetToken) {
        window.__PASSWORD_RESET_TOKEN_PRESENT = true;
        window.__PASSWORD_RESET_ORIGINAL_URL = fullUrl;
        console.log('[PASSWORD RESET] Stored recovery token flag on window.__PASSWORD_RESET_TOKEN_PRESENT');
    }
    
    // If it's a password reset token but not already on password-reset page, go straight to password reset form
    if (isPasswordResetToken && !isPasswordReset) {
        console.log('[PASSWORD RESET] ✅ Detected password reset token in URL');
        
        // DO NOT REWRITE THE HASH - Supabase needs it in root format
        console.log('[PASSWORD RESET] Token format is correct for Supabase, not modifying hash');
        
        // Initialize auth bootstrap first (needed for Supabase recovery session)
        try {
            console.log('🔐 Initializing Auth Bootstrap for password reset...');
            await AuthBootstrap.init();
        } catch (error) {
            console.error('Error initializing auth bootstrap:', error);
        }
        
        // Always stay in auth layout for recovery
        renderAuthLayout();
        
        // BYPASS generic router: load password reset UI directly
        if (typeof window.loadPasswordReset === 'function') {
            console.log('[PASSWORD RESET] 🚀 Calling window.loadPasswordReset() directly (bypassing router)');
            window.loadPasswordReset();
        } else {
            console.error('[PASSWORD RESET] ❌ window.loadPasswordReset is not defined – falling back to loadPage(\"password-reset\")');
            loadPage('password-reset');
        }
        
        return; // CRITICAL: Stop here, don't continue with normal auth flow
    }
    
    // Only treat as invite if it's not a password reset link
    if (!isPasswordReset && !isPasswordResetToken && (hash.includes('access_token') || pathname === '/invite' || hash.includes('#invite'))) {
        console.log('[INVITE] Detected invite link');
        await renderInviteHandler();
        return; // Don't continue with normal auth flow
    }
    
    try {
        // STEP 1: Initialize Auth Bootstrap FIRST (before any layout decision)
        console.log('🔐 Initializing Auth Bootstrap...');
        await AuthBootstrap.init();
        
        // STEP 2: Check authentication status
        const authenticated = isAuthenticated();
        const routeHash = window.location.hash || '';
        const isAuthRoute_ = isAuthRoute(routeHash);
        
        // Check if this is a password reset/recovery flow
        // Recovery sessions should stay in auth layout even if authenticated
        const isRecoveryTokenFlow = routeHash.includes('access_token') && 
                                   (routeHash.includes('type=recovery') || routeHash.includes('type%3Drecovery'));
        
        // STEP 3: Render appropriate layout based on auth state
        // CRITICAL: Recovery token flows must stay in auth layout even if authenticated
        if (!authenticated || isAuthRoute_ || isRecoveryTokenFlow) {
            // UNAUTHENTICATED OR AUTH ROUTE OR RECOVERY FLOW: Render Auth Layout
            if (isRecoveryTokenFlow) {
                console.log('[AUTH GATE] Recovery token detected, rendering Auth Layout (even though authenticated)');
            } else {
                console.log('[AUTH GATE] User not authenticated or auth route, rendering Auth Layout');
            }
            renderAuthLayout();
            
            // Set up auth state listener (only updates UI, never navigates for password recovery)
            AuthBootstrap.onAuthStateChange((user, session) => {
                const hashNow = window.location.hash || '';
                const isRecoveryToken =
                    hashNow.includes('access_token') &&
                    (hashNow.includes('type=recovery') || hashNow.includes('type%3Drecovery'));
                const isPasswordResetRoute = hashNow.includes('password-reset');

                // For normal sign-ins (not password recovery), switch to app layout
                if (user && session && !isRecoveryToken && !isPasswordResetRoute) {
                    console.log('[AUTH STATE CHANGE] User logged in, switching to App Layout');
                    renderAppLayout();
                    // Reset screen tracking for new layout
                    currentScreen = null;
                    // Start app flow
                    startAppFlow();
                } else if (isRecoveryToken || isPasswordResetRoute) {
                    // For recovery sessions, stay in auth layout so password-reset page can handle update
                    console.log('[AUTH STATE CHANGE] Password recovery session detected, staying in Auth Layout');
                }
            });
            
            // Load appropriate auth page
            // Ensure hash is set to login if it's pointing to an app route
            let route = routeHash.replace('#', '').split('?')[0] || 'login';
            const appRoutes = ['dashboard', 'sales', 'purchases', 'inventory', 'settings', 'reports', 'expenses', 'branch-select'];
            if (!isAuthRoute_ && appRoutes.includes(route)) {
                // Hash is pointing to app route but not authenticated - force login
                route = 'login';
                window.location.hash = '#login';
                window.history.replaceState(null, '', window.location.href.split('#')[0] + '#login');
            }
            loadPage(route);
            
        } else {
            // AUTHENTICATED: Render App Layout (full shell with sidebar, top bar)
            console.log('[AUTH GATE] User authenticated, rendering App Layout');
            
            // Initialize branch context (only for authenticated users)
            if (window.BranchContext) {
                BranchContext.init();
            }
            
            renderAppLayout();
            
            // Set up auth state listener for authenticated state
            AuthBootstrap.onAuthStateChange((user, session) => {
                if (!user || !session) {
                    // User logged out - FORCE immediate switch to auth layout and login
                    console.log('[AUTH STATE CHANGE] User logged out, forcing auth layout and login...');
                    
                    // CRITICAL: Force auth layout FIRST before any routing
                    renderAuthLayout();
                    
                    // Force hash to login immediately (before any async operations)
                    const currentHash = window.location.hash.replace('#', '');
                    const appRoutes = ['dashboard', 'sales', 'purchases', 'inventory', 'settings', 'reports', 'expenses', 'branch-select', 'password-set'];
                    
                    if (appRoutes.includes(currentHash) || !currentHash || currentHash === '') {
                        console.log('[AUTH STATE CHANGE] Redirecting from app route to login:', currentHash);
                        window.location.hash = '#login';
                        window.history.replaceState(null, '', window.location.href.split('#')[0] + '#login');
                    }
                    
                    // Reset screen tracking
                    currentScreen = null;
                    
                    // Load login page immediately
                    if (window.loadLogin) {
                        window.loadLogin();
                    } else {
                        loadPage('login');
                    }
                    
                    // Clear UI
                    updateUserUI(null);
                } else {
                    // User still logged in - update UI state only (no navigation)
                    if (layoutRendered === 'app') {
                        updateUserUI(user);
                    }
                }
            });
            
            // Start app routing flow
            await startAppFlow();
        }
        
    } catch (error) {
        console.error('❌ Error during app initialization:', error);
        // Fallback to auth layout
        renderAuthLayout();
        loadPage('login');
    }
    
    console.log('✅ App initialization complete');
});

/**
 * Initialize hash-based routing
 * Handles browser back/forward buttons and direct hash navigation
 */
function initializeHashRouting() {
    // Listen for hash changes (browser back/forward, direct navigation)
    window.addEventListener('hashchange', () => {
        // If we're in the middle of a password reset recovery flow, ignore hash changes
        if (window.__PASSWORD_RESET_TOKEN_PRESENT === true) {
            console.log('[HASH ROUTING] Password reset flow active, ignoring hashchange event');
            return;
        }

        const hash = window.location.hash.replace('#', '') || 'dashboard';
        console.log('[HASH ROUTING] Hash changed to:', hash);
        
        // Check authentication FIRST before any routing
        const authenticated = isAuthenticated();
        const authRoutes = ['login', 'password-set', 'password-reset', 'reset-password'];
        const isAuthRoute = authRoutes.includes(hash);
        
        // CRITICAL: If not authenticated and trying to access app route, force login immediately
        if (!authenticated && !isAuthRoute) {
            console.log('[HASH ROUTING] Not authenticated, redirecting to login from:', hash);
            renderAuthLayout();
            window.location.hash = '#login';
            window.history.replaceState(null, '', window.location.href.split('#')[0] + '#login');
            if (window.loadLogin) {
                window.loadLogin();
            }
            return;
        }
        
        // Handle auth routes
        // CRITICAL: Check for recovery token - these should always go to password-reset page
        const isRecoveryToken = hash.includes('access_token') && 
                               (hash.includes('type=recovery') || hash.includes('type%3Drecovery'));
        if (isRecoveryToken) {
            console.log('[HASH ROUTING] Recovery token detected, forcing password-reset route');
            loadPage('password-reset');
            return;
        }
        
        if (isAuthRoute || hash === 'setup' || hash === 'invite') {
            loadPage(hash);
            return;
        }
        
        // For authenticated app routes, check if branch is selected
        if (authenticated) {
            const branch = BranchContext.getBranch();
            if (!branch && hash !== 'branch-select' && hash !== 'setup') {
                // No branch selected, redirect to branch selection
                loadPage('branch-select');
                return;
            }
        }
        
        // Load the requested page
        loadPage(hash);
    });
    
    // Handle initial hash if present
    const initialHash = window.location.hash.replace('#', '');
    if (initialHash && initialHash !== 'login' && initialHash !== 'password-set' && initialHash !== 'branch-select') {
        // Initial hash navigation will be handled by startAppFlow, but we can set it up
        console.log('[HASH ROUTING] Initial hash detected:', initialHash);
    }
}

/**
 * Handle invite link from Supabase email
 */
async function renderInviteHandler() {
    console.log('[INVITE] Handling invite link');
    
    // Show loading UI
    const invitePage = document.getElementById('invite');
    if (invitePage) {
        invitePage.classList.add('active');
        invitePage.style.display = 'block';
        invitePage.style.visibility = 'visible';
        invitePage.innerHTML = `
            <div style="display: flex; justify-content: center; align-items: center; min-height: 100vh; flex-direction: column; gap: 1rem;">
                <div style="border: 4px solid #f3f3f3; border-top: 4px solid #3498db; border-radius: 50%; width: 50px; height: 50px; animation: spin 1s linear infinite;"></div>
                <p>Processing invitation...</p>
            </div>
            <style>
                @keyframes spin {
                    0% { transform: rotate(0deg); }
                    100% { transform: rotate(360deg); }
                }
            </style>
        `;
    }
    
    try {
        // Initialize Supabase if not already initialized
        Auth.initSupabase();
        
        // Supabase automatically parses access_token from hash when getSession() is called
        // Wait a moment for Supabase to process the hash
        await new Promise(resolve => setTimeout(resolve, 1000));
        
        // Get Supabase client from shared module
        const supabaseClient = window.initSupabaseClient ? window.initSupabaseClient() : null;
        if (supabaseClient) {
            const { data, error } = await supabaseClient.auth.getSession();
            
            if (error || !data?.session) {
                console.error('[INVITE] Invalid or expired invitation link:', error);
                if (invitePage) {
                    invitePage.innerHTML = `
                        <div style="display: flex; justify-content: center; align-items: center; min-height: 100vh; flex-direction: column; gap: 1rem; padding: 2rem;">
                            <i class="fas fa-exclamation-triangle" style="font-size: 3rem; color: #e74c3c;"></i>
                            <h2>Invalid or Expired Invitation</h2>
                            <p>The invitation link is invalid or has expired.</p>
                            <button class="btn btn-primary" onclick="window.location.hash = '#login'">Go to Login</button>
                        </div>
                    `;
                } else {
                    alert('Invalid or expired invitation link');
                    window.location.hash = '#login';
                }
                return;
            }
            
            console.log('[INVITE] Invite session accepted');
            
            // User is now authenticated
            // Clear the pathname and hash to remove the token
            window.history.replaceState(null, '', window.location.origin + '/');
            
            // Initialize auth bootstrap if not already done
            await AuthBootstrap.init();
            
            // Refresh auth state
            await AuthBootstrap.refresh();
            
            // Continue with normal app flow (will handle password set, branch select, etc.)
            await startAppFlow();
        } else {
            throw new Error('Supabase not configured');
        }
    } catch (error) {
        console.error('[INVITE] Error handling invite:', error);
        if (invitePage) {
            invitePage.innerHTML = `
                <div style="display: flex; justify-content: center; align-items: center; min-height: 100vh; flex-direction: column; gap: 1rem; padding: 2rem;">
                    <i class="fas fa-exclamation-triangle" style="font-size: 3rem; color: #e74c3c;"></i>
                    <h2>Error Processing Invitation</h2>
                    <p>${error.message || 'An error occurred while processing the invitation link.'}</p>
                    <button class="btn btn-primary" onclick="window.location.hash = '#login'">Go to Login</button>
                </div>
            `;
        } else {
            alert('Error processing invitation link. Please try again.');
            window.location.hash = '#login';
        }
    }
}

/**
 * Start app routing flow
 * Determines which screen to show based on auth state
 * IDEMPOTENT: Uses currentScreen guard to prevent duplicate navigation
 */
async function startAppFlow() {
    // Guard: Prevent multiple simultaneous calls
    if (isInitializing) {
        console.log('[APP FLOW] Already initializing, skipping...');
        return;
    }

    // If a password reset recovery flow is active, do NOT run normal app routing.
    // The password-reset page is responsible for handling the flow and redirecting to login.
    if (window.__PASSWORD_RESET_TOKEN_PRESENT === true) {
        console.log('[APP FLOW] Password reset flow active, skipping startAppFlow routing');
        return;
    }
    
    // GUARD: If user is on branch-select route, do NOT redirect away from it.
    // Branch selection must be user-invoked only, and startAppFlow should not interfere.
    const currentHash = window.location.hash || '';
    const hashRoute = currentHash.replace('#', '').split('?')[0];
    if (hashRoute === 'branch-select') {
        console.log('[APP FLOW] User is on branch-select route, skipping redirect checks to allow user selection');
        isInitializing = false;
        return;
    }
    
    isInitializing = true;
    
    try {
        // Get current user (from cache, fast)
        const user = AuthBootstrap.getCurrentUser();
        
        if (!user) {
            // Not authenticated - show login
            if (currentScreen !== 'login') {
                console.log('👤 User not authenticated, showing login page...');
                currentScreen = 'login';
                loadPage('login');
            }
            isInitializing = false;
            return;
        }
        
        console.log('✅ User authenticated:', user.email || user.id);
        
        // Update UI
        updateUserUI(user);
        CONFIG.USER_ID = user.id;
        saveConfig();
        
        // Check if password setup is needed (for invited users)
        // Uses persistent password_set flag from user profile
        // GUARD: Do NOT redirect to password-set if we're already on branch-select route
        // (user may have already set password but flag not updated yet, or in transition)
        const currentHashForCheck = window.location.hash || '';
        const hashRouteForCheck = currentHashForCheck.replace('#', '').split('?')[0];
        const needsPassword = await AuthBootstrap.needsPasswordSetup(user);
        if (needsPassword && hashRouteForCheck !== 'branch-select') {
            if (currentScreen !== 'password-set') {
                console.log('🔑 Password setup required');
                currentScreen = 'password-set';
                loadPage('password-set');
            }
            isInitializing = false;
            return;
        }
        
        // Check if company setup is needed
        let needsSetup = false;
        try {
            const redirect = await Promise.race([
                Auth.shouldRedirectToSetup(),
                new Promise((_, reject) => setTimeout(() => reject(new Error('Timeout')), 5000))
            ]);
            needsSetup = redirect.redirect === 'setup';
        } catch (error) {
            console.warn('Setup check timed out:', error);
        }
        
        if (needsSetup) {
            if (currentScreen !== 'setup') {
                console.log('⚙️ Setup required, redirecting to setup wizard...');
                currentScreen = 'setup';
                loadPage('setup');
            }
            isInitializing = false;
            return;
        }
        
        // Check if branch is selected and validate access
        const branch = BranchContext.getBranch();
        
        if (!branch) {
            // No branch selected - show branch selection
            if (currentScreen !== 'branch-select') {
                console.log('🌳 No branch selected, showing branch selection...');
                currentScreen = 'branch-select';
                loadPage('branch-select');
            }
            isInitializing = false;
            return;
        }
        
        // Validate branch access on refresh (re-validate branch exists and user has access)
        try {
            const branchValid = await validateBranchAccess(branch.id);
            if (!branchValid) {
                // Branch no longer accessible - clear and show selection
                console.log('🌳 Branch access invalid, clearing selection...');
                BranchContext.clearBranch();
                if (currentScreen !== 'branch-select') {
                    currentScreen = 'branch-select';
                    loadPage('branch-select');
                }
                isInitializing = false;
                return;
            }
        } catch (error) {
            console.error('Error validating branch access:', error);
            // On error, allow continuation (don't block user)
        }
        
        // All checks passed - show dashboard
        if (currentScreen !== 'dashboard') {
            console.log('✅ All checks passed, showing dashboard...');
            currentScreen = 'dashboard';
            await updateStatusBar(user);
            loadPage('dashboard');
        }
        
    } catch (error) {
        console.error('Error in app flow:', error);
        if (currentScreen !== 'login') {
            currentScreen = 'login';
            loadPage('login');
        }
    } finally {
        isInitializing = false;
    }
}

/**
 * Validate branch access - re-validate on refresh
 * Checks if branch exists and user has access
 */
async function validateBranchAccess(branchId) {
    try {
        // Try to fetch branch - if it fails, user doesn't have access
        const branch = await API.branch.get(branchId);
        // Also check if branch is active
        return branch && branch.is_active !== false;
    } catch (error) {
        console.warn('Branch access validation failed:', error);
        return false;
    }
}

/**
 * Update user UI elements
 * Only called when app layout is active (authenticated state)
 */
function updateUserUI(user) {
    // Only update UI if app layout is rendered
    if (layoutRendered !== 'app') {
        return; // Don't update UI elements that don't exist in auth layout
    }
    
    // Update username display
    const usernameSpan = document.getElementById('username');
    if (usernameSpan) {
        usernameSpan.textContent = user?.email || user?.user_metadata?.full_name || 'User';
    }
    
    // Show/hide sidebar and logout button (only in app layout)
    const sidebar = document.getElementById('sidebar');
    const logoutBtnTop = document.getElementById('logoutBtnTop');
    
    if (sidebar) {
        sidebar.style.display = user ? 'flex' : 'none';
    }
    
    // Show/hide top bar logout button (only when authenticated)
    if (logoutBtnTop) {
        logoutBtnTop.style.display = user ? 'block' : 'none';
    }
}

/**
 * Handle password set completion
 */
window.handlePasswordSetComplete = async function() {
    console.log('[PASSWORD SET COMPLETE] Continuing app flow...');
    // Refresh auth state
    await AuthBootstrap.refresh();
    // Reset currentScreen to allow navigation
    currentScreen = null;
    // Continue app flow
    await startAppFlow();
};

/**
 * Handle branch selection
 */
window.handleBranchSelected = async function() {
    console.log('[BRANCH SELECTED] Continuing app flow...');
    
    // Show sidebar and top bar now that branch is selected
    const sidebar = document.getElementById('sidebar');
    const topBar = document.querySelector('.top-bar');
    if (sidebar) sidebar.style.display = 'flex';
    if (topBar) topBar.style.display = 'flex';
    
    // Update status bar
    const user = AuthBootstrap.getCurrentUser();
    if (user) {
        await updateStatusBar(user);
    }
    // Reset currentScreen and navigate to dashboard
    currentScreen = null;
    await startAppFlow();
};

// Sub-navigation definitions
window.subNavItems = {
    sales: [
        { page: 'sales', subPage: 'pos', label: 'Point of Sale', icon: 'fa-cash-register' },
        { page: 'sales', subPage: 'invoices', label: 'Sales Invoices', icon: 'fa-file-invoice-dollar' },
        { page: 'sales-history', label: 'Sales History', icon: 'fa-history' },
        { page: 'sales-returns', label: 'Returns', icon: 'fa-undo' }
    ],
    purchases: [
        { page: 'purchases', subPage: 'orders', label: 'Purchase Orders', icon: 'fa-file-invoice' },
        { page: 'purchases', subPage: 'invoices', label: 'Purchase Invoices', icon: 'fa-file-invoice-dollar' },
        { page: 'purchases', subPage: 'credit-notes', label: 'Credit Notes', icon: 'fa-file-invoice' },
        { page: 'purchases', subPage: 'suppliers', label: 'Suppliers', icon: 'fa-truck' }
    ],
    inventory: [
        { page: 'inventory', subPage: 'items', label: 'Items', icon: 'fa-box' },
        { page: 'inventory', subPage: 'batch', label: 'Batch Tracking', icon: 'fa-tags' },
        { page: 'inventory', subPage: 'expiry', label: 'Expiry Report', icon: 'fa-calendar-times' },
        { page: 'inventory', subPage: 'movement', label: 'Item Movement', icon: 'fa-exchange-alt' },
        { page: 'inventory', subPage: 'stock', label: 'Current Stock', icon: 'fa-chart-bar' }
    ],
    expenses: [
        { page: 'expenses', label: 'All Expenses', icon: 'fa-money-bill-wave' },
        { page: 'expenses-categories', label: 'Categories', icon: 'fa-folder' },
        { page: 'expenses-reports', label: 'Reports', icon: 'fa-chart-pie' }
    ],
    reports: [
        { page: 'reports-sales', label: 'Sales Reports', icon: 'fa-chart-line' },
        { page: 'reports-inventory', label: 'Inventory Reports', icon: 'fa-warehouse' },
        { page: 'reports-financial', label: 'Financial Reports', icon: 'fa-dollar-sign' },
        { page: 'reports-custom', label: 'Custom Reports', icon: 'fa-file-alt' }
    ],
    settings: [
        { page: 'settings', subPage: 'general', label: 'General Settings', icon: 'fa-cog' },
        { page: 'settings', subPage: 'company', label: 'Company', icon: 'fa-building' },
        { page: 'settings', subPage: 'branches', label: 'Branches', icon: 'fa-code-branch' },
        { page: 'settings', subPage: 'users', label: 'Users & Roles', icon: 'fa-users' },
        { page: 'settings', subPage: 'transaction', label: 'Transaction', icon: 'fa-receipt' }
    ]
};

// Global navigation state
let isNavigating = false;
let navigationDebounceTimer = null;

// Navigation functions (global scope for accessibility)
function showMainNav() {
    if (isNavigating) return; // Prevent multiple rapid calls
    isNavigating = true;
    
    const sidebar = document.getElementById('sidebar');
    const mainNav = document.getElementById('mainNav');
    const subNav = document.getElementById('subNav');
    
    if (!sidebar || !mainNav || !subNav) {
        isNavigating = false;
        return;
    }
    
    // Use requestAnimationFrame for smooth transitions
    requestAnimationFrame(() => {
        sidebar.classList.remove('showing-sub');
        mainNav.style.display = 'flex';
        subNav.style.display = 'none';
        
        // Reset flag after transition
        setTimeout(() => {
            isNavigating = false;
        }, 300);
    });
}

function showSubNav(pageKey, title) {
    if (isNavigating) return; // Prevent multiple rapid calls
    isNavigating = true;
    
    const sidebar = document.getElementById('sidebar');
    const mainNav = document.getElementById('mainNav');
    const subNav = document.getElementById('subNav');
    const subNavItemsContainer = document.getElementById('subNavItems');
    const subNavTitle = document.getElementById('subNavTitle');
    
    if (!sidebar || !mainNav || !subNav || !subNavItemsContainer || !subNavTitle) {
        isNavigating = false;
        return;
    }
    
    const items = window.subNavItems && window.subNavItems[pageKey];
    if (!items) {
        isNavigating = false;
        return;
    }
    
    subNavTitle.textContent = title;
    subNavItemsContainer.innerHTML = items.map(item => `
        <a href="#" class="sub-nav-item" data-page="${item.page}" ${item.subPage ? `data-sub-page="${item.subPage}"` : ''}>
            <i class="fas ${item.icon}"></i>
            <span>${item.label}</span>
        </a>
    `).join('');
    
    // Add click handlers to sub-nav items (use event delegation for better performance)
    subNavItemsContainer.addEventListener('click', function subNavClickHandler(e) {
        const subItem = e.target.closest('.sub-nav-item');
        if (!subItem) return;
        
        e.preventDefault();
        
        // Debounce rapid clicks
        if (navigationDebounceTimer) {
            clearTimeout(navigationDebounceTimer);
        }
        
        navigationDebounceTimer = setTimeout(() => {
            const page = subItem.dataset.page;
            const subPage = subItem.dataset.subPage;
            
            // Update active state
            subNavItemsContainer.querySelectorAll('.sub-nav-item').forEach(nav => nav.classList.remove('active'));
            subItem.classList.add('active');
            
            // Load page
            if (subPage) {
                // For inventory, set the sub-page
                if (page === 'inventory' && window.switchInventorySubPage) {
                    loadPage(page);
                    setTimeout(() => {
                        if (window.switchInventorySubPage) {
                            window.switchInventorySubPage(subPage);
                        }
                    }, 100);
                } else if (page === 'purchases') {
                    // For purchases, load the page first, then switch to sub-page if specified
                    loadPage(page);
                    if (subPage && window.switchPurchaseSubPage) {
                        setTimeout(() => {
                            window.switchPurchaseSubPage(subPage);
                        }, 100);
                    } else if (!subPage && window.loadPurchases) {
                        // If no sub-page specified, ensure default sub-page loads
                        setTimeout(() => {
                            window.loadPurchases();
                        }, 100);
                    }
                } else if (page === 'sales') {
                    // For sales, load the page first, then switch to sub-page if specified
                    loadPage(page);
                    if (subPage && window.switchSalesSubPage) {
                        setTimeout(() => {
                            window.switchSalesSubPage(subPage);
                        }, 100);
                    } else if (!subPage && window.loadSales) {
                        setTimeout(() => {
                            window.loadSales();
                        }, 100);
                    }
                } else if (page === 'settings') {
                    // For settings, load the page with sub-page
                    loadPage(subPage ? `${page}-${subPage}` : page);
                    if (subPage && window.loadSettingsSubPage) {
                        setTimeout(() => {
                            window.loadSettingsSubPage(subPage);
                        }, 100);
                    }
                } else {
                    loadPage(page);
                }
            } else {
                loadPage(page);
            }
        }, 150);
    }, { once: false, passive: false });
    
    // Use requestAnimationFrame for smooth transitions
    requestAnimationFrame(() => {
        sidebar.classList.add('showing-sub');
        mainNav.style.display = 'none';
        subNav.style.display = 'flex';
        
        // Reset flag after transition
        setTimeout(() => {
            isNavigating = false;
        }, 300);
    });
}

// Navigation
function initializeNavigation() {
    const sidebar = document.getElementById('sidebar');
    const mainNav = document.getElementById('mainNav');
    const subNav = document.getElementById('subNav');
    const sidebarToggle = document.getElementById('sidebarToggle');
    const backToMainNav = document.getElementById('backToMainNav');
    
    if (!sidebar || !mainNav || !subNav) {
        console.error('Navigation elements not found');
        return;
    }
    
    // Sidebar collapse/expand toggle
    if (sidebarToggle) {
        sidebarToggle.addEventListener('click', (e) => {
            e.stopPropagation();
            e.preventDefault();
            
            // Debounce rapid clicks
            if (navigationDebounceTimer) {
                clearTimeout(navigationDebounceTimer);
            }
            
            navigationDebounceTimer = setTimeout(() => {
                sidebar.classList.toggle('collapsed');
                // If showing sub-nav, go back to main nav when collapsing
                if (sidebar.classList.contains('showing-sub') && sidebar.classList.contains('collapsed')) {
                    showMainNav();
                }
            }, 100);
        }, { passive: false });
    }
    
    // Back to main nav button - use event delegation
    if (backToMainNav) {
        backToMainNav.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            
            // Debounce rapid clicks
            if (navigationDebounceTimer) {
                clearTimeout(navigationDebounceTimer);
            }
            
            navigationDebounceTimer = setTimeout(() => {
                showMainNav();
            }, 100);
        }, { passive: false });
    }
    
    // Main nav items - use event delegation for better performance
    if (mainNav) {
        mainNav.addEventListener('click', (e) => {
            const navItem = e.target.closest('.nav-item');
            if (!navItem) return;
            
            e.preventDefault();
            e.stopPropagation();
            
            // Debounce rapid clicks
            if (navigationDebounceTimer) {
                clearTimeout(navigationDebounceTimer);
            }
            
            navigationDebounceTimer = setTimeout(() => {
                const page = navItem.dataset.page;
                const hasSub = navItem.dataset.hasSub === 'true';
                
                if (hasSub && window.subNavItems && window.subNavItems[page]) {
                    // Show sub-navigation
                    showSubNav(page, navItem.querySelector('span')?.textContent || page);
                } else {
                    // Direct page navigation (no sub-items)
                    loadPage(page);
                    showMainNav();
                    
                    // Update active state
                    document.querySelectorAll('.nav-item').forEach(nav => nav.classList.remove('active'));
                    navItem.classList.add('active');
                }
            }, 150);
        }, { passive: false });
    }
}

// Export navigation functions globally
window.showMainNav = showMainNav;
window.showSubNav = showSubNav;

// Menu toggle (mobile)
function initializeMenuToggle() {
    const menuToggle = document.getElementById('menuToggle');
    const sidebar = document.getElementById('sidebar');
    
    if (menuToggle) {
        menuToggle.addEventListener('click', () => {
            sidebar.classList.toggle('open');
        });
    }
}

// Load page
function loadPage(pageName) {
    console.log('📄 Loading page:', pageName);
    currentPage = pageName;
    
    // BEFORE loading any page, check if this is a password reset link
    const currentHash = window.location.hash || '';
    
    // Check for password reset token
    if (currentHash.includes('access_token') && (currentHash.includes('type=recovery') || currentHash.includes('type%3Drecovery'))) {
        console.log('🔧 [ROUTER] Password reset link detected, forcing password-reset route');
        
        // DO NOT REWRITE THE HASH - Supabase needs token in root format: #access_token=...&type=recovery
        console.log('🔧 [ROUTER] Token format is correct for Supabase, not modifying hash');
        
        // CRITICAL: Always set pageName to 'password-reset' when token is present
        // This ensures isAuthPage check passes
        pageName = 'password-reset';
        currentPage = 'password-reset';
        console.log('✅ [ROUTER] Forced pageName to password-reset');
    }
    
    // Check if this is an auth route
    const authRoutes = ['login', 'password-set', 'password-reset', 'reset-password'];
    const isAuthPage = authRoutes.includes(pageName);
    const authenticated = isAuthenticated();
    
    // Check if this is a password reset/recovery flow
    // Recovery sessions are temporary and should allow password-reset page
    // (currentHash already declared above)
    const isRecoveryToken = currentHash.includes('access_token') && 
                           (currentHash.includes('type=recovery') || currentHash.includes('type%3Drecovery'));
    const isPasswordResetFlow = (pageName === 'password-reset' || pageName === 'reset-password') && isRecoveryToken;
    
    // ENFORCE LAYOUT ISOLATION: App pages must use App Layout and require auth
    // CRITICAL: This check happens FIRST to prevent app pages from loading in auth layout
    if (!isAuthPage && !authenticated) {
        console.warn('[ROUTING] App page requested but user is not authenticated, forcing login...');
        // Force auth layout immediately
        renderAuthLayout();
        // Force hash to login
        window.location.hash = '#login';
        window.history.replaceState(null, '', window.location.href.split('#')[0] + '#login');
        // Update page name to login
        pageName = 'login';
        currentPage = 'login';
    }
    
    // ENFORCE LAYOUT ISOLATION: Auth pages must use Auth Layout
    // EXCEPTION: Allow password-reset page even when authenticated if it's a recovery token
    // GUARD: Do NOT redirect away from branch-select route - user must select branch manually
    const hashRoute = currentHash.replace('#', '').split('?')[0];
    const isOnBranchSelectRoute = hashRoute === 'branch-select';
    if (isAuthPage && authenticated && !isPasswordResetFlow && layoutRendered !== 'auth' && !isOnBranchSelectRoute) {
        console.warn('[ROUTING] Auth page requested but user is authenticated, redirecting to dashboard...');
        // Don't load auth pages in app layout - redirect to dashboard
        // UNLESS it's a password reset flow with recovery token
        // UNLESS user is on branch-select route (must allow user to select branch)
        pageName = 'dashboard';
        currentPage = 'dashboard';
    }
    
    // Ensure correct layout is rendered before proceeding
    if (isAuthPage && layoutRendered !== 'auth') {
        renderAuthLayout();
    } else if (!isAuthPage && authenticated && layoutRendered !== 'app') {
        renderAppLayout();
    }
    
    // Handle sub-pages (e.g., settings-company, purchases-orders)
    // CRITICAL: Don't split auth pages like 'password-reset' or 'password-set'
    let mainPage = pageName;
    let subPage = null;
    // Pages that should NOT be split into main/sub by the '-' character
    // (includes auth pages and special app pages like 'branch-select')
    const authPages = ['password-reset', 'password-set', 'reset-password', 'branch-select'];
    if (pageName.includes('-') && !authPages.includes(pageName)) {
        const parts = pageName.split('-');
        mainPage = parts[0];
        subPage = parts.slice(1).join('-');
    }
    
    // Update URL hash
    try {
        const currentHash = window.location.hash || '';
        
        // Special handling for password reset pages with tokens
        if (pageName === 'password-reset' && currentHash.includes('access_token') && currentHash.includes('type=recovery')) {
            // DO NOT REWRITE THE HASH - Supabase needs token in root format
            console.log('🔧 [HASH] Password reset token detected, not modifying hash');
            
            // Only add route prefix if hash is pure token (starts with #access_token) and doesn't have route yet
            if (currentHash.startsWith('#access_token') && !currentHash.includes('password-reset')) {
                // Add route prefix without breaking the token format
                const newHash = `#password-reset/${currentHash.substring(1)}`;
                window.history.replaceState(null, null, window.location.pathname + newHash);
                console.log('✅ [HASH] Added route prefix while preserving token format');
            }
        } else if (pageName !== 'password-reset') {
            // Normal hash update for other pages
            window.location.hash = `#${pageName}`;
        }
        // For password-reset without token, let the default hash update happen
    } catch (e) {
        console.warn('Could not update URL hash:', e);
    }
    
    // CRITICAL FIX: For auth pages, ensure the page element exists BEFORE hide/show logic
    // This prevents "Found 0 page elements" error and ensures element exists for visibility checks
    let pageElement = null;
    if (isAuthPage) {
        const authLayout = document.getElementById('authLayout');
        pageElement = document.getElementById(mainPage);
        
        // CRITICAL: Create the page element if it doesn't exist
        // This must happen BEFORE hide/show logic so the element exists when we search for it
        if (!pageElement && authLayout) {
            console.log(`[AUTH PAGE] Creating ${mainPage} page element in auth layout`);
            const pageDiv = document.createElement('div');
            pageDiv.id = mainPage;
            pageDiv.className = 'page';
            authLayout.appendChild(pageDiv);
            pageElement = pageDiv;
        }
    }
    
    // Hide all pages (explicitly set display: none to override any inline styles)
    // Search in the appropriate layout container
    const container = isAuthPage ? document.getElementById('authLayout') : document.getElementById('appLayout');
    const allPages = container ? container.querySelectorAll('.page') : document.querySelectorAll('.page');
    console.log(`📄 Found ${allPages.length} page elements in ${isAuthPage ? 'auth' : 'app'} layout`);
    allPages.forEach(page => {
        page.classList.remove('active');
        page.style.display = 'none';
        page.style.visibility = 'hidden';
    });
    
    // Show selected page (use mainPage for element ID)
    // For auth pages, pageElement may already be set above; otherwise get it
    if (!pageElement) {
        pageElement = document.getElementById(mainPage);
    }
    
    // For app pages, if the element doesn't exist yet, lazily create it for known special pages
    if (!pageElement && !isAuthPage) {
        const appLayout = document.getElementById('appLayout');
        if (appLayout && (mainPage === 'branch-select')) {
            console.log(`[APP PAGE] Creating ${mainPage} page element in app layout`);
            const pageDiv = document.createElement('div');
            pageDiv.id = mainPage;
            pageDiv.className = 'page';
            appLayout.querySelector('#pageContent')?.appendChild(pageDiv) || appLayout.appendChild(pageDiv);
            pageElement = pageDiv;
        }
    }

    if (pageElement) {
        pageElement.classList.add('active');
        console.log('✅ Page element found and activated:', pageName);
        // Force display - use flex for auth pages to match CSS, block for app pages
        if (isAuthPage) {
            pageElement.style.display = 'flex';
        } else {
            pageElement.style.display = 'block';
        }
        pageElement.style.visibility = 'visible';
        pageElement.style.opacity = '1';
        
        // CRITICAL: Ensure auth layout container is visible for auth pages
        // Must use 'flex' not 'block' to prevent container collapse (matches renderAuthLayout)
        if (isAuthPage) {
            const authLayoutContainer = document.getElementById('authLayout');
            if (authLayoutContainer) {
                authLayoutContainer.style.display = 'flex';
                authLayoutContainer.style.visibility = 'visible';
                authLayoutContainer.style.height = '100vh';
                authLayoutContainer.style.minHeight = '100vh';
                authLayoutContainer.style.width = '100%';
            }
        }
    } else if (isAuthPage) {
        // Auth pages should have been created above, but if not, loader will handle it
        console.warn('[AUTH PAGE] Page element still not found, loader will create:', pageName);
    } else {
        console.error('❌ Page element not found:', pageName);
        // If not authenticated and trying to load app page, force login
        if (!authenticated) {
            console.warn('[ROUTING] Page not found and not authenticated, forcing login...');
            renderAuthLayout();
            window.location.hash = '#login';
            if (window.loadLogin) {
                window.loadLogin();
            }
            return; // Stop here, don't try to show dashboard
        }
        // Fallback: show dashboard if requested page doesn't exist (app pages only, authenticated)
        const dashboard = document.getElementById('dashboard');
        if (dashboard) {
            dashboard.classList.add('active');
            dashboard.style.display = 'block';
            dashboard.style.visibility = 'visible';
            console.log('⚠️ Fallback: showing dashboard instead');
        }
    }
    
    // Show/hide action buttons
    const newSaleBtn = document.getElementById('newSaleBtn');
    const newPurchaseBtn = document.getElementById('newPurchaseBtn');
    
    newSaleBtn.style.display = pageName === 'sales' ? 'block' : 'none';
    if (newPurchaseBtn) {
        if (pageName === 'purchases') {
            newPurchaseBtn.style.display = 'block';
            // Connect the button to create function
            newPurchaseBtn.onclick = function() {
                console.log('🔴 [TOP BAR BUTTON] New Purchase button clicked');
                console.log('🔴 [TOP BAR BUTTON] window.createNewPurchaseOrder type:', typeof window.createNewPurchaseOrder);
                console.log('🔴 [TOP BAR BUTTON] window.createNewPurchaseOrder value:', window.createNewPurchaseOrder);
                
                if (window.createNewPurchaseOrder) {
                    console.log('🔴 [TOP BAR BUTTON] Calling window.createNewPurchaseOrder()...');
                    window.createNewPurchaseOrder();
                } else {
                    console.error('❌ [TOP BAR BUTTON] createNewPurchaseOrder function not found!');
                    console.error('❌ [TOP BAR BUTTON] Available window functions:', Object.keys(window).filter(k => k.includes('Purchase')));
                }
            };
        } else {
            newPurchaseBtn.style.display = 'none';
            newPurchaseBtn.onclick = null;
        }
    }
    
    // Update currentScreen tracking
    currentScreen = mainPage;
    
    // Load page content (use mainPage for switch)
    switch(mainPage) {
        case 'invite':
            renderInviteHandler();
            break;
        case 'login':
            // CRITICAL: Ensure auth layout is rendered before loading login
            if (layoutRendered !== 'auth') {
                renderAuthLayout();
            }
            // CRITICAL: Ensure login page element exists in auth layout before calling loader
            const authLayoutForLogin = document.getElementById('authLayout');
            let loginPageEl = document.getElementById('login');
            if (!loginPageEl && authLayoutForLogin) {
                // Create login page element in auth layout if it doesn't exist
                if (!authLayoutForLogin.querySelector('#login')) {
                    const loginDiv = document.createElement('div');
                    loginDiv.id = 'login';
                    loginDiv.className = 'page';
                    authLayoutForLogin.appendChild(loginDiv);
                    loginPageEl = loginDiv;
                }
            }
            // Now call the loader which will populate the element
            if (window.loadLogin) {
                window.loadLogin();
            } else {
                console.error('[ROUTING] loadLogin function not found on window');
            }
            break;
        case 'password-set':
            if (window.loadPasswordSet) window.loadPasswordSet();
            break;
        case 'password-reset':
            // Wait for loadPasswordReset to be available (handles race condition)
            if (window.loadPasswordReset) {
                console.log('[ROUTER] password-reset: loadPasswordReset already available, calling immediately');
                window.loadPasswordReset();
            } else {
                console.warn('[ROUTER] password-reset: loadPasswordReset not yet available, waiting for script to load...');
                // Retry mechanism with longer wait time for script loading race condition
                let retryCount = 0;
                const maxRetries = 100; // Check up to 100 times
                const retryInterval = 50; // Check every 50ms (total max wait: 5 seconds)
                
                const checkInterval = setInterval(() => {
                    retryCount++;
                    
                    // Check if function is now available
                    if (typeof window.loadPasswordReset === 'function') {
                        console.log(`✅ [ROUTER] password-reset: loadPasswordReset now available after ${retryCount * retryInterval}ms, calling it`);
                        clearInterval(checkInterval);
                        try {
                            window.loadPasswordReset();
                        } catch (error) {
                            console.error('[ROUTER] password-reset: Error calling loadPasswordReset:', error);
                        }
                    } else if (retryCount >= maxRetries) {
                        // Give up after max retries
                        console.error(`❌ [ROUTER] password-reset: loadPasswordReset not defined after ${maxRetries * retryInterval}ms (${maxRetries} attempts)`);
                        console.error('   Script may not have loaded. Check Network tab for password_reset.js');
                        clearInterval(checkInterval);
                        
                        // Fallback: show error message
                        const page = document.getElementById('password-reset');
                        if (page) {
                            page.innerHTML = '<div class="login-container"><div class="login-card"><h1><i class="fas fa-pills"></i> PharmaSight</h1><h2>Password Reset</h2><p>The password reset functionality is not available. Please refresh the page.</p><p style="font-size: 0.875rem; color: var(--text-secondary); margin-top: 1rem;">If the problem persists, check the browser console for errors.</p><a href="#login" style="display: inline-block; margin-top: 1rem;">Back to Login</a></div></div>';
                        }
                    }
                }, retryInterval);
            }
            break;
        case 'branch-select':
            if (window.loadBranchSelect) window.loadBranchSelect();
            break;
        case 'setup':
            if (window.loadSetup) window.loadSetup();
            break;
        case 'dashboard':
            if (window.loadDashboard) window.loadDashboard();
            break;
        case 'sales':
            if (window.loadSales) {
                window.loadSales();
                // Load sub-page if specified
                if (subPage && window.loadSalesSubPage) {
                    setTimeout(() => window.loadSalesSubPage(subPage), 100);
                }
            }
            break;
        case 'purchases':
            if (window.loadPurchases) {
                window.loadPurchases();
                // Load sub-page if specified
                if (subPage && window.loadPurchaseSubPage) {
                    setTimeout(() => window.loadPurchaseSubPage(subPage), 100);
                }
            } else {
                console.error('❌ window.loadPurchases is not defined! purchases.js may not have loaded.');
                console.error('   Checking for script errors...');
                // Show error message on page
                const page = document.getElementById('purchases');
                if (page) {
                    page.innerHTML = '<div class="card" style="padding: 2rem;"><h3>Error Loading Purchases Page</h3><p>The purchases.js script may not have loaded properly. Please check the browser console for errors.</p><p>Expected logs: "✅ purchases.js script loaded" and "✓ Purchases functions exported to window"</p></div>';
                }
            }
            break;
        case 'inventory':
            console.log('Loading inventory page...');
            if (window.loadInventory) {
                window.loadInventory();
            } else {
                console.error('loadInventory function not found on window object');
            }
            break;
        case 'settings':
            console.log('[ROUTER] Loading settings page, subPage:', subPage);
            if (typeof window.loadSettings === 'function') {
                console.log('[ROUTER] Calling window.loadSettings with subPage:', subPage);
                // Pass subPage directly to loadSettings to avoid race condition
                window.loadSettings(subPage || null);
                console.log('[ROUTER] window.loadSettings call completed');
            } else {
                console.error('[ROUTER] ERROR: window.loadSettings is not defined!');
                // Show error message on page
                const page = document.getElementById('settings');
                if (page) {
                    page.innerHTML = '<div class="card"><div class="card-body"><p style="color: red;">Error: Settings page not loaded. Please refresh the page.</p></div></div>';
                }
            }
            break;
    }
}

/**
 * Update Status Bar (phAMACore style)
 * Shows: User | Company Name | Branch Name
 */
async function updateStatusBar(user) {
    const statusUser = document.getElementById('statusUser');
    const statusCompany = document.getElementById('statusCompany');
    const statusBranch = document.getElementById('statusBranch');
    
    if (!statusUser || !statusCompany || !statusBranch) {
        console.warn('Status bar elements not found');
        return;
    }
    
    // Update user
    if (user) {
        statusUser.textContent = user.email || user.user_metadata?.full_name || 'User';
    } else {
        statusUser.textContent = 'Not Logged In';
    }
    
    // Update company
    if (CONFIG.COMPANY_ID) {
        try {
            const company = await API.company.get(CONFIG.COMPANY_ID);
            statusCompany.textContent = company.name || 'Unknown Company';
            statusCompany.classList.remove('status-warning');
        } catch (error) {
            console.error('Error loading company:', error);
            statusCompany.textContent = 'Company Not Found';
            statusCompany.classList.add('status-warning');
        }
    } else {
        statusCompany.textContent = 'Not Set';
        statusCompany.classList.add('status-warning');
    }
    
    // Update branch
    if (CONFIG.BRANCH_ID) {
        try {
            const branch = await API.branch.get(CONFIG.BRANCH_ID);
            statusBranch.textContent = branch.name || 'Unknown Branch';
            statusBranch.classList.remove('status-warning');
        } catch (error) {
            console.error('Error loading branch:', error);
            statusBranch.textContent = 'Branch Not Found';
            statusBranch.classList.add('status-warning');
        }
    } else {
        statusBranch.textContent = 'Not Set';
        statusBranch.classList.add('status-warning');
    }
}

// Export for use in other scripts
window.loadPage = loadPage;
window.currentPage = currentPage;
window.updateStatusBar = updateStatusBar;
window.startAppFlow = startAppFlow;
window.renderAppLayout = renderAppLayout;
window.renderAuthLayout = renderAuthLayout;
window.isAuthenticated = isAuthenticated;

