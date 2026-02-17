/**
 * Login Page
 * 
 * Handles user authentication via Supabase Auth
 */

async function loadLogin() {
    try {
        // Set tenant context from URL so username-login uses the correct tenant DB (e.g. after invite: ?tenant=pharmasight-meds-ltd)
        const params = new URLSearchParams(window.location.search || '');
        const tenantFromUrl = params.get('tenant') || params.get('subdomain');
        if (tenantFromUrl) {
            // Per-tab tenant context first (prevents collisions across tabs).
            try { if (typeof sessionStorage !== 'undefined') sessionStorage.setItem('pharmasight_tenant_subdomain', tenantFromUrl); } catch (_) {}
            // Also persist last-used tenant for convenience across reloads.
            try { if (typeof localStorage !== 'undefined') localStorage.setItem('pharmasight_tenant_subdomain', tenantFromUrl); } catch (_) {}
        }
        if (sessionStorage.getItem('tenant_invite_setup_done') === '1') {
            sessionStorage.removeItem('tenant_invite_setup_done');
            if (typeof showToast === 'function') showToast('Password set. Sign in with your username.', 'success');
            else if (typeof showNotification === 'function') showNotification('Password set. Sign in with your username.', 'success');
        }
    } catch (_) {}
    // Check if already logged in (using AuthBootstrap for consistency)
    const user = AuthBootstrap.getCurrentUser();
    if (user && isAuthenticated()) {
        // Already logged in, switch to app layout and continue app flow
        renderAppLayout();
        if (window.startAppFlow) {
            await window.startAppFlow();
        } else {
            loadPage('dashboard');
        }
        return;
    }
    
    // Ensure we're in auth layout (not app layout)
    renderAuthLayout();
    
    // Get auth layout container
    const authLayout = document.getElementById('authLayout');
    if (!authLayout) {
        console.error('[LOGIN] Auth layout container not found');
        return;
    }
    
    // Get login page element (should already exist - loadPage() creates it first)
    let page = document.getElementById('login');
    if (!page) {
        // Fallback: Only create if loadPage() didn't create it (shouldn't happen normally)
        console.warn('[LOGIN] Login page element not found, creating fallback element in auth layout...');
        const loginDiv = document.createElement('div');
        loginDiv.id = 'login';
        loginDiv.className = 'page';
        authLayout.appendChild(loginDiv);
        page = loginDiv;
    }
    
    if (!page) {
        console.error('[LOGIN] Failed to get or create login page element');
        return;
    }
    
    console.log('[LOGIN] Rendering login form in element:', page.id);
    
    // CRITICAL: Ensure auth layout is visible
    if (authLayout) {
        authLayout.style.display = 'block';
        authLayout.style.visibility = 'visible';
    }
    
    // Render login form (standalone, no app shell)
    page.innerHTML = `
        <div class="login-container">
            <div class="login-card">
                <h1><i class="fas fa-pills"></i> PharmaSight</h1>
                <h2>Sign In</h2>
                <form id="loginForm">
                    <div class="form-group">
                        <label for="loginUsername">Username</label>
                        <input type="text" id="loginUsername" required placeholder="Enter your username">
                    </div>
                    <div class="form-group">
                        <label for="loginPassword">Password</label>
                        <input type="password" id="loginPassword" required placeholder="••••••••">
                    </div>
                    <button type="submit" class="btn btn-primary btn-block">
                        <i class="fas fa-sign-in-alt"></i> Sign In
                    </button>
                </form>
                <div id="loginError" class="error-message" style="display: none;"></div>
                <p class="login-hint" style="font-size: 0.8rem; color: var(--text-secondary, #666); margin-top: 0.5rem;">
                    <strong>Admin panel</strong>: username <code>admin</code> + admin password → tenant management.<br>
                    <strong>Tenant</strong>: use the username from your invite (e.g. J-MWANGI). <a href="#password-reset">Forgot password?</a>
                </p>
                <div class="login-links">
                    <a href="#password-reset">Forgot Password?</a>
                </div>
            </div>
        </div>
    `;
    
    // CRITICAL: Explicitly show the page element with explicit dimensions
    // Use height: 100% to fill parent flex container
    page.classList.add('active');
    page.style.display = 'flex';
    page.style.visibility = 'visible';
    page.style.opacity = '1';
    page.style.width = '100%';
    page.style.height = '100%';
    page.style.flexShrink = '0';
    
    // RUNTIME DOM VISIBILITY ASSERTIONS - Fail loudly if login is not visible
    setTimeout(() => {
        const computedStyle = window.getComputedStyle(page);
        const rect = page.getBoundingClientRect();
        const loginCard = page.querySelector('.login-card');
        const loginCardRect = loginCard ? loginCard.getBoundingClientRect() : null;
        const authLayoutComputed = window.getComputedStyle(authLayout);
        const authLayoutRect = authLayout.getBoundingClientRect();
        
        // Assertion 1: Page element must exist
        if (!page) {
            console.error('❌ [VISIBILITY ASSERTION FAILED] Login page element does not exist!');
            throw new Error('Login page element does not exist');
        }
        
        // Assertion 2: Auth layout must exist and be visible
        if (!authLayout) {
            console.error('❌ [VISIBILITY ASSERTION FAILED] Auth layout container does not exist!');
            throw new Error('Auth layout container does not exist');
        }
        
        if (authLayoutComputed.display === 'none') {
            console.error('❌ [VISIBILITY ASSERTION FAILED] Auth layout is hidden (display: none)!');
            console.error('   Auth layout inline style:', authLayout.style.display);
            console.error('   Auth layout computed style:', authLayoutComputed.display);
            throw new Error('Auth layout is hidden');
        }
        
        // Assertion 3: Page element must not have zero size
        if (rect.width === 0 || rect.height === 0) {
            console.error('❌ [VISIBILITY ASSERTION FAILED] Login page element has zero size!');
            console.error('   Width:', rect.width, 'Height:', rect.height);
            console.error('   Computed display:', computedStyle.display);
            console.error('   Computed visibility:', computedStyle.visibility);
            console.error('   Computed opacity:', computedStyle.opacity);
            console.error('   Computed position:', computedStyle.position);
            console.error('   Computed z-index:', computedStyle.zIndex);
            throw new Error(`Login page element has zero size (${rect.width}x${rect.height})`);
        }
        
        // Assertion 4: Page element must not be hidden
        if (computedStyle.display === 'none') {
            console.error('❌ [VISIBILITY ASSERTION FAILED] Login page element is hidden (display: none)!');
            console.error('   Inline style display:', page.style.display);
            console.error('   Computed style display:', computedStyle.display);
            throw new Error('Login page element is hidden');
        }
        
        if (computedStyle.visibility === 'hidden') {
            console.error('❌ [VISIBILITY ASSERTION FAILED] Login page element visibility is hidden!');
            console.error('   Inline style visibility:', page.style.visibility);
            console.error('   Computed style visibility:', computedStyle.visibility);
            throw new Error('Login page element visibility is hidden');
        }
        
        if (parseFloat(computedStyle.opacity) === 0) {
            console.error('❌ [VISIBILITY ASSERTION FAILED] Login page element opacity is 0!');
            console.error('   Inline style opacity:', page.style.opacity);
            console.error('   Computed style opacity:', computedStyle.opacity);
            throw new Error('Login page element opacity is 0');
        }
        
        // Assertion 5: Login card must exist and have size
        if (!loginCard) {
            console.error('❌ [VISIBILITY ASSERTION FAILED] Login card element does not exist!');
            console.error('   Page innerHTML length:', page.innerHTML.length);
            throw new Error('Login card element does not exist');
        }
        
        const loginCardComputed = window.getComputedStyle(loginCard);
        if (loginCardRect && (loginCardRect.width === 0 || loginCardRect.height === 0)) {
            console.error('❌ [VISIBILITY ASSERTION FAILED] Login card has zero size!');
            console.error('   Card width:', loginCardRect.width, 'Card height:', loginCardRect.height);
            console.error('   Card computed display:', loginCardComputed.display);
            console.error('   Card computed visibility:', loginCardComputed.visibility);
            throw new Error(`Login card has zero size (${loginCardRect.width}x${loginCardRect.height})`);
        }
        
        // Assertion 6: Check if element is covered by another element
        const elementAtCenter = document.elementFromPoint(
            rect.left + rect.width / 2,
            rect.top + rect.height / 2
        );
        if (elementAtCenter && !page.contains(elementAtCenter) && elementAtCenter !== page && elementAtCenter !== authLayout) {
            console.error('❌ [VISIBILITY ASSERTION FAILED] Login page is covered by another element!');
            console.error('   Covering element:', elementAtCenter);
            console.error('   Covering element tag:', elementAtCenter.tagName);
            console.error('   Covering element id:', elementAtCenter.id);
            console.error('   Covering element class:', elementAtCenter.className);
            console.error('   Covering element computed display:', window.getComputedStyle(elementAtCenter).display);
            console.error('   Covering element computed z-index:', window.getComputedStyle(elementAtCenter).zIndex);
            console.error('   Page computed z-index:', computedStyle.zIndex);
            throw new Error(`Login page is covered by element: ${elementAtCenter.tagName}${elementAtCenter.id ? '#' + elementAtCenter.id : ''}${elementAtCenter.className ? '.' + elementAtCenter.className : ''}`);
        }
        
        // Assertion 7: Check viewport visibility
        if (rect.bottom < 0 || rect.top > window.innerHeight || rect.right < 0 || rect.left > window.innerWidth) {
            console.error('❌ [VISIBILITY ASSERTION FAILED] Login page is outside viewport!');
            console.error('   Page rect:', rect);
            console.error('   Viewport size:', window.innerWidth, 'x', window.innerHeight);
            console.error('   Page position:', { left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom });
            throw new Error(`Login page is outside viewport (rect: ${JSON.stringify(rect)})`);
        }
        
        // Assertion 8: Auth layout must have size
        if (authLayoutRect.width === 0 || authLayoutRect.height === 0) {
            console.error('❌ [VISIBILITY ASSERTION FAILED] Auth layout has zero size!');
            console.error('   Auth layout width:', authLayoutRect.width, 'Height:', authLayoutRect.height);
            console.error('   Auth layout computed display:', authLayoutComputed.display);
            console.error('   Auth layout computed position:', authLayoutComputed.position);
            throw new Error(`Auth layout has zero size (${authLayoutRect.width}x${authLayoutRect.height})`);
        }
        
        // Success - log all visibility metrics
        console.log('✅ [VISIBILITY ASSERTION PASSED] Login page is visible');
        console.log('   Page rect:', rect);
        console.log('   Page computed display:', computedStyle.display);
        console.log('   Page computed visibility:', computedStyle.visibility);
        console.log('   Page computed opacity:', computedStyle.opacity);
        console.log('   Page computed position:', computedStyle.position);
        console.log('   Page computed z-index:', computedStyle.zIndex);
        console.log('   Auth layout rect:', authLayoutRect);
        console.log('   Auth layout computed display:', authLayoutComputed.display);
        if (loginCardRect) {
            console.log('   Login card rect:', loginCardRect);
        }
        console.log('   Element at center:', elementAtCenter ? `${elementAtCenter.tagName}${elementAtCenter.id ? '#' + elementAtCenter.id : ''}` : 'none');
    }, 100); // Small delay to ensure rendering is complete
    
    // Setup form handler
    const form = document.getElementById('loginForm');
    const errorDiv = document.getElementById('loginError');
    
    // Setup "Forgot Password?" link handler
    const forgotPasswordLink = page.querySelector('a[href="#password-reset"]');
    if (forgotPasswordLink) {
        forgotPasswordLink.addEventListener('click', (e) => {
            e.preventDefault();
            console.log('[LOGIN] Forgot Password link clicked, navigating to password-reset');
            // Use loadPage to ensure proper routing
            if (window.loadPage) {
                window.loadPage('password-reset');
            } else {
                // Fallback to direct hash change
                window.location.hash = '#password-reset';
            }
        });
    }
    
    if (form) {
        form.onsubmit = async (e) => {
            e.preventDefault();
            
            const username = document.getElementById('loginUsername').value.trim();
            const password = document.getElementById('loginPassword').value;
            
            // Clear previous errors
            if (errorDiv) {
                errorDiv.style.display = 'none';
                errorDiv.textContent = '';
            }
            
            try {
                // Check if user is blocked (brute force protection)
                if (window.LoginSecurity) {
                    if (window.LoginSecurity.isUserBlocked(username)) {
                        const blockedUntil = window.LoginSecurity.getBlockedUntil(username);
                        const timeRemaining = window.LoginSecurity.formatTimeUntilUnblock(blockedUntil);
                        
                        const errorMsg = timeRemaining
                            ? `Account locked due to too many failed attempts. Try again in ${timeRemaining}.`
                            : 'Account locked due to too many failed attempts.';
                        
                        if (errorDiv) {
                            // Offer a self-service unlock option (password reset email) instead of just waiting.
                            errorDiv.innerHTML = `
                                <div style="text-align:center;">
                                    <div style="margin-bottom:0.5rem;">${String(errorMsg).replace(/</g, '&lt;')}</div>
                                    <button type="button" class="btn btn-secondary" id="unlockAccountBtn" style="width:100%;">
                                        <i class="fas fa-envelope"></i> Send unlock link
                                    </button>
                                    <div style="margin-top:0.5rem; font-size:0.85rem; color: var(--text-secondary);">
                                        You can reset your password, or go back and continue using your old password.
                                    </div>
                                </div>
                            `;
                            errorDiv.style.display = 'block';
                            const btn = document.getElementById('unlockAccountBtn');
                            if (btn) {
                                btn.onclick = async () => {
                                    btn.disabled = true;
                                    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Sending...';
                                    try {
                                        await sendUnlockLinkForUsername(username);
                                        // Unblock locally so user can try again immediately if they remember the password.
                                        try { window.LoginSecurity.unblockUser(username); } catch (_) {}
                                        if (errorDiv) {
                                            errorDiv.innerHTML = `
                                                <div style="text-align:center;">
                                                    <div style="margin-bottom:0.5rem; color: var(--success-color);">
                                                        Unlock link sent. Check your email.
                                                    </div>
                                                    <div style="font-size:0.85rem; color: var(--text-secondary);">
                                                        You can reset your password using the email link, or return and sign in with your current password.
                                                    </div>
                                                </div>
                                            `;
                                            errorDiv.style.display = 'block';
                                        }
                                    } catch (err) {
                                        const msg = (err && err.message) ? err.message : 'Failed to send unlock link';
                                        if (errorDiv) {
                                            errorDiv.textContent = msg;
                                            errorDiv.style.display = 'block';
                                        } else if (typeof showToast === 'function') {
                                            showToast(msg, 'error');
                                        }
                                    } finally {
                                        if (btn) {
                                            btn.disabled = false;
                                            btn.innerHTML = '<i class="fas fa-envelope"></i> Send unlock link';
                                        }
                                    }
                                };
                            }
                        } else {
                            showToast(errorMsg, 'error');
                        }
                        return;
                    }
                }
                
                // Check if this is an admin login
                const isAdminLogin = username.toLowerCase() === 'admin';
                
                if (isAdminLogin) {
                    // Admin panel login: username "admin" + admin password → tenant management
                    try {
                        const adminResponse = await fetch(`${CONFIG.API_BASE_URL}/api/admin/auth/login`, {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json',
                            },
                            body: JSON.stringify({ username, password })
                        });
                        const adminData = await adminResponse.json().catch(() => ({}));
                        if (adminResponse.ok && adminData.success && adminData.is_admin) {
                            localStorage.setItem('admin_token', adminData.token);
                            localStorage.setItem('is_admin', 'true');
                            showToast('Welcome Admin!', 'success');
                            window.location.href = '/admin.html';
                            return;
                        }
                        // Admin login failed: show admin error, do not fall through to regular auth
                        if (adminResponse.status === 401 || adminData.detail) {
                            const errorMsg = adminData.detail || 'Invalid admin credentials';
                            if (window.LoginSecurity) window.LoginSecurity.recordFailedAttempt(username);
                            if (errorDiv) {
                                errorDiv.textContent = errorMsg;
                                errorDiv.style.display = 'block';
                            } else {
                                showToast(errorMsg, 'error');
                            }
                            return;
                        }
                    } catch (adminError) {
                        console.log('Admin auth request failed:', adminError);
                        const msg = 'Could not reach admin login. Check that the backend is running and, on Render, that ADMIN_PASSWORD is set.';
                        if (errorDiv) {
                            errorDiv.textContent = msg;
                            errorDiv.style.display = 'block';
                        } else {
                            showToast(msg, 'error');
                        }
                        return;
                    }
                }
                
                // Regular user authentication: Lookup email from username (must send tenant context so backend uses tenant DB)
                let userEmail = null;
                try {
                    // IMPORTANT: Do NOT send tenant header during login.
                    // The backend can discover the correct tenant for this username and return tenant_subdomain.
                    // This avoids "wrong tenant" collisions across tabs/devices.
                    const headers = { 'Content-Type': 'application/json' };
                    const usernameResponse = await fetch(`${CONFIG.API_BASE_URL}/api/auth/username-login`, {
                        method: 'POST',
                        headers,
                        body: JSON.stringify({ username, password })
                    });
                    
                    if (usernameResponse.ok) {
                        const userData = await usernameResponse.json();
                        userEmail = userData.email;
                        // Persist tenant so app knows where this user belongs (all API calls use this tenant DB)
                        if (userData.tenant_subdomain) {
                            try { if (typeof sessionStorage !== 'undefined') sessionStorage.setItem('pharmasight_tenant_subdomain', userData.tenant_subdomain); } catch (_) {}
                            try { if (typeof localStorage !== 'undefined') localStorage.setItem('pharmasight_tenant_subdomain', userData.tenant_subdomain); } catch (_) {}
                        }
                        // Store username for UI display (status bar / sidebar show username instead of email)
                        if (typeof localStorage !== 'undefined' && (userData.username || username)) {
                            localStorage.setItem('pharmasight_username', userData.username || username);
                        }
                    } else {
                        const errorData = await usernameResponse.json().catch(() => ({}));
                        // Same username in more than one tenant: show picker
                        if (usernameResponse.status === 409 && errorData.detail && typeof errorData.detail === 'object' && errorData.detail.code === 'multiple_tenants') {
                            const msg = errorData.detail.message || 'This username exists in more than one organization.';
                            const tenants = errorData.detail.tenants || [];
                            if (errorDiv) {
                                let html = '<p style="margin-bottom:0.5rem;">' + String(msg).replace(/</g, '&lt;') + '</p>';
                                if (tenants.length) {
                                    html += '<p class="login-hint" style="margin-top:0.5rem;"><strong>Choose organization:</strong></p><div style="display:flex;flex-wrap:wrap;gap:0.5rem;margin-top:0.5rem;">';
                                    tenants.forEach(function(t) {
                                        const sub = (t.subdomain || '').replace(/"/g, '&quot;');
                                        const name = (t.name || t.subdomain || sub).replace(/</g, '&lt;');
                                        const url = (window.location.pathname || '/') + '?tenant=' + encodeURIComponent(t.subdomain) + '#login';
                                        html += '<a href="' + url + '" class="btn btn-secondary" style="font-size:0.85rem;">' + name + '</a>';
                                    });
                                    html += '</div>';
                                }
                                errorDiv.innerHTML = html;
                                errorDiv.style.display = 'block';
                            } else {
                                showToast(msg, 'error');
                            }
                            return;
                        }
                        if (!userEmail) {
                            throw new Error(typeof errorData.detail === 'string' ? errorData.detail : (errorData.detail && errorData.detail.message) || 'User not found');
                        }
                    }
                } catch (error) {
                    // Record failed attempt
                    if (window.LoginSecurity) {
                        window.LoginSecurity.recordFailedAttempt(username);
                    }
                    
                    const errorMsg = error.message || 'Invalid username or password';
                    if (errorDiv) {
                        errorDiv.textContent = errorMsg;
                        errorDiv.style.display = 'block';
                    } else {
                        showToast(errorMsg, 'error');
                    }
                    return;
                }
                
                // Now authenticate with Supabase using the email
                const data = await AuthBootstrap.signIn(userEmail, password);
                
                if (data.user) {
                    // Clear failed attempts on successful login
                    if (window.LoginSecurity) {
                        window.LoginSecurity.clearAttempts(username);
                    }
                    
                    // Check if this user is also an admin (for tenant admins)
                    // This allows tenant admins to access both their tenant app and admin panel
                    const loggedInUserEmail = data.user.email?.toLowerCase();
                    const isTenantAdmin = loggedInUserEmail === 'pharmasightsolutions@gmail.com' || 
                                         loggedInUserEmail === 'admin@pharmasight.com';
                    
                    // Store user ID in config
                    CONFIG.USER_ID = data.user.id;
                    saveConfig();
                    
                    // Clear admin flags for regular users
                    localStorage.removeItem('admin_token');
                    localStorage.removeItem('is_admin');
                    
                    // Refresh auth state
                    await AuthBootstrap.refresh();
                    
                    showToast('Welcome!', 'success');
                    
                    // Switch to app layout after successful login
                    if (window.renderAppLayout) {
                        window.renderAppLayout();
                    }
                    
                    // Initialize session timeout
                    if (window.SessionTimeout) {
                        window.SessionTimeout.init();
                    }
                    
                    // FIXED: Check if this is a special flow requiring password setup
                    // Reset currentScreen to allow navigation
                    if (window.currentScreen !== undefined) {
                        window.currentScreen = null;
                    }
                    
                    // Check URL parameters to determine flow type
                    const hash = window.location.hash || '';
                    const fullUrl = window.location.href || '';
                    
                    // Parse URL parameters - handle both hash and full URL formats
                    let paramsString = '';
                    if (hash.includes('?')) {
                        paramsString = hash.split('?')[1];
                    } else if (hash.includes('=')) {
                        paramsString = hash.replace('#', '');
                    } else if (fullUrl.includes('?')) {
                        paramsString = fullUrl.split('?')[1].split('#')[0];
                    }
                    
                    const urlParams = new URLSearchParams(paramsString);
                    const isPasswordResetFlow = urlParams.get('type') === 'recovery' || 
                                              hash.includes('type=recovery') || 
                                              hash.includes('type%3Drecovery') ||
                                              fullUrl.includes('type=recovery');
                    const hasInvitationToken = urlParams.get('invitation_token') || 
                                              hash.includes('invitation_token') ||
                                              fullUrl.includes('invitation_token');
                    
                    if (isPasswordResetFlow || hasInvitationToken) {
                        // User needs to set/reset password (invitation/reset flow)
                        console.log('[LOGIN] Password setup required (invitation/reset flow)');
                        if (window.loadPage) {
                            window.loadPage('password-set');
                        } else {
                            window.location.hash = '#password-set';
                        }
                    } else {
                        // Normal login - check if user already has password
                        const needsPassword = await AuthBootstrap.needsPasswordSetup(data.user, 'login');
                        if (needsPassword) {
                            console.log('[LOGIN] Password setup required (first login)');
                            if (window.loadPage) {
                                window.loadPage('password-set');
                            } else {
                                window.location.hash = '#password-set';
                            }
                        } else {
                            // Normal login - password already set, go to branch selection
                            console.log('[LOGIN] Normal login, redirecting to branch-select');
                            if (window.loadPage) {
                                window.loadPage('branch-select');
                            } else {
                                window.location.hash = '#branch-select';
                            }
                        }
                    }
                }
            } catch (error) {
                console.error('Login error:', error);
                
                // Record failed attempt (brute force protection)
                if (window.LoginSecurity) {
                    const attemptInfo = window.LoginSecurity.recordFailedAttempt(username);
                    const remaining = window.LoginSecurity.getRemainingAttempts(username);
                    
                    let errorMsg = error.message || 'Invalid username or password';
                    
                    // Add remaining attempts info if not blocked yet
                    if (!attemptInfo.blocked && remaining > 0) {
                        errorMsg += ` (${remaining} attempt${remaining !== 1 ? 's' : ''} remaining)`;
                    }
                    
                    // Show error
                    if (errorDiv) {
                        errorDiv.textContent = errorMsg;
                        errorDiv.style.display = 'block';
                    } else {
                        showToast(errorMsg, 'error');
                    }
                    
                    // If blocked, show additional message
                    if (attemptInfo.blocked) {
                        const blockedUntil = window.LoginSecurity.getBlockedUntil(username);
                        const timeRemaining = window.LoginSecurity.formatTimeUntilUnblock(blockedUntil);
                        const blockMsg = timeRemaining 
                            ? `Account locked. Try again in ${timeRemaining}.`
                            : 'Account locked. Please contact an administrator.';
                        
                        setTimeout(() => {
                            if (errorDiv) {
                                errorDiv.textContent = blockMsg;
                            } else {
                                showToast(blockMsg, 'error');
                            }
                        }, 2000);
                    }
                } else {
                    // No LoginSecurity available, show basic error
                    if (errorDiv) {
                        errorDiv.textContent = error.message || 'Invalid username or password';
                        errorDiv.style.display = 'block';
                    } else {
                        showToast(error.message || 'Login failed', 'error');
                    }
                }
            }
        };
    }
}

/**
 * Self-service unlock: send Supabase password reset email for a username.
 * Backend discovers tenant for the username and returns the correct email.
 */
async function sendUnlockLinkForUsername(username) {
    const normalized = (username || '').trim();
    if (!normalized) {
        throw new Error('Enter your username or email first.');
    }
    if (!CONFIG || !CONFIG.API_BASE_URL) {
        throw new Error('Configuration error: API base URL not set.');
    }

    // Step 1: Resolve email + tenant context from backend (do not send tenant header)
    const res = await fetch(`${CONFIG.API_BASE_URL}/api/auth/username-login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        // Password is required by schema, but not used for lookup.
        body: JSON.stringify({ username: normalized, password: 'unlock' })
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
        const msg = typeof data.detail === 'string'
            ? data.detail
            : (data.detail && data.detail.message) || 'User not found';
        throw new Error(msg);
    }

    const email = data.email;
    if (!email) throw new Error('Could not resolve your email for password reset.');

    // Persist tenant so subsequent app API calls use the correct DB for this user
    if (data.tenant_subdomain) {
        try { if (typeof sessionStorage !== 'undefined') sessionStorage.setItem('pharmasight_tenant_subdomain', data.tenant_subdomain); } catch (_) {}
        try { if (typeof localStorage !== 'undefined') localStorage.setItem('pharmasight_tenant_subdomain', data.tenant_subdomain); } catch (_) {}
    }

    // Step 2: Send Supabase reset email (works as "unlock" link)
    const supabase = window.initSupabaseClient ? window.initSupabaseClient() : null;
    if (!supabase) throw new Error('Supabase client not available');

    const { error } = await supabase.auth.resetPasswordForEmail(email, {
        redirectTo: (typeof CONFIG !== 'undefined' && CONFIG.APP_PUBLIC_URL) ? CONFIG.APP_PUBLIC_URL : window.location.origin
    });
    if (error) throw error;
    return true;
}

// Export for app.js
window.loadLogin = loadLogin;
