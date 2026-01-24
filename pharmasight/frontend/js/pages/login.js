/**
 * Login Page
 * 
 * Handles user authentication via Supabase Auth
 */

async function loadLogin() {
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
                        <label for="loginEmail">Email</label>
                        <input type="email" id="loginEmail" required placeholder="your@email.com">
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
            
            const email = document.getElementById('loginEmail').value;
            const password = document.getElementById('loginPassword').value;
            
            // Clear previous errors
            if (errorDiv) {
                errorDiv.style.display = 'none';
                errorDiv.textContent = '';
            }
            
            try {
                // Check if user is blocked (brute force protection)
                if (window.LoginSecurity) {
                    if (window.LoginSecurity.isUserBlocked(email)) {
                        const blockedUntil = window.LoginSecurity.getBlockedUntil(email);
                        const timeRemaining = window.LoginSecurity.formatTimeUntilUnblock(blockedUntil);
                        
                        const errorMsg = timeRemaining 
                            ? `Account locked due to too many failed attempts. Try again in ${timeRemaining}.`
                            : 'Account locked due to too many failed attempts. Please contact an administrator.';
                        
                        if (errorDiv) {
                            errorDiv.textContent = errorMsg;
                            errorDiv.style.display = 'block';
                        } else {
                            showToast(errorMsg, 'error');
                        }
                        return;
                    }
                }
                
                // Sign in via AuthBootstrap
                const data = await AuthBootstrap.signIn(email, password);
                
                if (data.user) {
                    // Clear failed attempts on successful login
                    if (window.LoginSecurity) {
                        window.LoginSecurity.clearAttempts(email);
                    }
                    
                    // Store user ID in config
                    CONFIG.USER_ID = data.user.id;
                    saveConfig();
                    
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
                    const attemptInfo = window.LoginSecurity.recordFailedAttempt(email);
                    const remaining = window.LoginSecurity.getRemainingAttempts(email);
                    
                    let errorMsg = error.message || 'Invalid email or password';
                    
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
                        const blockedUntil = window.LoginSecurity.getBlockedUntil(email);
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
                        errorDiv.textContent = error.message || 'Invalid email or password';
                        errorDiv.style.display = 'block';
                    } else {
                        showToast(error.message || 'Login failed', 'error');
                    }
                }
            }
        };
    }
}

// Export for app.js
window.loadLogin = loadLogin;
