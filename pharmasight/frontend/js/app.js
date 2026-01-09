// Main Application Logic

let currentPage = 'dashboard';

// Initialize app
document.addEventListener('DOMContentLoaded', () => {
    initializeNavigation();
    initializeMenuToggle();
    loadPage('dashboard');
    
    // Check if company/branch is set
    if (!CONFIG.COMPANY_ID || !CONFIG.BRANCH_ID) {
        showToast('Please configure Company and Branch in Settings', 'warning');
    }
});

// Navigation
function initializeNavigation() {
    const navItems = document.querySelectorAll('.nav-item');
    navItems.forEach(item => {
        item.addEventListener('click', (e) => {
            e.preventDefault();
            const page = item.dataset.page;
            loadPage(page);
            
            // Update active state
            navItems.forEach(nav => nav.classList.remove('active'));
            item.classList.add('active');
        });
    });
}

// Menu toggle (mobile)
function initializeMenuToggle() {
    const menuToggle = document.getElementById('menuToggle');
    const sidebar = document.getElementById('sidebar');
    
    menuToggle.addEventListener('click', () => {
        sidebar.classList.toggle('open');
    });
}

// Load page
function loadPage(pageName) {
    currentPage = pageName;
    
    // Hide all pages
    document.querySelectorAll('.page').forEach(page => {
        page.classList.remove('active');
    });
    
    // Show selected page
    const pageElement = document.getElementById(pageName);
    if (pageElement) {
        pageElement.classList.add('active');
    }
    
    // Show/hide action buttons
    const newSaleBtn = document.getElementById('newSaleBtn');
    const newPurchaseBtn = document.getElementById('newPurchaseBtn');
    
    newSaleBtn.style.display = pageName === 'sales' ? 'block' : 'none';
    newPurchaseBtn.style.display = pageName === 'purchases' ? 'block' : 'none';
    
    // Load page content
    switch(pageName) {
        case 'dashboard':
            if (window.loadDashboard) window.loadDashboard();
            break;
        case 'items':
            if (window.loadItems) window.loadItems();
            break;
        case 'sales':
            if (window.loadSales) window.loadSales();
            break;
        case 'purchases':
            if (window.loadPurchases) window.loadPurchases();
            break;
        case 'inventory':
            if (window.loadInventory) window.loadInventory();
            break;
        case 'settings':
            if (window.loadSettings) window.loadSettings();
            break;
    }
}

// Export for use in other scripts
window.loadPage = loadPage;
window.currentPage = currentPage;

