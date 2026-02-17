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
    
    // Check if we have a token in the URL OR a persisted flag from app.js
    const hash = window.location.hash || '';
    const fullUrl = window.location.href || '';
    const hasTokenInUrl = (
        hash.includes('access_token') && hash.includes('type=recovery')
    ) || (
        fullUrl.includes('access_token') && fullUrl.includes('type=recovery')
    );
    const hasTokenFlag = window.__PASSWORD_RESET_TOKEN_PRESENT === true;
    const hasToken = hasTokenInUrl || hasTokenFlag;
    
    console.log('[PASSWORD RESET] Has token in URL?', hasTokenInUrl, 'Has token flag?', hasTokenFlag);
    
    if (hasToken) {
        // Token in URL - show password update form
        console.log('[PASSWORD RESET] Showing password update form (token detected)');
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
            
            try {
                const supabase = window.initSupabaseClient();
                if (!supabase) throw new Error('Supabase client not available');
                
                // Send reset email
                const { error } = await supabase.auth.resetPasswordForEmail(email, {
                    redirectTo: (typeof CONFIG !== 'undefined' && CONFIG.APP_PUBLIC_URL) ? CONFIG.APP_PUBLIC_URL : window.location.origin
                });
                
                if (error) throw error;
                
                // Show success
                if (successDiv) {
                    successDiv.innerHTML = `
                        <i class="fas fa-check-circle"></i>
                        <p>Password reset link has been sent to your email!</p>
                        <p style="font-size: 0.875rem; margin-top: 0.5rem;">
                            Please check your inbox and click the link to reset your password.
                        </p>
                    `;
                    successDiv.style.display = 'block';
                }
                
                // Hide form
                form.style.display = 'none';
                
            } catch (error) {
                console.error('Password reset error:', error);
                if (errorDiv) {
                    errorDiv.textContent = error.message || 'Failed to send reset email. Please try again.';
                    errorDiv.style.display = 'block';
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
                               placeholder="At least 6 characters (not numbers/letters only, sequential, or common)"
                               minlength="6" autocomplete="new-password">
                        <small style="color: var(--text-secondary); margin-top: 0.25rem; display: block;">
                            Must be at least 6 characters. Cannot be numbers only, letters only, sequential, or common passwords.
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
    
    // First, let Supabase process the token naturally
    console.log('[PASSWORD RESET] Waiting for Supabase to process recovery token...');
    
    // Wait a moment for Supabase to process the token
    await new Promise(resolve => setTimeout(resolve, 1000));
    
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
            
            // Use PasswordValidation if available, otherwise fallback to basic validation
            if (window.PasswordValidation) {
                const validation = window.PasswordValidation.validate(newPassword);
                if (!validation.valid) {
                    showError(validation.errors[0] || 'Password validation failed');
                    return;
                }
            } else {
                // Fallback validation
                if (newPassword.length < 6) {
                    showError('Password must be at least 6 characters long');
                    return;
                }
                
                const hasNumber = /\d/.test(newPassword);
                const hasLetter = /[a-zA-Z]/.test(newPassword);
                
                if (!hasNumber || !hasLetter) {
                    showError('Password must include both letters and numbers');
                    return;
                }
            }
            
            // Show loading
            const submitBtn = form.querySelector('button[type="submit"]');
            const originalText = submitBtn.innerHTML;
            submitBtn.disabled = true;
            submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Updating...';
            
            try {
                const supabase = window.initSupabaseClient();
                if (!supabase) throw new Error('Supabase client not available');
                
                // First, get the current session
                const { data: sessionData, error: sessionError } = await supabase.auth.getSession();
                
                if (sessionError) throw sessionError;
                
                if (!sessionData.session) {
                    // Try one more time with a small delay
                    await new Promise(resolve => setTimeout(resolve, 500));
                    const { data: retryData } = await supabase.auth.getSession();
                    
                    if (!retryData.session) {
                        throw new Error('No valid recovery session. The link may have expired or already been used.');
                    }
                }
                
                // Update password
                const { error: updateError } = await supabase.auth.updateUser({
                    password: newPassword
                });
                
                if (updateError) throw updateError;
                
                console.log('[PASSWORD RESET] ✅ Password updated successfully!');

                // Also mark password_set = true in our backend profile so app flow doesn't
                // keep sending the user to the password-set screen after login.
                try {
                    const activeSession = sessionData.session || (await supabase.auth.getSession())?.data?.session;
                    const userId = activeSession?.user?.id;
                    if (userId && window.API && window.API.users && window.API.users.update) {
                        await API.users.update(userId, { password_set: true });
                        console.log('[PASSWORD RESET] Updated password_set flag in user profile');
                    } else {
                        console.warn('[PASSWORD RESET] Could not update password_set flag (no userId or API.users.update)');
                    }
                } catch (profileError) {
                    console.warn('[PASSWORD RESET] Error updating password_set flag:', profileError);
                    // Non-critical; user can still log in, but might see password-set once more
                }
                
                showToast('Password updated successfully! You can now login with your new password.', 'success');
                
                // Sign out the recovery session to ensure fresh login
                try {
                    await supabase.auth.signOut();
                    console.log('[PASSWORD RESET] Signed out recovery session');
                } catch (signOutError) {
                    console.warn('[PASSWORD RESET] Error signing out:', signOutError);
                    // Non-critical - continue with redirect
                }
                
                // Clear hash and redirect to login
                window.history.replaceState(null, null, window.location.pathname);
                setTimeout(() => {
                    if (window.loadPage) {
                        window.loadPage('login');
                    } else {
                        window.location.hash = '#login';
                    }
                }, 1500);
                
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