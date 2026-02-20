/**
 * Change password modal for logged-in users.
 * User enters current password and new password (with confirm); no email link.
 */
(function () {
    function getChangePasswordContent() {
        return `
            <form id="changePasswordForm" class="change-password-form">
                <div class="form-group">
                    <label for="changePasswordCurrent">Current password</label>
                    <input type="password" id="changePasswordCurrent" required 
                           placeholder="Enter your current password" autocomplete="current-password">
                </div>
                <div class="form-group">
                    <label for="changePasswordNew">New password</label>
                    <input type="password" id="changePasswordNew" required 
                           placeholder="Enter new password" minlength="6" autocomplete="new-password">
                    <p class="form-hint">At least 6 characters. Not numbers only, letters only, or common passwords.</p>
                    <div id="changePasswordStrength" class="password-strength" style="font-size: 0.75rem; margin-top: 0.25rem;"></div>
                    <div id="changePasswordValidationError" class="error-message" style="display: none;"></div>
                </div>
                <div class="form-group">
                    <label for="changePasswordConfirm">Confirm new password</label>
                    <input type="password" id="changePasswordConfirm" required 
                           placeholder="Re-enter new password" minlength="6" autocomplete="new-password">
                    <div id="changePasswordConfirmError" class="error-message" style="display: none;"></div>
                </div>
            </form>
        `;
    }

    function getChangePasswordFooter() {
        return `
            <button type="button" class="btn btn-secondary" onclick="closeModal()">Cancel</button>
            <button type="button" class="btn btn-primary" id="changePasswordSubmitBtn">
                <i class="fas fa-key"></i> Update password
            </button>
        `;
    }

    function openChangePasswordModal() {
        if (typeof showModal !== 'function') return;
        showModal('Change password', getChangePasswordContent(), getChangePasswordFooter());

        const form = document.getElementById('changePasswordForm');
        const currentInput = document.getElementById('changePasswordCurrent');
        const newInput = document.getElementById('changePasswordNew');
        const confirmInput = document.getElementById('changePasswordConfirm');
        const strengthDiv = document.getElementById('changePasswordStrength');
        const validationErrorDiv = document.getElementById('changePasswordValidationError');
        const confirmErrorDiv = document.getElementById('changePasswordConfirmError');
        const submitBtn = document.getElementById('changePasswordSubmitBtn');

        if (!form || !newInput || !confirmInput || !submitBtn) return;

        function validateNewPassword() {
            const password = newInput.value;
            if (!password) {
                if (strengthDiv) strengthDiv.textContent = '';
                if (validationErrorDiv) { validationErrorDiv.style.display = 'none'; validationErrorDiv.textContent = ''; }
                return false;
            }
            if (window.PasswordValidation && window.PasswordValidation.validateRealTime) {
                const errorMsg = window.PasswordValidation.validateRealTime(password);
                const valid = !errorMsg;
                if (strengthDiv) strengthDiv.textContent = valid ? 'OK' : errorMsg;
                if (strengthDiv) strengthDiv.style.color = valid ? 'var(--success-color, green)' : 'var(--danger-color, #c00)';
                if (validationErrorDiv) {
                    validationErrorDiv.style.display = valid ? 'none' : 'block';
                    validationErrorDiv.textContent = valid ? '' : errorMsg;
                }
                return valid;
            }
            if (password.length < 6) {
                if (strengthDiv) strengthDiv.textContent = 'At least 6 characters required.';
                if (strengthDiv) strengthDiv.style.color = 'var(--danger-color, #c00)';
                if (validationErrorDiv) { validationErrorDiv.style.display = 'block'; validationErrorDiv.textContent = 'At least 6 characters required.'; }
                return false;
            }
            if (strengthDiv) strengthDiv.textContent = '';
            if (validationErrorDiv) validationErrorDiv.style.display = 'none';
            return true;
        }

        function validateConfirm() {
            const ok = newInput.value && newInput.value === confirmInput.value;
            if (confirmErrorDiv) {
                confirmErrorDiv.style.display = ok ? 'none' : 'block';
                confirmErrorDiv.textContent = ok ? '' : 'Passwords do not match.';
            }
            return ok;
        }

        if (newInput) {
            newInput.addEventListener('input', validateNewPassword);
            newInput.addEventListener('blur', validateNewPassword);
        }
        if (confirmInput) {
            confirmInput.addEventListener('input', validateConfirm);
            confirmInput.addEventListener('blur', validateConfirm);
        }

        submitBtn.addEventListener('click', async function () {
            const current = currentInput ? currentInput.value : '';
            const newPw = newInput.value;
            const confirm = confirmInput.value;

            if (!current) {
                if (typeof showToast === 'function') showToast('Enter your current password.', 'error');
                return;
            }
            if (!validateNewPassword()) {
                if (typeof showToast === 'function') showToast('Please fix the new password requirements.', 'error');
                return;
            }
            if (!validateConfirm()) {
                if (typeof showToast === 'function') showToast('New password and confirmation do not match.', 'error');
                return;
            }

            submitBtn.disabled = true;
            submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Updating...';

            const baseUrl = (typeof CONFIG !== 'undefined' && CONFIG.API_BASE_URL) ? CONFIG.API_BASE_URL : '';
            const token = typeof localStorage !== 'undefined' ? localStorage.getItem('pharmasight_access_token') : null;
            const tenantSub = typeof sessionStorage !== 'undefined' ? sessionStorage.getItem('pharmasight_tenant_subdomain') : null
                || (typeof localStorage !== 'undefined' ? localStorage.getItem('pharmasight_tenant_subdomain') : null);

            try {
                const headers = { 'Content-Type': 'application/json' };
                if (token) headers['Authorization'] = 'Bearer ' + token;
                if (tenantSub) headers['X-Tenant-Subdomain'] = tenantSub;

                const res = await fetch(baseUrl.replace(/\/$/, '') + '/api/auth/change-password', {
                    method: 'POST',
                    headers,
                    body: JSON.stringify({ current_password: current, new_password: newPw })
                });
                const data = await res.json().catch(() => ({}));
                if (!res.ok) {
                    const msg = data.detail || data.message || (typeof data.detail === 'object' && data.detail.detail) || 'Failed to update password.';
                    throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
                }
                if (typeof closeModal === 'function') closeModal();
                if (typeof showToast === 'function') showToast('Password updated successfully.', 'success');
            } catch (err) {
                if (typeof showToast === 'function') showToast(err.message || 'Failed to update password.', 'error');
            } finally {
                submitBtn.disabled = false;
                submitBtn.innerHTML = '<i class="fas fa-key"></i> Update password';
            }
        });
    }

    window.openChangePasswordModal = openChangePasswordModal;
})();
