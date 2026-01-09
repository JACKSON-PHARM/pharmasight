// Settings Page

async function loadSettings() {
    const page = document.getElementById('settings');
    
    page.innerHTML = `
        <div class="card">
            <div class="card-header">
                <h3 class="card-title">Settings</h3>
            </div>
            <form id="settingsForm" onsubmit="saveSettings(event)">
                <div class="form-group">
                    <label class="form-label">API Base URL</label>
                    <input type="text" class="form-input" name="api_base_url" 
                           value="${CONFIG.API_BASE_URL}" required>
                </div>
                
                <h4 style="margin-top: 2rem; margin-bottom: 1rem;">Company & Branch Configuration</h4>
                
                <div class="form-row">
                    <div class="form-group">
                        <label class="form-label">Company ID</label>
                        <input type="text" class="form-input" name="company_id" 
                               value="${CONFIG.COMPANY_ID || ''}" 
                               placeholder="UUID">
                        <small style="color: var(--text-secondary);">
                            Your company UUID from database
                        </small>
                    </div>
                    <div class="form-group">
                        <label class="form-label">Branch ID</label>
                        <input type="text" class="form-input" name="branch_id" 
                               value="${CONFIG.BRANCH_ID || ''}" 
                               placeholder="UUID">
                        <small style="color: var(--text-secondary);">
                            Your branch UUID from database
                        </small>
                    </div>
                </div>
                
                <div class="form-row">
                    <div class="form-group">
                        <label class="form-label">User ID</label>
                        <input type="text" class="form-input" name="user_id" 
                               value="${CONFIG.USER_ID || ''}" 
                               placeholder="UUID">
                        <small style="color: var(--text-secondary);">
                            Your user UUID (for audit trail)
                        </small>
                    </div>
                    <div class="form-group">
                        <label class="form-label">VAT Rate (%)</label>
                        <input type="number" class="form-input" name="vat_rate" 
                               value="${CONFIG.VAT_RATE}" 
                               step="0.01" min="0" max="100">
                    </div>
                </div>
                
                <div style="margin-top: 2rem;">
                    <button type="submit" class="btn btn-primary">
                        <i class="fas fa-save"></i> Save Settings
                    </button>
                    <button type="button" class="btn btn-secondary" onclick="resetSettings()">
                        <i class="fas fa-undo"></i> Reset to Defaults
                    </button>
                </div>
            </form>
        </div>
        
        <div class="card" style="margin-top: 2rem;">
            <div class="card-header">
                <h3 class="card-title">Instructions</h3>
            </div>
            <div>
                <h5>Getting Started:</h5>
                <ol>
                    <li>Make sure your FastAPI backend is running on ${CONFIG.API_BASE_URL}</li>
                    <li>Run the database schema in Supabase</li>
                    <li>Create a company and branch in the database (or via API)</li>
                    <li>Copy the Company ID and Branch ID UUIDs</li>
                    <li>Paste them in the settings above</li>
                    <li>Save settings</li>
                </ol>
                
                <h5 style="margin-top: 1rem;">Finding Your IDs:</h5>
                <p>You can find your Company and Branch IDs by:</p>
                <ul>
                    <li>Querying the database directly</li>
                    <li>Using the API endpoints (when implemented)</li>
                    <li>Checking the Supabase dashboard</li>
                </ul>
            </div>
        </div>
    `;
}

function saveSettings(event) {
    event.preventDefault();
    const form = event.target;
    const formData = new FormData(form);
    
    CONFIG.API_BASE_URL = formData.get('api_base_url');
    CONFIG.COMPANY_ID = formData.get('company_id') || null;
    CONFIG.BRANCH_ID = formData.get('branch_id') || null;
    CONFIG.USER_ID = formData.get('user_id') || null;
    CONFIG.VAT_RATE = parseFloat(formData.get('vat_rate') || 16.00);
    
    // Update API client base URL
    api.baseURL = CONFIG.API_BASE_URL;
    
    saveConfig();
    showToast('Settings saved successfully', 'success');
}

function resetSettings() {
    CONFIG.API_BASE_URL = 'http://localhost:8000';
    CONFIG.COMPANY_ID = null;
    CONFIG.BRANCH_ID = null;
    CONFIG.USER_ID = null;
    CONFIG.VAT_RATE = 16.00;
    
    saveConfig();
    loadSettings();
    showToast('Settings reset to defaults', 'info');
}

// Export
window.loadSettings = loadSettings;
window.saveSettings = saveSettings;
window.resetSettings = resetSettings;

