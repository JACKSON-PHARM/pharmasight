/**
 * Branch Context Service
 * 
 * Manages branch selection and persistence:
 * - Stores branch in localStorage + memory
 * - Supports multi-tab sync via BroadcastChannel
 * - Provides reactive branch state
 */

const BRANCH_STORAGE_KEY = 'pharmasight_selected_branch';
const BRANCH_CHANNEL_NAME = 'pharmasight_branch';

// Private state
let selectedBranch = null;
let branchListeners = new Set();
let branchChannel = null;

/**
 * Initialize BroadcastChannel for branch sync
 */
function initBranchChannel() {
    if (typeof BroadcastChannel === 'undefined') {
        return;
    }
    
    if (!branchChannel) {
        branchChannel = new BroadcastChannel(BRANCH_CHANNEL_NAME);
        
        branchChannel.onmessage = (event) => {
            if (event.data.type === 'BRANCH_CHANGED') {
                const { branch } = event.data;
                if (branch?.id !== selectedBranch?.id) {
                    setBranchInternal(branch, false); // Don't broadcast again
                }
            }
        };
    }
}

/**
 * Broadcast branch change to other tabs
 */
function broadcastBranchChange(branch) {
    if (branchChannel) {
        branchChannel.postMessage({
            type: 'BRANCH_CHANGED',
            branch: branch,
            timestamp: Date.now()
        });
    }
}

/**
 * Notify all branch listeners
 */
function notifyBranchListeners(branch) {
    branchListeners.forEach(callback => {
        try {
            callback(branch);
        } catch (error) {
            console.error('Error in branch listener:', error);
        }
    });
}

/**
 * Internal function to set branch (without broadcasting)
 */
function setBranchInternal(branch, shouldBroadcast = true) {
    selectedBranch = branch;
    
    // Persist to localStorage
    if (branch) {
        localStorage.setItem(BRANCH_STORAGE_KEY, JSON.stringify({
            id: branch.id,
            name: branch.name,
            company_id: branch.company_id,
            code: branch.code,
            is_hq: !!branch.is_hq
        }));
        if (typeof CONFIG !== 'undefined') CONFIG.IS_HQ = !!branch.is_hq;
    } else {
        localStorage.removeItem(BRANCH_STORAGE_KEY);
        if (typeof CONFIG !== 'undefined') CONFIG.IS_HQ = false;
    }
    
    // Update CONFIG for backward compatibility
    if (branch) {
        CONFIG.BRANCH_ID = branch.id;
        CONFIG.COMPANY_ID = branch.company_id;
        saveConfig();
    } else {
        CONFIG.BRANCH_ID = null;
        saveConfig();
    }
    
    // Clear search cache so Items/Inventory don't show stale stock from previous branch
    if (typeof window !== 'undefined' && window.searchCache && typeof window.searchCache.clear === 'function') {
        window.searchCache.clear();
    }
    
    // Broadcast to other tabs
    if (shouldBroadcast) {
        broadcastBranchChange(branch);
    }
    
    // Notify listeners
    notifyBranchListeners(branch);
}

/**
 * Set selected branch
 */
function setBranch(branch) {
    setBranchInternal(branch, true);
}

/**
 * Get selected branch (from memory)
 */
function getBranch() {
    return selectedBranch;
}

/**
 * Load branch from localStorage
 */
function loadBranchFromStorage() {
    try {
        const stored = localStorage.getItem(BRANCH_STORAGE_KEY);
        if (stored) {
            const branch = JSON.parse(stored);
            selectedBranch = branch;
            CONFIG.BRANCH_ID = branch.id;
            CONFIG.COMPANY_ID = branch.company_id;
            CONFIG.IS_HQ = !!branch.is_hq;
            return branch;
        }
    } catch (error) {
        console.error('Error loading branch from storage:', error);
    }
    return null;
}

/**
 * Clear selected branch
 */
function clearBranch() {
    setBranchInternal(null, true);
}

/**
 * Subscribe to branch changes
 * @param {Function} callback - Called with (branch) when branch changes
 * @returns {Function} Unsubscribe function
 */
function onBranchChange(callback) {
    branchListeners.add(callback);
    
    // Immediately call with current branch
    try {
        callback(selectedBranch);
    } catch (error) {
        console.error('Error in initial branch callback:', error);
    }
    
    // Return unsubscribe function
    return () => {
        branchListeners.delete(callback);
    };
}

/**
 * Initialize branch context
 */
function initBranchContext() {
    initBranchChannel();
    loadBranchFromStorage();
}

// Export BranchContext service
const BranchContext = {
    init: initBranchContext,
    setBranch,
    getBranch,
    clearBranch,
    onBranchChange,
    loadFromStorage: loadBranchFromStorage
};

// Expose to window
if (typeof window !== 'undefined') {
    window.BranchContext = BranchContext;
}
