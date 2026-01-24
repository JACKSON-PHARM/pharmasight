/**
 * Optimistic Locking Service
 * 
 * Handles version-based optimistic locking for editable documents.
 * Prevents concurrent edit conflicts by tracking document versions.
 */

/**
 * Get version from document (if it exists)
 */
function getDocumentVersion(document) {
    if (!document) return null;
    return document.version || document.updated_at || document.created_at || null;
}

/**
 * Prepare document for save with version check
 * Returns data object with version field for optimistic locking
 * Ensures version is sent to API for database-level enforcement
 */
function prepareDocumentForSave(document, versionField = 'version') {
    if (!document) {
        throw new Error('Document is required');
    }
    
    const version = getDocumentVersion(document);
    
    // Always include version field for database-level optimistic locking
    // Database/API will check version and reject if outdated
    const saveData = {
        ...document,
        [versionField]: version
    };
    
    // Ensure version is explicitly set (even if null for new documents)
    if (!(versionField in saveData)) {
        saveData[versionField] = version;
    }
    
    return saveData;
}

/**
 * Check if save was successful or had a version conflict
 */
function handleSaveResponse(response, originalVersion, versionField = 'version') {
    const newVersion = response[versionField] || response.version || response.updated_at;
    
    if (!newVersion) {
        // Version wasn't returned, assume success (older API)
        return { success: true, conflict: false, newVersion: null };
    }
    
    if (originalVersion && newVersion !== originalVersion) {
        // Version changed - save was successful
        return { success: true, conflict: false, newVersion };
    }
    
    if (originalVersion === newVersion && originalVersion !== null) {
        // Version unchanged - might indicate conflict, but could also mean no changes
        return { success: true, conflict: false, newVersion };
    }
    
    return { success: true, conflict: false, newVersion };
}

/**
 * Handle version conflict error
 */
function handleVersionConflict(error, documentName = 'document') {
    const message = error.message || error.detail || 'Version conflict';
    
    if (message.toLowerCase().includes('version') || 
        message.toLowerCase().includes('conflict') ||
        message.toLowerCase().includes('concurrent')) {
        
        showToast(
            `${documentName} was modified by another user. Please refresh and try again.`,
            'error'
        );
        return true; // Conflict detected
    }
    
    return false; // Not a version conflict
}

/**
 * Save document with optimistic locking
 * 
 * @param {Function} saveFunction - API function to call for saving
 * @param {Object} document - Document data to save
 * @param {Object} options - Options
 * @param {string} options.versionField - Field name for version (default: 'version')
 * @param {string} options.documentName - Name for error messages
 * @returns {Promise} Save result
 */
async function saveWithLocking(saveFunction, document, options = {}) {
    const {
        versionField = 'version',
        documentName = 'Document'
    } = options;
    
    if (!document) {
        throw new Error('Document is required');
    }
    
    const originalVersion = getDocumentVersion(document);
    
    try {
        // Prepare document with version
        const saveData = prepareDocumentForSave(document, versionField);
        
        // Attempt save
        const response = await saveFunction(saveData);
        
        // Check for conflicts
        const result = handleSaveResponse(response, originalVersion, versionField);
        
        if (result.conflict) {
            throw new Error('Version conflict detected');
        }
        
        return {
            success: true,
            data: response,
            newVersion: result.newVersion
        };
        
    } catch (error) {
        // Check if it's a version conflict
        const isConflict = handleVersionConflict(error, documentName);
        
        if (isConflict) {
            return {
                success: false,
                conflict: true,
                error: error
            };
        }
        
        // Re-throw non-conflict errors
        throw error;
    }
}

/**
 * Wrapper for API update calls with optimistic locking
 */
async function updateDocumentWithLocking(documentId, document, updateFunction, options = {}) {
    return saveWithLocking(
        (data) => updateFunction(documentId, data),
        document,
        options
    );
}

// Export OptimisticLocking service
const OptimisticLocking = {
    getVersion: getDocumentVersion,
    prepareForSave: prepareDocumentForSave,
    handleResponse: handleSaveResponse,
    handleConflict: handleVersionConflict,
    save: saveWithLocking,
    update: updateDocumentWithLocking
};

// Expose to window
if (typeof window !== 'undefined') {
    window.OptimisticLocking = OptimisticLocking;
}
