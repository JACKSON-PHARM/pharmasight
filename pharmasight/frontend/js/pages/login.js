/**
 * Login Page
 * 
 * Handles user authentication via Supabase Auth
 */

async function loadLogin() {
    // Check if already logged in
    const user = await Auth.getCurrentUser();
    if (user) {
        // Already logged in, check if setup is needed
        const redirect = await Auth.shouldRedirectToSetup();
        if (redirect.redirect === 'setup') {
            loadPage('setup');
            return;
        } else {
            loadPage('dashboard');
            return;
        }
    }
    
    // Show login page
    const page = document.getElementById('login');
    if (!page) {
        console.error('Login page not found');
        return;
    }
    
    page.classList.add('active');
    
    // Hide other pages
    document.querySelectorAll('.page').forEach(p => {
        if (p.id !== 'login') {
            p.classList.remove('active');
        }
    });
    
    // Hide sidebar
    const sidebar = document.getElementById('sidebar');
    if (sidebar) {
        sidebar.style.display = 'none';
    }
    
    // Setup form handler
    const form = document.getElementById('loginForm');
    const errorDiv = document.getElementById('loginError');
    
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
                // Sign in via Supabase
                const data = await Auth.signIn(email, password);
                
                if (data.user) {
                    // Store user ID in config
                    CONFIG.USER_ID = data.user.id;
                    saveConfig();
                    
                    // Update username display
                    const usernameSpan = document.getElementById('username');
                    if (usernameSpan) {
                        usernameSpan.textContent = data.user.email || 'User';
                    }
                    
                    // Check if setup is needed
                    const redirect = await Auth.shouldRedirectToSetup();
                    
                    if (redirect.redirect === 'setup') {
                        showToast('Welcome! Please complete company setup.', 'success');
                        loadPage('setup');
                    } else {
                        showToast('Welcome back!', 'success');
                        loadPage('dashboard');
                    }
                }
            } catch (error) {
                console.error('Login error:', error);
                
                // Show error
                if (errorDiv) {
                    errorDiv.textContent = error.message || 'Invalid email or password';
                    errorDiv.style.display = 'block';
                } else {
                    showToast(error.message || 'Login failed', 'error');
                }
            }
        };
    }
}

// Export for app.js
window.loadLogin = loadLogin;
