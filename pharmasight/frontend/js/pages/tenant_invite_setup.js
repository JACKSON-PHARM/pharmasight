/**
 * Tenant Invite Setup – Set password for new tenant admins
 * Shown when user opens /setup?token=... from invite email.
 */

function escapeHtml(text) {
    if (text == null) return '';
    const div = document.createElement('div');
    div.textContent = String(text);
    return div.innerHTML;
}

function getTokenFromUrl() {
    const params = new URLSearchParams(window.location.search);
    return params.get('token') || null;
}

async function loadTenantInviteSetup() {
    const token = getTokenFromUrl();
    const page = document.getElementById('tenant-invite-setup');
    if (!page) return;

    if (typeof renderAuthLayout === 'function') renderAuthLayout();

    const authLayout = document.getElementById('authLayout');
    if (authLayout) {
        authLayout.querySelectorAll('.page').forEach(function (p) {
            if (p.id !== 'tenant-invite-setup') {
                p.classList.remove('active');
                p.style.display = 'none';
                p.style.visibility = 'hidden';
            }
        });
    }
    page.classList.add('active');
    page.style.display = 'block';
    page.style.visibility = 'visible';

    if (!token) {
        page.innerHTML = `
            <div class="login-container">
                <div class="login-card">
                    <h1><i class="fas fa-pills"></i> PharmaSight</h1>
                    <h2>Invalid setup link</h2>
                    <p style="margin-bottom: 1rem; color: var(--text-secondary);">
                        This link is missing the setup token. Please use the exact link from your invite email.
                    </p>
                    <a href="#login" class="btn btn-primary btn-block"><i class="fas fa-sign-in-alt"></i> Sign in</a>
                </div>
            </div>`;
        return;
    }

    page.innerHTML = `
        <div class="login-container">
            <div class="login-card">
                <h1><i class="fas fa-pills"></i> PharmaSight</h1>
                <h2>Complete your setup</h2>
                <div id="tenant-invite-loading" style="text-align: center; padding: 2rem;">
                    <div style="border: 4px solid #f3f3f3; border-top: 4px solid #3498db; border-radius: 50%; width: 40px; height: 40px; animation: spin 1s linear infinite; margin: 0 auto 1rem;"></div>
                    <p>Verifying invite…</p>
                </div>
                <div id="tenant-invite-form" style="display: none;"></div>
                <div id="tenant-invite-error" style="display: none;"></div>
            </div>
        </div>
        <style>@keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }</style>`;

    try {
        const data = await window.API.tenantInviteSetup.validateToken(token);
        document.getElementById('tenant-invite-loading').style.display = 'none';

        if (!data || !data.valid) {
            document.getElementById('tenant-invite-error').style.display = 'block';
            document.getElementById('tenant-invite-error').innerHTML = `
                <p style="color: var(--danger-color); margin-bottom: 1rem;">Invalid or expired invite link. Please request a new one.</p>
                <a href="#login" class="btn btn-secondary">Back to sign in</a>`;
            return;
        }

        if (data.subdomain && typeof localStorage !== 'undefined') {
            try { localStorage.setItem('pharmasight_tenant_subdomain', data.subdomain); } catch (_) {}
        }

        const companyName = data.company_name || 'your company';
        const username = data.username || '';

        document.getElementById('tenant-invite-form').style.display = 'block';
        document.getElementById('tenant-invite-form').innerHTML = `
            <p style="margin-bottom: 1rem; color: var(--text-secondary);">
                Set a password for <strong>${escapeHtml(companyName)}</strong>.
                You’ll sign in with your username: <code style="background: #f0f0f0; padding: 2px 6px; border-radius: 4px;">${escapeHtml(username)}</code>
            </p>
            <form id="tenantInviteSetupForm">
                <div class="form-group">
                    <label for="tenantSetupPassword">Password</label>
                    <input type="password" id="tenantSetupPassword" required placeholder="Choose a password" minlength="8" autocomplete="new-password">
                    <small style="color: var(--text-secondary); margin-top: 0.25rem; display: block;">
                        At least 8 characters. Avoid numbers-only, letters-only, or common passwords.
                    </small>
                    <div id="tenantSetupValidationError" style="color: var(--danger-color); font-size: 0.875rem; margin-top: 0.25rem; display: none;"></div>
                </div>
                <div class="form-group">
                    <label for="tenantSetupConfirm">Confirm password</label>
                    <input type="password" id="tenantSetupConfirm" required placeholder="Confirm password" autocomplete="new-password">
                </div>
                <button type="submit" class="btn btn-primary btn-block"><i class="fas fa-key"></i> Set password & continue</button>
            </form>
            <div id="tenantSetupError" class="error-message" style="display: none; margin-top: 1rem;"></div>`;

        const form = document.getElementById('tenantInviteSetupForm');
        const errEl = document.getElementById('tenantSetupError');
        const valErrEl = document.getElementById('tenantSetupValidationError');
        const pwdInput = document.getElementById('tenantSetupPassword');

        if (pwdInput && window.PasswordValidation) {
            pwdInput.addEventListener('input', function () {
                var p = pwdInput.value;
                if (p.length > 0 && p.length < 8) {
                    valErrEl.textContent = 'Password must be at least 8 characters';
                    valErrEl.style.display = 'block';
                    pwdInput.style.borderColor = 'var(--danger-color)';
                } else if (window.PasswordValidation.validate(p).valid) {
                    valErrEl.style.display = 'none';
                    valErrEl.textContent = '';
                    pwdInput.style.borderColor = '';
                } else {
                    valErrEl.textContent = window.PasswordValidation.getFirstError(p);
                    valErrEl.style.display = 'block';
                    pwdInput.style.borderColor = 'var(--danger-color)';
                }
            });
        }

        form.onsubmit = async function (e) {
            e.preventDefault();
            var pwd = document.getElementById('tenantSetupPassword').value;
            var confirm = document.getElementById('tenantSetupConfirm').value;
            if (errEl) { errEl.style.display = 'none'; errEl.textContent = ''; }

            if (pwd.length < 8) {
                if (errEl) { errEl.textContent = 'Password must be at least 8 characters'; errEl.style.display = 'block'; }
                return;
            }
            if (window.PasswordValidation && !window.PasswordValidation.validate(pwd).valid) {
                if (errEl) { errEl.textContent = (window.PasswordValidation.validate(pwd).errors)[0] || 'Invalid password'; errEl.style.display = 'block'; }
                return;
            }
            if (pwd !== confirm) {
                if (errEl) { errEl.textContent = 'Passwords do not match'; errEl.style.display = 'block'; }
                return;
            }

            var btn = form.querySelector('button[type="submit"]');
            var origText = btn.innerHTML;
            btn.disabled = true;
            btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Setting up…';

            try {
                var res = await window.API.tenantInviteSetup.complete({ token: token, password: pwd });
                if (res && res.success) {
                    try { sessionStorage.setItem('tenant_invite_setup_done', '1'); } catch (_) {}
                    var base = window.location.origin + (window.location.pathname || '/');
                    var sub = typeof localStorage !== 'undefined' ? localStorage.getItem('pharmasight_tenant_subdomain') : null;
                    var loginUrl = base + (sub ? '?tenant=' + encodeURIComponent(sub) : '') + '#login';
                    window.location.replace(loginUrl);
                } else {
                    throw new Error(res && (res.message || res.detail) ? (res.message || res.detail) : 'Setup failed');
                }
            } catch (err) {
                var msg = (err && err.message) || (err.data && (err.data.detail || err.data.message)) || 'Setup failed. Please try again.';
                if (err.data && typeof err.data.detail === 'string') msg = err.data.detail;
                else if (err.data && err.data.detail && err.data.detail.length && typeof err.data.detail[0] === 'object' && err.data.detail[0].msg) msg = err.data.detail[0].msg;
                if (errEl) { errEl.textContent = msg; errEl.style.display = 'block'; }
            } finally {
                btn.disabled = false;
                btn.innerHTML = origText;
            }
        };
    } catch (err) {
        document.getElementById('tenant-invite-loading').style.display = 'none';
        var errDiv = document.getElementById('tenant-invite-error');
        errDiv.style.display = 'block';
        var msg = (err && err.message) || (err.data && (err.data.detail || err.data.message)) || 'Invalid or expired invite link.';
        if (err.data && typeof err.data.detail === 'string') msg = err.data.detail;
        errDiv.innerHTML = '<p style="color: var(--danger-color); margin-bottom: 1rem;">' + escapeHtml(msg) + '</p><a href="#login" class="btn btn-secondary">Back to sign in</a>';
    }
}

if (typeof window !== 'undefined') {
    window.loadTenantInviteSetup = loadTenantInviteSetup;
}
