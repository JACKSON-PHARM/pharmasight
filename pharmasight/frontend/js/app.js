// Main Application Logic

let currentPage = 'dashboard';

// Initialize app
document.addEventListener('DOMContentLoaded', async () => {
    console.log('✅ DOM Content Loaded - Initializing app...');
    
    // Hide loading indicator if it exists
    const loadingIndicator = document.getElementById('appLoading');
    if (loadingIndicator) {
        loadingIndicator.style.display = 'none';
    }
    
    // Ensure dashboard is visible by default
    const dashboard = document.getElementById('dashboard');
    if (dashboard) {
        dashboard.style.display = 'block';
    }
    
    // Ensure at least dashboard is visible
    const dashboard = document.getElementById('dashboard');
    if (dashboard && !dashboard.classList.contains('active')) {
        dashboard.classList.add('active');
    }
    
    console.log('✅ CONFIG loaded:', { COMPANY_ID: CONFIG.COMPANY_ID, BRANCH_ID: CONFIG.BRANCH_ID });
    
    try {
        // Initialize Supabase Auth
        console.log('🔐 Initializing Supabase Auth...');
        Auth.initSupabase();
        
        // Check authentication and setup status (with timeout)
        console.log('🔍 Checking authentication and setup status...');
        const authCheckPromise = checkAuthAndSetup();
        const timeoutPromise = new Promise((resolve) => {
            setTimeout(() => {
                console.warn('⏱️ Auth check timed out after 10 seconds, showing login page...');
                loadPage('login');
                resolve();
            }, 10000);
        });
        
        await Promise.race([authCheckPromise, timeoutPromise]);
    } catch (error) {
        console.error('❌ Error during app initialization:', error);
        // Fallback: show login page
        loadPage('login');
    }
    
    // Always initialize navigation and menu toggle
    console.log('🧭 Initializing navigation...');
    try {
        initializeNavigation();
        initializeMenuToggle();
    } catch (error) {
        console.error('❌ Error initializing navigation:', error);
    }
    console.log('✅ App initialization complete');
});

/**
 * Check authentication status and redirect accordingly
 */
async function checkAuthAndSetup() {
    try {
        console.log('👤 Getting current user...');
        const user = await Promise.race([
            Auth.getCurrentUser(),
            new Promise((_, reject) => setTimeout(() => reject(new Error('Timeout')), 5000))
        ]);
        
        if (!user) {
            // Not authenticated - show login
            console.log('👤 User not authenticated, showing login page...');
            loadPage('login');
            return;
        }
        
        console.log('✅ User authenticated:', user.email || user.id);
        
        // User is authenticated
        CONFIG.USER_ID = user.id;
        
        // Update username display
        const usernameSpan = document.getElementById('username');
        if (usernameSpan) {
            usernameSpan.textContent = user.email || user.user_metadata?.full_name || 'User';
        }
        
        // Show sidebar
        const sidebar = document.getElementById('sidebar');
        if (sidebar) {
            sidebar.style.display = 'flex';
        }
        
        // Check if setup is needed (with timeout protection)
        let redirect;
        try {
            redirect = await Promise.race([
                Auth.shouldRedirectToSetup(),
                new Promise((_, reject) => setTimeout(() => reject(new Error('Timeout')), 10000))
            ]);
        } catch (error) {
            console.warn('Auth check timed out, defaulting to login:', error);
            loadPage('login');
            return;
        }
        
        if (redirect.redirect === 'setup') {
            console.log('Setup required, redirecting to setup wizard...');
            loadPage('setup');
        } else if (CONFIG.COMPANY_ID && CONFIG.BRANCH_ID) {
            // Already configured, go to dashboard
            loadPage('dashboard');
        } else {
            // Need to load company/branch from database (with timeout)
            try {
                const statusPromise = API.startup.status();
                const timeoutPromise = new Promise((_, reject) => 
                    setTimeout(() => reject(new Error('Timeout')), 5000)
                );
                
                const status = await Promise.race([statusPromise, timeoutPromise]);
                if (status.initialized && status.company_id) {
                    CONFIG.COMPANY_ID = status.company_id;
                    // Try to get branches
                    const companies = await Promise.race([
                        API.company.list(),
                        new Promise((_, reject) => setTimeout(() => reject(new Error('Timeout')), 5000))
                    ]);
                    if (companies && companies.length > 0) {
                        const branches = await Promise.race([
                            API.branch.list(companies[0].id),
                            new Promise((_, reject) => setTimeout(() => reject(new Error('Timeout')), 5000))
                        ]);
                        if (branches && branches.length > 0) {
                            CONFIG.BRANCH_ID = branches[0].id;
                            saveConfig();
                            loadPage('dashboard');
                            return;
                        }
                    }
                }
            } catch (error) {
                console.log('Error loading company/branch (non-critical):', error);
                // Continue to setup if loading fails
            }
            
            // If we get here, setup is needed
            loadPage('setup');
        }
    } catch (error) {
        console.error('Error checking auth:', error);
        // On error, show login
        loadPage('login');
    }
}

// Sub-navigation definitions
window.subNavItems = {
    sales: [
        { page: 'sales', label: 'Point of Sale', icon: 'fa-cash-register' },
        { page: 'sales-history', label: 'Sales History', icon: 'fa-history' },
        { page: 'sales-returns', label: 'Returns', icon: 'fa-undo' }
    ],
    purchases: [
        { page: 'purchases', subPage: 'orders', label: 'Purchase Orders', icon: 'fa-file-invoice' },
        { page: 'purchases', subPage: 'invoices', label: 'Purchase Invoices', icon: 'fa-file-invoice-dollar' },
        { page: 'purchases', subPage: 'credit-notes', label: 'Credit Notes', icon: 'fa-file-invoice' },
        { page: 'purchases', subPage: 'suppliers', label: 'Suppliers', icon: 'fa-truck' }
    ],
    inventory: [
        { page: 'inventory', subPage: 'items', label: 'Items', icon: 'fa-box' },
        { page: 'inventory', subPage: 'batch', label: 'Batch Tracking', icon: 'fa-tags' },
        { page: 'inventory', subPage: 'expiry', label: 'Expiry Report', icon: 'fa-calendar-times' },
        { page: 'inventory', subPage: 'movement', label: 'Item Movement', icon: 'fa-exchange-alt' },
        { page: 'inventory', subPage: 'stock', label: 'Current Stock', icon: 'fa-chart-bar' }
    ],
    expenses: [
        { page: 'expenses', label: 'All Expenses', icon: 'fa-money-bill-wave' },
        { page: 'expenses-categories', label: 'Categories', icon: 'fa-folder' },
        { page: 'expenses-reports', label: 'Reports', icon: 'fa-chart-pie' }
    ],
    reports: [
        { page: 'reports-sales', label: 'Sales Reports', icon: 'fa-chart-line' },
        { page: 'reports-inventory', label: 'Inventory Reports', icon: 'fa-warehouse' },
        { page: 'reports-financial', label: 'Financial Reports', icon: 'fa-dollar-sign' },
        { page: 'reports-custom', label: 'Custom Reports', icon: 'fa-file-alt' }
    ],
    settings: [
        { page: 'settings', label: 'General Settings', icon: 'fa-cog' },
        { page: 'settings-company', label: 'Company', icon: 'fa-building' },
        { page: 'settings-users', label: 'Users & Roles', icon: 'fa-users' },
        { page: 'settings-pricing', label: 'Pricing Rules', icon: 'fa-tags' }
    ]
};

// Global navigation state
let isNavigating = false;
let navigationDebounceTimer = null;

// Navigation functions (global scope for accessibility)
function showMainNav() {
    if (isNavigating) return; // Prevent multiple rapid calls
    isNavigating = true;
    
    const sidebar = document.getElementById('sidebar');
    const mainNav = document.getElementById('mainNav');
    const subNav = document.getElementById('subNav');
    
    if (!sidebar || !mainNav || !subNav) {
        isNavigating = false;
        return;
    }
    
    // Use requestAnimationFrame for smooth transitions
    requestAnimationFrame(() => {
        sidebar.classList.remove('showing-sub');
        mainNav.style.display = 'flex';
        subNav.style.display = 'none';
        
        // Reset flag after transition
        setTimeout(() => {
            isNavigating = false;
        }, 300);
    });
}

function showSubNav(pageKey, title) {
    if (isNavigating) return; // Prevent multiple rapid calls
    isNavigating = true;
    
    const sidebar = document.getElementById('sidebar');
    const mainNav = document.getElementById('mainNav');
    const subNav = document.getElementById('subNav');
    const subNavItemsContainer = document.getElementById('subNavItems');
    const subNavTitle = document.getElementById('subNavTitle');
    
    if (!sidebar || !mainNav || !subNav || !subNavItemsContainer || !subNavTitle) {
        isNavigating = false;
        return;
    }
    
    const items = window.subNavItems && window.subNavItems[pageKey];
    if (!items) {
        isNavigating = false;
        return;
    }
    
    subNavTitle.textContent = title;
    subNavItemsContainer.innerHTML = items.map(item => `
        <a href="#" class="sub-nav-item" data-page="${item.page}" ${item.subPage ? `data-sub-page="${item.subPage}"` : ''}>
            <i class="fas ${item.icon}"></i>
            <span>${item.label}</span>
        </a>
    `).join('');
    
    // Add click handlers to sub-nav items (use event delegation for better performance)
    subNavItemsContainer.addEventListener('click', function subNavClickHandler(e) {
        const subItem = e.target.closest('.sub-nav-item');
        if (!subItem) return;
        
        e.preventDefault();
        
        // Debounce rapid clicks
        if (navigationDebounceTimer) {
            clearTimeout(navigationDebounceTimer);
        }
        
        navigationDebounceTimer = setTimeout(() => {
            const page = subItem.dataset.page;
            const subPage = subItem.dataset.subPage;
            
            // Update active state
            subNavItemsContainer.querySelectorAll('.sub-nav-item').forEach(nav => nav.classList.remove('active'));
            subItem.classList.add('active');
            
            // Load page
            if (subPage) {
                // For inventory, set the sub-page
                if (page === 'inventory' && window.switchInventorySubPage) {
                    loadPage(page);
                    setTimeout(() => {
                        if (window.switchInventorySubPage) {
                            window.switchInventorySubPage(subPage);
                        }
                    }, 100);
                } else if (page === 'purchases') {
                    // For purchases, load the page first, then switch to sub-page if specified
                    loadPage(page);
                    if (subPage && window.switchPurchaseSubPage) {
                        setTimeout(() => {
                            window.switchPurchaseSubPage(subPage);
                        }, 100);
                    } else if (!subPage && window.loadPurchases) {
                        // If no sub-page specified, ensure default sub-page loads
                        setTimeout(() => {
                            window.loadPurchases();
                        }, 100);
                    }
                } else {
                    loadPage(page);
                }
            } else {
                loadPage(page);
            }
        }, 150);
    }, { once: false, passive: false });
    
    // Use requestAnimationFrame for smooth transitions
    requestAnimationFrame(() => {
        sidebar.classList.add('showing-sub');
        mainNav.style.display = 'none';
        subNav.style.display = 'flex';
        
        // Reset flag after transition
        setTimeout(() => {
            isNavigating = false;
        }, 300);
    });
}

// Navigation
function initializeNavigation() {
    const sidebar = document.getElementById('sidebar');
    const mainNav = document.getElementById('mainNav');
    const subNav = document.getElementById('subNav');
    const sidebarToggle = document.getElementById('sidebarToggle');
    const backToMainNav = document.getElementById('backToMainNav');
    
    if (!sidebar || !mainNav || !subNav) {
        console.error('Navigation elements not found');
        return;
    }
    
    // Sidebar collapse/expand toggle
    if (sidebarToggle) {
        sidebarToggle.addEventListener('click', (e) => {
            e.stopPropagation();
            e.preventDefault();
            
            // Debounce rapid clicks
            if (navigationDebounceTimer) {
                clearTimeout(navigationDebounceTimer);
            }
            
            navigationDebounceTimer = setTimeout(() => {
                sidebar.classList.toggle('collapsed');
                // If showing sub-nav, go back to main nav when collapsing
                if (sidebar.classList.contains('showing-sub') && sidebar.classList.contains('collapsed')) {
                    showMainNav();
                }
            }, 100);
        }, { passive: false });
    }
    
    // Back to main nav button - use event delegation
    if (backToMainNav) {
        backToMainNav.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            
            // Debounce rapid clicks
            if (navigationDebounceTimer) {
                clearTimeout(navigationDebounceTimer);
            }
            
            navigationDebounceTimer = setTimeout(() => {
                showMainNav();
            }, 100);
        }, { passive: false });
    }
    
    // Main nav items - use event delegation for better performance
    if (mainNav) {
        mainNav.addEventListener('click', (e) => {
            const navItem = e.target.closest('.nav-item');
            if (!navItem) return;
            
            e.preventDefault();
            e.stopPropagation();
            
            // Debounce rapid clicks
            if (navigationDebounceTimer) {
                clearTimeout(navigationDebounceTimer);
            }
            
            navigationDebounceTimer = setTimeout(() => {
                const page = navItem.dataset.page;
                const hasSub = navItem.dataset.hasSub === 'true';
                
                if (hasSub && window.subNavItems && window.subNavItems[page]) {
                    // Show sub-navigation
                    showSubNav(page, navItem.querySelector('span')?.textContent || page);
                } else {
                    // Direct page navigation (no sub-items)
                    loadPage(page);
                    showMainNav();
                    
                    // Update active state
                    document.querySelectorAll('.nav-item').forEach(nav => nav.classList.remove('active'));
                    navItem.classList.add('active');
                }
            }, 150);
        }, { passive: false });
    }
}

// Export navigation functions globally
window.showMainNav = showMainNav;
window.showSubNav = showSubNav;

// Menu toggle (mobile)
function initializeMenuToggle() {
    const menuToggle = document.getElementById('menuToggle');
    const sidebar = document.getElementById('sidebar');
    
    if (menuToggle) {
        menuToggle.addEventListener('click', () => {
            sidebar.classList.toggle('open');
        });
    }
}

// Load page
function loadPage(pageName) {
    console.log('📄 Loading page:', pageName);
    currentPage = pageName;
    
    // Update URL hash
    try {
        window.location.hash = `#${pageName}`;
    } catch (e) {
        console.warn('Could not update URL hash:', e);
    }
    
    // Hide all pages
    const allPages = document.querySelectorAll('.page');
    console.log(`📄 Found ${allPages.length} page elements`);
    allPages.forEach(page => {
        page.classList.remove('active');
    });
    
    // Show selected page
    const pageElement = document.getElementById(pageName);
    if (pageElement) {
        pageElement.classList.add('active');
        console.log('✅ Page element found and activated:', pageName);
        // Force display in case CSS isn't working
        pageElement.style.display = 'block';
        pageElement.style.visibility = 'visible';
    } else {
        console.error('❌ Page element not found:', pageName);
        // Fallback: show dashboard if requested page doesn't exist
        const dashboard = document.getElementById('dashboard');
        if (dashboard) {
            dashboard.classList.add('active');
            dashboard.style.display = 'block';
            dashboard.style.visibility = 'visible';
            console.log('⚠️ Fallback: showing dashboard instead');
        }
    }
    
    // Show/hide action buttons
    const newSaleBtn = document.getElementById('newSaleBtn');
    const newPurchaseBtn = document.getElementById('newPurchaseBtn');
    
    newSaleBtn.style.display = pageName === 'sales' ? 'block' : 'none';
    if (newPurchaseBtn) {
        if (pageName === 'purchases') {
            newPurchaseBtn.style.display = 'block';
            // Connect the button to create function
            newPurchaseBtn.onclick = function() {
                console.log('🔴 [TOP BAR BUTTON] New Purchase button clicked');
                console.log('🔴 [TOP BAR BUTTON] window.createNewPurchaseOrder type:', typeof window.createNewPurchaseOrder);
                console.log('🔴 [TOP BAR BUTTON] window.createNewPurchaseOrder value:', window.createNewPurchaseOrder);
                
                if (window.createNewPurchaseOrder) {
                    console.log('🔴 [TOP BAR BUTTON] Calling window.createNewPurchaseOrder()...');
                    window.createNewPurchaseOrder();
                } else {
                    console.error('❌ [TOP BAR BUTTON] createNewPurchaseOrder function not found!');
                    console.error('❌ [TOP BAR BUTTON] Available window functions:', Object.keys(window).filter(k => k.includes('Purchase')));
                }
            };
        } else {
            newPurchaseBtn.style.display = 'none';
            newPurchaseBtn.onclick = null;
        }
    }
    
    // Load page content
    switch(pageName) {
        case 'login':
            if (window.loadLogin) window.loadLogin();
            break;
        case 'setup':
            if (window.loadSetup) window.loadSetup();
            break;
        case 'dashboard':
            if (window.loadDashboard) window.loadDashboard();
            break;
        case 'sales':
            if (window.loadSales) window.loadSales();
            break;
        case 'purchases':
            if (window.loadPurchases) window.loadPurchases();
            break;
        case 'inventory':
            console.log('Loading inventory page...');
            if (window.loadInventory) {
                window.loadInventory();
            } else {
                console.error('loadInventory function not found on window object');
            }
            break;
        case 'settings':
            if (window.loadSettings) window.loadSettings();
            break;
    }
}

// Export for use in other scripts
window.loadPage = loadPage;
window.currentPage = currentPage;

