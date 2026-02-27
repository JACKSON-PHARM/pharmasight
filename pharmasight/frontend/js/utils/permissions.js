/**
 * Permission checking utilities for frontend
 * Checks user permissions against required permissions for features/cards/data
 */

// Cache user permissions
let cachedUserPermissions = null;
let cachedPermissionsTimestamp = null;
const PERMISSIONS_CACHE_TTL = 60000; // 1 minute

/**
 * Get current user's permissions (cached)
 * @param {string} branchId - Optional branch ID to check permissions for
 * @returns {Promise<Set<string>>} Set of permission names
 */
async function getUserPermissions(branchId = null) {
    const userId = typeof CONFIG !== 'undefined' && CONFIG.USER_ID ? CONFIG.USER_ID : null;
    if (!userId) {
        return new Set();
    }
    
    // Check cache
    const now = Date.now();
    if (cachedUserPermissions && cachedPermissionsTimestamp && 
        (now - cachedPermissionsTimestamp) < PERMISSIONS_CACHE_TTL) {
        return cachedUserPermissions;
    }
    
    try {
        if (API && API.users && API.users.getUserPermissions) {
            const result = await API.users.getUserPermissions(userId, branchId);
            cachedUserPermissions = new Set(result.permissions || []);
            cachedPermissionsTimestamp = now;
            return cachedUserPermissions;
        }
    } catch (error) {
        console.warn('Error fetching user permissions:', error);
    }
    
    return new Set();
}

/**
 * Check if user has a specific permission
 * @param {string} permissionName - Permission name to check (e.g., 'sales.view_all')
 * @param {string} branchId - Optional branch ID
 * @returns {Promise<boolean>}
 */
async function hasPermission(permissionName, branchId = null) {
    const permissions = await getUserPermissions(branchId);
    return permissions.has(permissionName);
}

/**
 * Check if user has any of the specified permissions
 * @param {string[]} permissionNames - Array of permission names
 * @param {string} branchId - Optional branch ID
 * @returns {Promise<boolean>}
 */
async function hasAnyPermission(permissionNames, branchId = null) {
    const permissions = await getUserPermissions(branchId);
    return permissionNames.some(name => permissions.has(name));
}

/**
 * Check if user has all of the specified permissions
 * @param {string[]} permissionNames - Array of permission names
 * @param {string} branchId - Optional branch ID
 * @returns {Promise<boolean>}
 */
async function hasAllPermissions(permissionNames, branchId = null) {
    const permissions = await getUserPermissions(branchId);
    return permissionNames.every(name => permissions.has(name));
}

/**
 * Clear permissions cache (call when user changes role/branch)
 */
function clearPermissionsCache() {
    cachedUserPermissions = null;
    cachedPermissionsTimestamp = null;
}

/**
 * Check dashboard card visibility based on permissions
 * Card-specific permission mappings
 */
const DASHBOARD_CARD_PERMISSIONS = {
    'totalItems': ['dashboard.view_items', 'items.view'],
    'totalStock': ['dashboard.view_inventory', 'inventory.view'],
    'totalStockValue': ['dashboard.view_stock_value', 'inventory.view', 'inventory.view_cost'],
    'todaySales': ['dashboard.view_sales', 'sales.view_own', 'sales.view_all'],
    'ordersProcessed': ['dashboard.view_sales', 'sales.view_own', 'sales.view_all'],
    // Gross profit reveals cost, so require cost-related permissions (or admin).
    'todayGrossProfit': ['inventory.view_cost', 'items.view_cost', 'admin.manage_company'],
    'expiringItems': ['dashboard.view_expiring', 'inventory.view'],
    'orderBookPendingToday': ['dashboard.view_order_book', 'orders.view'],
};

/**
 * Permissions that imply full admin (see all dashboard cards).
 * Uses permissions that exist in DB: users.edit is granted to admin in migration 019.
 */
const ADMIN_IMPLYING_PERMISSIONS = ['users.edit', 'admin.manage_company'];

/**
 * Check if a dashboard card should be visible
 * @param {string} cardId - Card ID (e.g., 'totalItems', 'todaySales')
 * @param {string} branchId - Optional branch ID
 * @returns {Promise<boolean>}
 */
async function canViewDashboardCard(cardId, branchId = null) {
    // Admin-style roles (users.edit / admin.manage_company) see all dashboard cards
    if (await hasAnyPermission(ADMIN_IMPLYING_PERMISSIONS, branchId)) {
        return true;
    }
    const requiredPerms = DASHBOARD_CARD_PERMISSIONS[cardId];
    if (!requiredPerms || requiredPerms.length === 0) {
        return true; // No restrictions, show by default
    }
    return hasAnyPermission(requiredPerms, branchId);
}

/**
 * Check if user can view all sales or only their own
 * @param {string} branchId - Optional branch ID
 * @returns {Promise<{canViewAll: boolean, canViewOwn: boolean}>}
 */
async function getSalesViewPermissions(branchId = null) {
    const permissions = await getUserPermissions(branchId);
    return {
        canViewAll: permissions.has('sales.view_all'),
        canViewOwn: permissions.has('sales.view_own') || permissions.has('sales.view_all'),
    };
}

/**
 * Check if user can view unit cost/purchase price
 * @param {string} branchId - Optional branch ID
 * @returns {Promise<boolean>}
 */
async function canViewUnitCost(branchId = null) {
    return hasAnyPermission([
        'items.view_cost',
        'inventory.view_cost',
        'purchases.view',
        'purchases.create',
        'admin.manage_company'
    ], branchId);
}

// Export functions
if (typeof window !== 'undefined') {
    window.Permissions = {
        getUserPermissions,
        hasPermission,
        hasAnyPermission,
        hasAllPermissions,
        clearPermissionsCache,
        canViewDashboardCard,
        getSalesViewPermissions,
        canViewUnitCost,
    };
}
