/**
 * Password Reset Page
 * 
 * Handles password reset flow for existing users who forgot their password
 */

async function loadPasswordReset() {
    console.log('[PASSWORD RESET] Script loaded and executing!');
    console.log('[PASSWORD RESET] Full URL:', window.location.href);
    console.log('[PASSWORD RESET] Hash:', window.location.hash);
    
    // Ensure auth layout is shown
    ensureAuthLayout();
    const authLayout = document.getElementById('authLayout');
    if (!authLayout) {
        console.error('[PASSWORD RESET] Auth layout container not found');
        return;
    }
    
    // Hide app layout
    const appLayout = document.getElementById('appLayout');
    if (appLayout) appLayout.style.display = 'none';
    
    // Create page container
    let page = authLayout.querySelector('#password-reset');
    if (!page) {
        page = document.createElement('div');
        page.id = 'password-reset';
        page.className = 'page';
        authLayout.appendChild(page);
    }
    
    // Clear page
    page.innerHTML = '';
    
    const token = getResetTokenFromUrl();
    const hasToken = Boolean(token);

    if (hasToken) {
        console.log('[PASSWORD RESET] Showing password update form (internal token detected)');
        await renderPasswordUpdateForm(page);
    } else {
        // No token - show email request form
        console.log('[PASSWORD RESET] Showing email request form (no token)');
        renderEmailRequestForm(page);
    }
}

function renderEmailRequestForm(page) {
    page.innerHTML = `
        <div class="login-container">
            <div class="login-card">
                <h1><i class="fas fa-pills"></i> PharmaSight</h1>
                <h2>Reset Password</h2>
                <p style="color: var(--text-secondary); margin-bottom: 1.5rem; text-align: center;">
                    Enter your email address and we'll send you a link to reset your password.
                </p>
                <form id="passwordResetForm">
                    <div class="form-group">
                        <label for="resetEmail">Email</label>
                        <input type="email" id="resetEmail" required placeholder="your@email.com">
                    </div>
                    <button type="submit" class="btn btn-primary btn-block">
                        <i class="fas fa-envelope"></i> Send Reset Link
                    </button>
                </form>
                <div id="resetError" class="error-message" style="display: none;"></div>
                <div id="resetSuccess" class="success-message" style="display: none;"></div>
                <div class="login-links">
                    <a href="#login" id="backToLoginLinkEmail">Back to Login</a>
                </div>
            </div>
        </div>
    `;
    
    // Setup form
    const form = document.getElementById('passwordResetForm');
    if (form) {
        form.onsubmit = async (e) => {
            e.preventDefault();
            
            const email = document.getElementById('resetEmail').value;
            const errorDiv = document.getElementById('resetError');
            const successDiv = document.getElementById('resetSuccess');
            
            // Clear messages
            if (errorDiv) {
                errorDiv.style.display = 'none';
                errorDiv.textContent = '';
            }
            if (successDiv) {
                successDiv.style.display = 'none';
                successDiv.textContent = '';
            }
            
            const submitBtn = form.querySelector('button[type="submit"]');
            const originalBtnText = submitBtn ? submitBtn.innerHTML : '';
            if (submitBtn) {
                submitBtn.disabled = true;
                submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Sending...';
            }
            try {
                // Internal auth only: backend sends reset email via SMTP (no Supabase).
                const baseUrl = (typeof CONFIG !== 'undefined' && CONFIG.API_BASE_URL)
                    ? CONFIG.API_BASE_URL
                    : (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1' ? 'http://localhost:8000' : window.location.origin);
                const url = `${baseUrl.replace(/\/$/, '')}/api/auth/request-reset`;
                // Timeout so we don't leave "Sending..." forever (e.g. Render cold start or wrong API URL)
                const timeoutMs = 28000;
                const controller = new AbortController();
                const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
                const res = await fetch(url, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ email: email }),
                    signal: controller.signal
                });
                clearTimeout(timeoutId);
                const data = await res.json().catch(() => ({}));
                if (res.ok) {
                    if (successDiv) {
                        successDiv.innerHTML = `
                            <i class="fas fa-check-circle"></i>
                            <p>If an account exists with this email, you will receive a reset link.</p>
                            <p style="font-size: 0.875rem; margin-top: 0.5rem;">Check your inbox and use the link to set a new password.</p>
                        `;
                        successDiv.style.display = 'block';
                    }
                    form.style.display = 'none';
                    if (submitBtn) { submitBtn.disabled = false; submitBtn.innerHTML = originalBtnText; }
                    return;
                }
                const msg = (data.detail && typeof data.detail === 'string') ? data.detail : (data.detail && data.detail.message) || 'Failed to send reset email. Please try again.';
                throw new Error(msg);
            } catch (error) {
                console.error('Password reset error:', error);
                if (errorDiv) {
                    let message = error.message || 'Failed to send reset email. Please try again.';
                    if (error.name === 'AbortError') {
                        message = 'Request timed out. The server may be starting (e.g. on Render). Please try again in a moment.';
                    } else if (message.includes('Failed to fetch') || message.includes('Load failed') || message.includes('NetworkError')) {
                        message = 'Cannot reach the server. Check that the app is deployed and the API URL is correct (e.g. Settings if using separate frontend/backend on Render).';
                    }
                    errorDiv.textContent = message;
                    errorDiv.style.display = 'block';
                }
                if (submitBtn) {
                    submitBtn.disabled = false;
                    submitBtn.innerHTML = originalBtnText;
                }
            }
        };
    }
    
    // Back to login
    const backLink = document.getElementById('backToLoginLinkEmail');
    if (backLink) {
        backLink.addEventListener('click', (e) => {
            e.preventDefault();
            if (window.loadPage) {
                window.loadPage('login');
            } else {
                window.location.hash = '#login';
            }
        });
    }
}

function getResetTokenFromUrl() {
    const search = window.location.search || '';
    const hash = window.location.hash || '';
    const fromSearch = search ? new URLSearchParams(search.slice(1)).get('token') : null;
    if (fromSearch) return fromSearch;
    const q = hash.indexOf('?');
    if (q >= 0) return new URLSearchParams(hash.slice(q + 1)).get('token');
    return null;
}

async function renderPasswordUpdateForm(page) {
    page.innerHTML = `
        <div class="login-container">
            <div class="login-card">
                <h1><i class="fas fa-pills"></i> PharmaSight</h1>
                <h2>Set New Password</h2>
                <p style="color: var(--text-secondary); margin-bottom: 1.5rem; text-align: center;">
                    Enter your new password below.
                </p>
                <form id="passwordUpdateForm">
                    <div class="form-group">
                        <label for="newPassword">New Password</label>
                        <input type="password" id="newPassword" required 
                               placeholder="At least 8 characters (letter and digit required)"
                               minlength="8" autocomplete="new-password">
                        <small style="color: var(--text-secondary); margin-top: 0.25rem; display: block;">
                            Must be at least 8 characters and include both a letter and a digit. Cannot be numbers only, letters only, sequential, or common passwords.
                        </small>
                        <div id="passwordStrength" style="margin-top: 0.5rem; font-size: 0.75rem;"></div>
                        <div id="passwordResetValidationError" style="color: var(--danger-color); font-size: 0.875rem; margin-top: 0.25rem; display: none;"></div>
                    </div>
                    <div class="form-group">
                        <label for="confirmPassword">Confirm Password</label>
                        <input type="password" id="confirmPassword" required 
                               placeholder="Re-enter your password"
                               minlength="4" autocomplete="new-password">
                    </div>
                    <button type="submit" class="btn btn-primary btn-block">
                        <i class="fas fa-key"></i> Update Password
                    </button>
                </form>
                <div id="updateError" class="error-message" style="display: none;"></div>
                <div class="login-links">
                    <a href="#login" id="backToLoginLinkUpdate">Back to Login</a>
                </div>
            </div>
        </div>
    `;
    // Now setup the form
    const form = document.getElementById('passwordUpdateForm');
    const newPasswordInput = document.getElementById('newPassword');
    const confirmPasswordInput = document.getElementById('confirmPassword');
    const errorDiv = document.getElementById('updateError');
    const strengthDiv = document.getElementById('passwordStrength');
    
    // Password strength indicator with real-time validation
    const validationErrorDiv = document.getElementById('passwordResetValidationError');
    
    if (newPasswordInput) {
        newPasswordInput.addEventListener('input', () => {
            const password = newPasswordInput.value;
            
            if (!password) {
                if (strengthDiv) strengthDiv.textContent = '';
                if (validationErrorDiv) validationErrorDiv.style.display = 'none';
                return;
            }
            
            // Use PasswordValidation if available
            if (window.PasswordValidation) {
                const error = window.PasswordValidation.validateRealTime(password);
                if (error) {
                    if (validationErrorDiv) {
                        validationErrorDiv.textContent = error;
                        validationErrorDiv.style.display = 'block';
                    }
                    if (strengthDiv) {
                        strengthDiv.textContent = '';
                    }
                    newPasswordInput.style.borderColor = 'var(--danger-color)';
                } else {
                    if (validationErrorDiv) validationErrorDiv.style.display = 'none';
                    if (strengthDiv) {
                        strengthDiv.textContent = 'Password strength: Good';
                        strengthDiv.style.color = 'var(--success-color)';
                    }
                    newPasswordInput.style.borderColor = '';
                }
            } else {
                // Fallback validation
                const hasNumber = /\d/.test(password);
                const hasLetter = /[a-zA-Z]/.test(password);
                
                if (strengthDiv) {
                    if (password.length < 6) {
                        strengthDiv.textContent = 'Too short (min 6 characters)';
                        strengthDiv.style.color = 'var(--danger-color)';
                    } else if (!hasNumber || !hasLetter) {
                        strengthDiv.textContent = 'Must include both letters and numbers';
                        strengthDiv.style.color = 'var(--danger-color)';
                    } else {
                        strengthDiv.textContent = 'Password strength: Good';
                        strengthDiv.style.color = 'var(--success-color)';
                    }
                }
            }
        });
    }
    
    if (form) {
        form.onsubmit = async (e) => {
            e.preventDefault();
            
            const newPassword = newPasswordInput.value;
            const confirmPassword = confirmPasswordInput.value;
            
            // Clear error
            if (errorDiv) {
                errorDiv.style.display = 'none';
                errorDiv.textContent = '';
            }
            
            // Validation using PasswordValidation utility
            if (newPassword !== confirmPassword) {
                showError('Passwords do not match');
                return;
            }
            
            // Backend requires at least 8 characters; enforce before sending
            if (newPassword.length < 8) {
                showError('Password must be at least 8 characters long');
                return;
            }
            
            // Use PasswordValidation if available, otherwise fallback to basic validation
            if (window.PasswordValidation) {
                const validation = window.PasswordValidation.validate(newPassword);
                if (!validation.valid) {
                    showError(validation.errors[0] || 'Password validation failed');
                    return;
                }
            } else {
                // Fallback validation (must match backend: min 8 chars, letter + digit)
                if (newPassword.length < 8) {
                    showError('Password must be at least 8 characters long');
                    return;
                }
                
                const hasNumber = /\d/.test(newPassword);
                const hasLetter = /[a-zA-Z]/.test(newPassword);
                
                if (!hasNumber || !hasLetter) {
                    showError('Password must contain at least one letter and one digit');
                    return;
                }
            }
            
            // Show loading
            const submitBtn = form.querySelector('button[type="submit"]');
            const originalText = submitBtn.innerHTML;
            submitBtn.disabled = true;
            submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Updating...';
            
            try {
                const token = getResetTokenFromUrl();
                if (!token) throw new Error('Reset link invalid or expired.');
                const baseUrl = (typeof CONFIG !== 'undefined' && CONFIG.API_BASE_URL)
                    ? CONFIG.API_BASE_URL
                    : (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1' ? 'http://localhost:8000' : window.location.origin);
                if (!baseUrl) throw new Error('Configuration error.');
                const res = await fetch(`${baseUrl.replace(/\/$/, '')}/api/auth/reset-password`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ token: token, new_password: newPassword })
                });
                const data = await res.json().catch(() => ({}));
                if (!res.ok) throw new Error(data.detail || data.message || 'Failed to reset password.');
                if (typeof showToast === 'function') showToast('Password reset. Sign in with your username and password.', 'success');
                window.history.replaceState(null, null, window.location.pathname);
                setTimeout(() => { (window.loadPage && window.loadPage('login')) || (window.location.hash = '#login'); }, 1500);
                return;
            } catch (error) {
                console.error('Password update error:', error);
                showError(error.message || 'Failed to update password. Please try again.');
                submitBtn.disabled = false;
                submitBtn.innerHTML = originalText;
            }
        };
    }
    
    function showError(message) {
        if (errorDiv) {
            errorDiv.textContent = message;
            errorDiv.style.display = 'block';
        } else {
            alert(message);
        }
    }
    
    // Back to login
    const backLink = document.getElementById('backToLoginLinkUpdate');
    if (backLink) {
        backLink.addEventListener('click', (e) => {
            e.preventDefault();
            if (window.loadPage) {
                window.loadPage('login');
            } else {
                window.location.hash = '#login';
            }
        });
    }
}

// Helper functions
// NOTE: We intentionally DO NOT override the global renderAuthLayout from app.js.
// This function delegates to the main layout helper when available to keep
// layout state (layoutRendered) consistent across the app.
function ensureAuthLayout() {
    if (typeof window.renderAuthLayout === 'function') {
        window.renderAuthLayout();
        return;
    }
    
    // Fallback: minimal layout toggle if app.js renderAuthLayout is not yet defined
    const authLayout = document.getElementById('authLayout');
    const appLayout = document.getElementById('appLayout');
    
    if (authLayout) {
        authLayout.style.display = 'flex';
        authLayout.style.visibility = 'visible';
    }
    
    if (appLayout) {
        appLayout.style.display = 'none';
    }
}
// Use global showToast from utils.js (do not override with console-only stub)

// Export to window
window.loadPasswordReset = loadPasswordReset;
console.log('[PASSWORD RESET] Function loaded and attached to window');