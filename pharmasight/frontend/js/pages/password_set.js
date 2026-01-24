/**
 * Password Set Page
 * 
 * Mandatory password setup screen for invited users.
 * Shows before any other screen if user needs password setup.
 */

async function loadPasswordSet() {
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
    
    const user = AuthBootstrap.getCurrentUser();
    const email = user?.email || 'your email';
    
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
                    <div class="form-group">
                        <label for="newPassword">New Password</label>
                        <input type="password" id="newPassword" required 
                               placeholder="Enter new password" minlength="8"
                               autocomplete="new-password">
                        <small style="color: var(--text-secondary); margin-top: 0.25rem; display: block;">
                            Must be at least 8 characters long
                        </small>
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
            
            // Validation
            if (newPassword.length < 8) {
                if (errorDiv) {
                    errorDiv.textContent = 'Password must be at least 8 characters long';
                    errorDiv.style.display = 'block';
                }
                return;
            }
            
            if (newPassword !== confirmPassword) {
                if (errorDiv) {
                    errorDiv.textContent = 'Passwords do not match';
                    errorDiv.style.display = 'block';
                }
                return;
            }
            
            try {
                // Update password via Supabase
                await AuthBootstrap.updatePassword(newPassword);
                
                // Update password_set flag in user profile via API
                // Backend should handle this, but we ensure it's set
                const user = AuthBootstrap.getCurrentUser();
                if (user && window.API && window.API.users && window.API.users.update) {
                    try {
                        await API.users.update(user.id, { password_set: true });
                    } catch (apiError) {
                        console.warn('Could not update password_set flag:', apiError);
                        // Non-critical - backend should handle this
                    }
                }
                
                showToast('Password set successfully!', 'success');
                
                // Wait a moment for auth state to update
                await new Promise(resolve => setTimeout(resolve, 500));
                
                // Trigger app flow to continue (password setup complete)
                // The app router will detect this and proceed to branch selection
                if (window.handlePasswordSetComplete) {
                    window.handlePasswordSetComplete();
                } else {
                    // Fallback: reload to trigger auth flow
                    window.location.reload();
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
