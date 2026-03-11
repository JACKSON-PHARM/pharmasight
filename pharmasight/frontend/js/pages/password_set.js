/**
 * Password Set Page
 * 
 * Mandatory password setup screen for invited users.
 * Shows before any other screen if user needs password setup.
 */

/**
 * Helper function to parse URL parameters from hash or full URL
 */
function parseUrlParams() {
    const hash = window.location.hash || '';
    const fullUrl = window.location.href || '';
    
    // Try to parse from hash first (format: #password-set?param=value or #param=value)
    let paramsString = '';
    if (hash.includes('?')) {
        paramsString = hash.split('?')[1];
    } else if (hash.includes('=')) {
        // Hash might be in root format: #key=value&...
        paramsString = hash.replace('#', '');
    } else if (fullUrl.includes('?')) {
        // Try full URL
        paramsString = fullUrl.split('?')[1].split('#')[0];
    }
    
    const urlParams = new URLSearchParams(paramsString);
    return { urlParams, hash, fullUrl };
}

async function loadPasswordSet() {
    console.log('[PASSWORD SET] Loading password set page');

    // Check if this is a valid password set scenario
    const { urlParams, hash, fullUrl } = parseUrlParams();
    const invitationToken = urlParams.get('invitation_token') || urlParams.get('token');
    const hasInvitationToken = invitationToken || 
                              hash.includes('invitation_token') ||
                              fullUrl.includes('invitation_token');

    // Authenticated user (seeded/forced change) OR unauthenticated invite via token
    const user = (window.AuthBootstrap && typeof AuthBootstrap.getCurrentUser === 'function')
        ? AuthBootstrap.getCurrentUser()
        : null;
    if (!user && !hasInvitationToken) {
        console.error('[PASSWORD SET] No user and no invitation token; redirecting to login');
        window.location.hash = 'login';
        return;
    }
    
    // Get user profile to check password_set flag
    let alreadyHasPassword = false;
    let userProfile = null;
    try {
        if (user?.id) {
            userProfile = await API.users.get(user.id);
            alreadyHasPassword = userProfile.password_set === true;
        }
    } catch (error) {
        console.warn('[PASSWORD SET] Could not check user profile:', error);
        // Continue anyway - better to show page than block user
    }
    
    // User shouldn't be here if:
    // 1. Not in invitation flow AND
    // 2. Already has password set
    if (!hasInvitationToken && alreadyHasPassword) {
        console.warn('[PASSWORD SET] User already has password, redirecting to dashboard');
        window.location.hash = 'dashboard';
        return;
    }
    
    // Ensure we're in auth layout (not app layout)
    renderAuthLayout();
    
    // Get auth layout container or create password-set page
    const authLayout = document.getElementById('authLayout');
    let page = document.getElementById('password-set');
    
    // If page doesn't exist in DOM, create it in auth layout
    if (!page && authLayout) {
        authLayout.innerHTML = '<div id="password-set" class="page"></div>';
        page = document.getElementById('password-set');
    }
    
    if (!page) {
        console.error('Password set page not found and could not be created');
        return;
    }
    
    // Hide other pages
    if (authLayout) {
        authLayout.querySelectorAll('.page').forEach(p => {
            if (p.id !== 'password-set') {
                p.classList.remove('active');
                p.style.display = 'none';
                p.style.visibility = 'hidden';
            }
        });
    }
    
    page.classList.add('active');
    page.style.display = 'block';
    page.style.visibility = 'visible';
    
    const email = user?.email || 'your email';
    const isInviteFlow = Boolean(hasInvitationToken);
    
    page.innerHTML = `
        <div class="login-container">
            <div class="login-card">
                <h1><i class="fas fa-pills"></i> PharmaSight</h1>
                <h2>Set Your Password</h2>
                <p style="margin-bottom: 1.5rem; color: var(--text-secondary);">
                    Welcome! Please set a secure password for your account.
                    <br><small>Email: <strong>${escapeHtml(email)}</strong></small>
                </p>
                <form id="passwordSetForm">
                    ${isInviteFlow ? '' : `
                    <div class="form-group">
                        <label for="currentPassword">Current Password</label>
                        <input type="password" id="currentPassword" required
                               placeholder="Enter current password"
                               autocomplete="current-password">
                    </div>
                    `}
                    <div class="form-group">
                        <label for="newPassword">New Password</label>
                        <input type="password" id="newPassword" required 
                               placeholder="Enter new password" minlength="6"
                               autocomplete="new-password">
                        <small style="color: var(--text-secondary); margin-top: 0.25rem; display: block;">
                            Must be at least 6 characters. Cannot be numbers only, letters only, sequential, or common passwords.
                        </small>
                        <div id="passwordSetValidationError" style="color: var(--danger-color); font-size: 0.875rem; margin-top: 0.25rem; display: none;"></div>
                    </div>
                    <div class="form-group">
                        <label for="confirmPassword">Confirm Password</label>
                        <input type="password" id="confirmPassword" required 
                               placeholder="Confirm new password"
                               autocomplete="new-password">
                    </div>
                    <button type="submit" class="btn btn-primary btn-block">
                        <i class="fas fa-key"></i> Set Password
                    </button>
                </form>
                <div id="passwordSetError" class="error-message" style="display: none; margin-top: 1rem;"></div>
            </div>
        </div>
    `;
    
    // Setup form handler
    const form = document.getElementById('passwordSetForm');
    const errorDiv = document.getElementById('passwordSetError');
    const validationErrorDiv = document.getElementById('passwordSetValidationError');
    const newPasswordInput = document.getElementById('newPassword');
    
    // Real-time password validation
    if (newPasswordInput && window.PasswordValidation) {
        newPasswordInput.addEventListener('input', () => {
            const password = newPasswordInput.value;
            if (validationErrorDiv) {
                const error = window.PasswordValidation.validateRealTime(password);
                if (error) {
                    validationErrorDiv.textContent = error;
                    validationErrorDiv.style.display = 'block';
                    newPasswordInput.style.borderColor = 'var(--danger-color)';
                } else {
                    validationErrorDiv.style.display = 'none';
                    newPasswordInput.style.borderColor = '';
                }
            }
        });
    }
    
    if (form) {
        form.onsubmit = async (e) => {
            e.preventDefault();
            
            const newPassword = document.getElementById('newPassword').value;
            const confirmPassword = document.getElementById('confirmPassword').value;
            
            // Clear previous errors
            if (errorDiv) {
                errorDiv.style.display = 'none';
                errorDiv.textContent = '';
            }
            
            // Validation using PasswordValidation utility
            if (!window.PasswordValidation) {
                console.error('PasswordValidation utility not loaded');
            }
            
            // Use PasswordValidation if available, otherwise fallback to basic validation
            if (window.PasswordValidation) {
                const validation = window.PasswordValidation.validate(newPassword);
                if (!validation.valid) {
                    if (errorDiv) {
                        errorDiv.textContent = validation.errors[0] || 'Password validation failed';
                        errorDiv.style.display = 'block';
                    }
                    return;
                }
            } else {
                // Fallback validation
                if (newPassword.length < 6) {
                    if (errorDiv) {
                        errorDiv.textContent = 'Password must be at least 6 characters long';
                        errorDiv.style.display = 'block';
                    }
                    return;
                }
            }
            
            if (newPassword !== confirmPassword) {
                if (errorDiv) {
                    errorDiv.textContent = 'Passwords do not match';
                    errorDiv.style.display = 'block';
                }
                return;
            }
            
            try {
                const baseUrl = (typeof CONFIG !== 'undefined' && CONFIG.API_BASE_URL)
                    ? CONFIG.API_BASE_URL
                    : (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1' ? 'http://localhost:8000' : window.location.origin);
                const base = (baseUrl || '').replace(/\/$/, '');
                if (!base) throw new Error('Configuration error.');

                if (isInviteFlow) {
                    const token = invitationToken || urlParams.get('invitation_token') || urlParams.get('token');
                    if (!token) throw new Error('Invitation link invalid or expired.');
                    const tenantSubdomain = (() => {
                        try { return localStorage.getItem('pharmasight_tenant_subdomain'); } catch (_) { return null; }
                    })();
                    if (!tenantSubdomain) {
                        throw new Error('Tenant context missing. Please open the invite link on the correct tenant URL.');
                    }
                    const res = await fetch(`${base}/api/invite/accept`, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-Tenant-Subdomain': tenantSubdomain
                        },
                        body: JSON.stringify({ invitation_token: token, new_password: newPassword })
                    });
                    const data = await res.json().catch(() => ({}));
                    if (!res.ok) throw new Error(data.detail || data.message || 'Failed to accept invitation.');

                    showToast('Password set. Sign in with your username and password.', 'success');
                    window.history.replaceState(null, null, window.location.pathname);
                    setTimeout(() => { (window.loadPage && window.loadPage('login')) || (window.location.hash = '#login'); }, 1500);
                    return;
                }

                // Seeded/forced change (authenticated): change password via internal backend
                const currentPasswordEl = document.getElementById('currentPassword');
                const currentPassword = currentPasswordEl ? currentPasswordEl.value : '';
                if (!currentPassword) throw new Error('Current password is required.');
                const res = await fetch(`${base}/api/auth/update-password`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword })
                });
                const data = await res.json().catch(() => ({}));
                if (!res.ok) throw new Error(data.detail || data.message || 'Failed to update password.');
                
                // Update password_set flag in user profile via API
                // Backend should handle this, but we ensure it's set and cache it locally
                const currentUser = AuthBootstrap.getCurrentUser();
                if (currentUser && window.API && window.API.users && window.API.users.update) {
                    try {
                        const updateData = {
                            password_set: true
                        };

                        // If user was pending (invited), mark as active and clear invitation token
                        if (userProfile && userProfile.is_pending === true) {
                            updateData.is_pending = false;
                            updateData.invitation_token = null;
                            console.log('[PASSWORD SET] Marking invited user as active and clearing invitation token');
                        }

                        await API.users.update(currentUser.id, updateData);

                        // Cache flag locally to avoid race conditions with subsequent checks
                        const localStorageKey = `user_${currentUser.id}_password_set`;
                        try {
                            localStorage.setItem(localStorageKey, 'true');
                        } catch (storageError) {
                            console.warn('[PASSWORD SET] Could not cache password_set flag in localStorage:', storageError);
                        }
                    } catch (apiError) {
                        console.warn('Could not update user profile flags after password set:', apiError);
                        // Non-critical - backend may also handle this
                    }
                }
                
                // Inform user and prepare for layout transition
                showToast('Password set successfully! Redirecting to branch selection...', 'success');
                
                // Mark that we are transitioning from password-set so loadPage()
                // can force the App layout even if layoutRendered is stale, and let
                // other flows know password was just set (bypasses stale checks).
                try {
                    sessionStorage.setItem('just_set_password', 'true');
                    // Clear the flag after a short window to avoid long-lived stale state
                    setTimeout(() => {
                        try {
                            sessionStorage.removeItem('just_set_password');
                        } catch (clearErr) {
                            console.warn('[PASSWORD SET] Could not clear just_set_password flag:', clearErr);
                        }
                    }, 10000);
                    // Clear any explicit needs_password_setup flag if present
                    sessionStorage.removeItem('needs_password_setup');
                } catch (e) {
                    console.warn('Could not set just_set_password flag in sessionStorage:', e);
                }
                
                // Wait a moment for auth state to update
                await new Promise(resolve => setTimeout(resolve, 500));
                
                // FIXED: After password set, go directly to branch-select (not dashboard)
                // Reset currentScreen to allow navigation
                if (window.currentScreen !== undefined) {
                    window.currentScreen = null;
                }
                
                // Navigate to branch-select page
                console.log('[PASSWORD SET] Password set complete, redirecting to branch-select');
                if (window.loadPage) {
                    window.loadPage('branch-select');
                } else {
                    window.location.hash = '#branch-select';
                }
            } catch (error) {
                console.error('Password set error:', error);
                if (errorDiv) {
                    errorDiv.textContent = error.message || 'Failed to set password. Please try again.';
                    errorDiv.style.display = 'block';
                }
            }
        };
    }
}

// Helper function for escaping HTML
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Export for app.js
window.loadPasswordSet = loadPasswordSet;
