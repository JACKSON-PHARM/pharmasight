// Setup Wizard - Company and Branch Setup (Unified Startup Flow)

let setupStep = 1;
let setupData = {
    company: {},
    admin_user: {},
    branch: {}
};

async function loadSetup() {
    console.log('Loading setup wizard...');
    console.log('Current CONFIG:', { COMPANY_ID: CONFIG.COMPANY_ID, BRANCH_ID: CONFIG.BRANCH_ID });
    
    // Check authentication - user must be logged in (use AuthBootstrap for tenant + legacy)
    const user = (typeof AuthBootstrap !== 'undefined' && AuthBootstrap.getCurrentUser) ? AuthBootstrap.getCurrentUser() : (typeof Auth !== 'undefined' && Auth.getCurrentUser) ? await Auth.getCurrentUser() : null;
    if (!user) {
        console.log('User not authenticated, redirecting to login');
        loadPage('login');
        return;
    }
    
    // Set admin user data from authenticated user
    setupData.admin_user = {
        id: user.id,
        email: user.email,
        full_name: (user.user_metadata && user.user_metadata.full_name) || user.full_name || '',
        phone: (user.user_metadata && user.user_metadata.phone) || user.phone || ''
    };
    
    // Check if already configured in localStorage
    if (CONFIG.COMPANY_ID && CONFIG.BRANCH_ID) {
        console.log('Already configured, redirecting to dashboard');
        window.location.hash = '#dashboard';
        loadPage('dashboard');
        return;
    }

    // Check startup status (non-blocking - skip if slow, show setup anyway)
    // Use Promise.race to timeout after 5 seconds
    try {
        const statusPromise = API.startup.status();
        const timeoutPromise = new Promise((_, reject) => 
            setTimeout(() => reject(new Error('Status check timeout')), 5000)
        );
        
        const status = await Promise.race([statusPromise, timeoutPromise]);
        console.log('Startup status:', status);
        
        if (status && status.initialized) {
            // Company already exists, try to load existing data
            try {
                const companies = await API.company.list();
                if (companies && companies.length > 0) {
                    const company = companies[0];
                    CONFIG.COMPANY_ID = company.id;
                    const branches = await API.branch.list(company.id);
                    if (branches && branches.length > 0) {
                        CONFIG.BRANCH_ID = branches[0].id;
                        saveConfig();
                        console.log('Found existing company and branch, redirecting...');
                        window.location.hash = '#dashboard';
                        loadPage('dashboard');
                        return;
                    }
                }
            } catch (error) {
                console.log('Error loading existing company/branch:', error);
                // Continue to setup wizard anyway
            }
        }
    } catch (error) {
        console.log('Startup status check skipped (timeout or error), proceeding with setup:', error.message);
        // Continue to setup wizard - user can still fill the form
    }

    // Ensure setup page exists
    let page = document.getElementById('setup');
    if (!page) {
        console.log('Setup page not found, creating...');
        page = createSetupPage();
    }
    
    // Make sure setup page is visible
    page.classList.add('active');
    
    // Hide other pages
    document.querySelectorAll('.page').forEach(p => {
        if (p.id !== 'setup') {
            p.classList.remove('active');
        }
    });
    
    console.log('Rendering setup step...');
    renderSetupStep();
}

function createSetupPage() {
    const pageContent = document.getElementById('pageContent');
    const setupDiv = document.createElement('div');
    setupDiv.id = 'setup';
    setupDiv.className = 'page';
    pageContent.appendChild(setupDiv);
    return setupDiv;
}

function renderSetupStep() {
    const page = document.getElementById('setup');
    if (!page) {
        console.error('Setup page element not found!');
        return;
    }
    
    console.log('Rendering setup step:', setupStep);

    if (setupStep === 1) {
        renderCompanySetup();
    } else if (setupStep === 2) {
        renderAdminUserSetup();
    } else if (setupStep === 3) {
        renderBranchSetup();
    } else if (setupStep === 4) {
        renderCompletion();
    }
}

function renderCompanySetup() {
    const page = document.getElementById('setup');
    page.innerHTML = `
        <div class="setup-wizard">
            <div class="setup-header">
                <h2><i class="fas fa-building"></i> Welcome to PharmaSight</h2>
                <p class="setup-subtitle">Let's set up your pharmacy business</p>
            </div>

            <div class="setup-progress">
                <div class="progress-step active">
                    <div class="step-number">1</div>
                    <div class="step-label">Company</div>
                </div>
                <div class="progress-step">
                    <div class="step-number">2</div>
                    <div class="step-label">Admin User</div>
                </div>
                <div class="progress-step">
                    <div class="step-number">3</div>
                    <div class="step-label">Branch</div>
                </div>
                <div class="progress-step">
                    <div class="step-number">4</div>
                    <div class="step-label">Complete</div>
                </div>
            </div>

            <div class="card setup-card">
                <div class="card-header">
                    <h3>Step 1: Company Information</h3>
                    <p>Enter your company details below</p>
                </div>
                <form id="companyForm" onsubmit="saveCompanyStep(event)">
                    <div class="form-row">
                        <div class="form-group">
                            <label class="form-label">Company Name *</label>
                            <input type="text" class="form-input" name="name" required 
                                   placeholder="PharmaSight" value="${setupData.company.name || ''}">
                        </div>
                        <div class="form-group">
                            <label class="form-label">Registration Number</label>
                            <input type="text" class="form-input" name="registration_number" 
                                   placeholder="Business registration number" value="${setupData.company.registration_number || ''}">
                        </div>
                    </div>

                    <div class="form-row">
                        <div class="form-group">
                            <label class="form-label">PIN Number</label>
                            <input type="text" class="form-input" name="pin" 
                                   placeholder="KRA PIN" value="${setupData.company.pin || ''}">
                        </div>
                        <div class="form-group">
                            <label class="form-label">Phone Number</label>
                            <input type="tel" class="form-input" name="phone" 
                                   placeholder="Enter phone number" value="${setupData.company.phone || ''}">
                        </div>
                    </div>

                    <div class="form-group">
                        <label class="form-label">Email Address</label>
                        <input type="email" class="form-input" name="email" 
                               placeholder="info@pharmasight.com" value="${setupData.company.email || ''}">
                    </div>

                    <div class="form-group">
                        <label class="form-label">Business Address</label>
                        <textarea class="form-textarea" name="address" rows="3" 
                                  placeholder="Enter your business address">${setupData.company.address || ''}</textarea>
                    </div>

                    <div class="form-row">
                        <div class="form-group">
                            <label class="form-label">Currency</label>
                            <select class="form-select" name="currency">
                                <option value="KES" ${(setupData.company.currency || 'KES') === 'KES' ? 'selected' : ''}>KES - Kenyan Shilling</option>
                                <option value="USD" ${setupData.company.currency === 'USD' ? 'selected' : ''}>USD - US Dollar</option>
                                <option value="EUR" ${setupData.company.currency === 'EUR' ? 'selected' : ''}>EUR - Euro</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label class="form-label">Fiscal Year Start Date</label>
                            <input type="date" class="form-input" name="fiscal_start_date" 
                                   value="${setupData.company.fiscal_start_date || ''}">
                        </div>
                    </div>

                    <div class="form-actions">
                        <button type="submit" class="btn btn-primary btn-large">
                            Next: Admin User <i class="fas fa-arrow-right"></i>
                        </button>
                    </div>
                </form>
            </div>
        </div>
    `;
}

function renderAdminUserSetup() {
    const page = document.getElementById('setup');
    page.innerHTML = `
        <div class="setup-wizard">
            <div class="setup-header">
                <h2><i class="fas fa-user-shield"></i> Admin User Setup</h2>
                <p class="setup-subtitle">Create the administrator account</p>
            </div>

            <div class="setup-progress">
                <div class="progress-step completed">
                    <div class="step-number"><i class="fas fa-check"></i></div>
                    <div class="step-label">Company</div>
                </div>
                <div class="progress-step active">
                    <div class="step-number">2</div>
                    <div class="step-label">Admin User</div>
                </div>
                <div class="progress-step">
                    <div class="step-number">3</div>
                    <div class="step-label">Branch</div>
                </div>
                <div class="progress-step">
                    <div class="step-number">4</div>
                    <div class="step-label">Complete</div>
                </div>
            </div>

            <div class="card setup-card">
                <div class="card-header">
                    <h3>Step 2: Admin User Information</h3>
                    <p>Set up the administrator account for your pharmacy</p>
                    <small style="color: var(--text-secondary); display: block; margin-top: 0.5rem;">
                        Note: If using Supabase Auth, the User ID should match your Supabase Auth user_id.
                        Otherwise, you can use a temporary UUID for now.
                    </small>
                </div>
                <form id="adminUserForm" onsubmit="saveAdminUserStep(event)">
                    <div class="form-group">
                        <label class="form-label">User ID (UUID) *</label>
                        <input type="text" class="form-input" name="user_id" required 
                               placeholder="00000000-0000-0000-0000-000000000000" 
                               pattern="[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
                               value="${setupData.admin_user.id || ''}"
                               readonly
                               style="background-color: #f5f5f5; cursor: not-allowed;">
                        <small style="color: var(--text-secondary); display: block; margin-top: 0.25rem;">
                            <i class="fas fa-info-circle"></i> This is your authenticated user ID from Supabase Auth
                        </small>
                    </div>

                    <div class="form-group">
                        <label class="form-label">Email Address *</label>
                        <input type="email" class="form-input" name="email" required 
                               placeholder="admin@pharmasight.com" 
                               value="${setupData.admin_user.email || ''}"
                               readonly
                               style="background-color: #f5f5f5; cursor: not-allowed;">
                        <small style="color: var(--text-secondary); display: block; margin-top: 0.25rem;">
                            <i class="fas fa-info-circle"></i> This is your authenticated email from Supabase Auth
                        </small>
                    </div>

                    <div class="form-row">
                        <div class="form-group">
                            <label class="form-label">Full Name</label>
                            <input type="text" class="form-input" name="full_name" 
                                   placeholder="Admin User" 
                                   value="${setupData.admin_user.full_name || ''}">
                        </div>
                        <div class="form-group">
                            <label class="form-label">Phone Number</label>
                            <input type="tel" class="form-input" name="phone" 
                                   placeholder="0700000000" 
                                   value="${setupData.admin_user.phone || ''}">
                        </div>
                    </div>

                    <div class="form-actions">
                        <button type="button" class="btn btn-secondary" onclick="setupStep = 1; renderSetupStep();">
                            <i class="fas fa-arrow-left"></i> Back
                        </button>
                        <button type="submit" class="btn btn-primary btn-large">
                            Next: Branch Setup <i class="fas fa-arrow-right"></i>
                        </button>
                    </div>
                </form>
            </div>
        </div>
    `;
}

function renderBranchSetup() {
    const page = document.getElementById('setup');
    page.innerHTML = `
        <div class="setup-wizard">
            <div class="setup-header">
                <h2><i class="fas fa-store"></i> Branch Setup</h2>
                <p class="setup-subtitle">Create your first branch/location</p>
            </div>

            <div class="setup-progress">
                <div class="progress-step completed">
                    <div class="step-number"><i class="fas fa-check"></i></div>
                    <div class="step-label">Company</div>
                </div>
                <div class="progress-step completed">
                    <div class="step-number"><i class="fas fa-check"></i></div>
                    <div class="step-label">Admin User</div>
                </div>
                <div class="progress-step active">
                    <div class="step-number">3</div>
                    <div class="step-label">Branch</div>
                </div>
                <div class="progress-step">
                    <div class="step-number">4</div>
                    <div class="step-label">Complete</div>
                </div>
            </div>

            <div class="card setup-card">
                <div class="card-header">
                    <h3>Step 3: Branch Information</h3>
                    <p>Company: <strong>${setupData.company.name || 'Unknown'}</strong></p>
                </div>
                <form id="branchForm" onsubmit="saveBranchStep(event)">
                    <div class="form-row">
                        <div class="form-group">
                            <label class="form-label">Branch Name *</label>
                            <input type="text" class="form-input" name="name" required 
                                   placeholder="PharmaSight Main Branch" 
                                   value="${setupData.branch.name || ''}">
                        </div>
                        <div class="form-group">
                            <label class="form-label">Branch Code</label>
                            <input type="text" class="form-input" name="code" 
                                   placeholder="BR001 (auto-generated if first branch)" maxlength="50"
                                   value="${setupData.branch.code || ''}">
                            <small style="color: var(--text-secondary); display: block; margin-top: 0.25rem;">
                                Optional: Leave empty to auto-generate as "BR001" for first branch. 
                                Subsequent branches will be BR002, BR003, etc.
                            </small>
                        </div>
                    </div>

                    <div class="form-group">
                        <label class="form-label">Branch Address</label>
                        <textarea class="form-textarea" name="address" rows="3" 
                                  placeholder="Enter branch address">${setupData.branch.address || ''}</textarea>
                    </div>

                    <div class="form-group">
                        <label class="form-label">Branch Phone</label>
                        <input type="tel" class="form-input" name="phone" 
                               placeholder="Branch contact number" 
                               value="${setupData.branch.phone || ''}">
                    </div>

                    <div class="form-actions">
                        <button type="button" class="btn btn-secondary" onclick="setupStep = 2; renderSetupStep();">
                            <i class="fas fa-arrow-left"></i> Back
                        </button>
                        <button type="submit" class="btn btn-primary btn-large">
                            <i class="fas fa-rocket"></i> Complete Setup
                        </button>
                    </div>
                </form>
            </div>
        </div>
    `;
}

function renderCompletion() {
    const page = document.getElementById('setup');
    page.innerHTML = `
        <div class="setup-wizard">
            <div class="setup-header">
                <h2><i class="fas fa-check-circle" style="color: var(--success);"></i> Setup Complete!</h2>
                <p class="setup-subtitle">Your pharmacy is ready to use</p>
            </div>

            <div class="setup-progress">
                <div class="progress-step completed">
                    <div class="step-number"><i class="fas fa-check"></i></div>
                    <div class="step-label">Company</div>
                </div>
                <div class="progress-step completed">
                    <div class="step-number"><i class="fas fa-check"></i></div>
                    <div class="step-label">Admin User</div>
                </div>
                <div class="progress-step completed">
                    <div class="step-number"><i class="fas fa-check"></i></div>
                    <div class="step-label">Branch</div>
                </div>
                <div class="progress-step completed">
                    <div class="step-number"><i class="fas fa-check"></i></div>
                    <div class="step-label">Complete</div>
                </div>
            </div>

            <div class="card setup-card success-card">
                <div class="success-content">
                    <div class="success-icon">
                        <i class="fas fa-check-circle"></i>
                    </div>
                    <h3>Congratulations!</h3>
                    <p>Your company, admin user, and branch have been set up successfully.</p>
                    
                    <div class="setup-summary">
                        <div class="summary-item">
                            <strong>Company:</strong> ${setupData.company.name || 'Unknown'}
                        </div>
                        <div class="summary-item">
                            <strong>Admin User:</strong> ${setupData.admin_user.email || 'Unknown'}
                        </div>
                        <div class="summary-item">
                            <strong>Branch:</strong> ${setupData.branch.name || 'Unknown'} (${setupData.branch.code || 'N/A'})
                        </div>
                    </div>

                    <div class="setup-actions">
                        <button class="btn btn-primary btn-large" onclick="goToDashboard()">
                            <i class="fas fa-home"></i> Go to Dashboard
                        </button>
                        <button class="btn btn-secondary" onclick="goToAddItems()">
                            <i class="fas fa-box"></i> Add Inventory Items
                        </button>
                    </div>
                </div>
            </div>
        </div>
    `;
}

function saveCompanyStep(event) {
    event.preventDefault();
    const form = event.target;
    const formData = new FormData(form);
    
    setupData.company = {
        name: formData.get('name'),
        registration_number: formData.get('registration_number') || null,
        pin: formData.get('pin') || null,
        phone: formData.get('phone') || null,
        email: formData.get('email') || null,
        address: formData.get('address') || null,
        currency: formData.get('currency') || 'KES',
        timezone: 'Africa/Nairobi',
        fiscal_start_date: formData.get('fiscal_start_date') || null,
    };
    
    if (!setupData.company.name || setupData.company.name.trim() === '') {
        showToast('Company name is required', 'error');
        return;
    }
    
    setupStep = 2;
    renderSetupStep();
}

function saveAdminUserStep(event) {
    event.preventDefault();
    const form = event.target;
    const formData = new FormData(form);
    
    setupData.admin_user = {
        id: formData.get('user_id'),
        email: formData.get('email'),
        full_name: formData.get('full_name') || null,
        phone: formData.get('phone') || null,
    };
    
    if (!setupData.admin_user.id || !setupData.admin_user.email) {
        showToast('User ID and Email are required', 'error');
        return;
    }
    
    // Validate UUID format
    const uuidRegex = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
    if (!uuidRegex.test(setupData.admin_user.id)) {
        showToast('User ID must be a valid UUID format', 'error');
        return;
    }
    
    setupStep = 3;
    renderSetupStep();
}

async function saveBranchStep(event) {
    event.preventDefault();
    
    const form = event.target;
    const formData = new FormData(form);
    
    setupData.branch = {
        name: formData.get('name'),
        code: formData.get('code'),
        address: formData.get('address') || null,
        phone: formData.get('phone') || null,
    };
    
    // Validate required fields
    if (!setupData.branch.name || setupData.branch.name.trim() === '') {
        showToast('Branch name is required', 'error');
        return;
    }
    
    // Branch code is optional - will be auto-generated as BR001 if not provided
    if (setupData.branch.code) {
        setupData.branch.code = setupData.branch.code.trim().toUpperCase();
    }
    
    // Disable submit button
    const submitBtn = form.querySelector('button[type="submit"]');
    const originalBtnText = submitBtn.innerHTML;
    submitBtn.disabled = true;
    submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Setting up...';
    
    try {
        console.log('Initializing company with data:', setupData);
        
        // Call unified startup endpoint
        const result = await API.startup.initialize(setupData);
        
        console.log('Setup completed successfully:', result);
        
        // Mark setup as complete in Supabase Auth metadata
        try {
            await API.invite.markSetupComplete(setupData.admin_user.id);
            console.log('User metadata updated: must_setup_company = false');
        } catch (metadataError) {
            console.warn('Failed to update user metadata (non-critical):', metadataError);
            // Non-critical - setup is complete in database
        }
        
        // Save to config
        CONFIG.COMPANY_ID = result.company_id;
        CONFIG.BRANCH_ID = result.branch_id;
        CONFIG.USER_ID = result.user_id;
        saveConfig();
        
        showToast('Setup completed successfully!', 'success');
        setupStep = 4;
        renderSetupStep();
    } catch (error) {
        console.error('Error during setup:', error);
        
        let errorMessage = 'Error during setup. ';
        if (error.message) {
            errorMessage += error.message;
        } else if (error.detail) {
            errorMessage += error.detail;
        } else {
            errorMessage += 'Please check if the backend server is running and database schema is updated.';
        }
        
        showToast(errorMessage, 'error');
        
        // Re-enable button
        submitBtn.disabled = false;
        submitBtn.innerHTML = originalBtnText;
    }
}

function goToDashboard() {
    window.location.hash = '#dashboard';
    if (window.loadDashboard) {
        window.loadDashboard();
    }
}

function goToAddItems() {
    window.location.hash = '#items';
    if (window.loadItems) {
        window.loadItems();
    }
}

// Export functions to global scope
window.loadSetup = loadSetup;
window.saveCompanyStep = saveCompanyStep;
window.saveAdminUserStep = saveAdminUserStep;
window.saveBranchStep = saveBranchStep;
window.goToDashboard = goToDashboard;
window.goToAddItems = goToAddItems;
window.renderSetupStep = renderSetupStep;
