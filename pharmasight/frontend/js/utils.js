// Utility Functions

/**
 * Run an async action with button disabled and single-flight guard.
 * Prevents double submission and re-enables button on success or error.
 * @param {string|HTMLElement} buttonOrId - Button element or its id
 * @param {string} inFlightKey - Optional key for dedup (e.g. 'batch-' + id). If same key runs again while in flight, skip.
 * @param {() => Promise<any>} fn - Async function to run
 * @returns {Promise<any>}
 */
async function safeSubmit(buttonOrId, inFlightKey, fn) {
    if (typeof inFlightKey === 'function') {
        fn = inFlightKey;
        inFlightKey = null;
    }
    const btn = typeof buttonOrId === 'string' ? document.getElementById(buttonOrId) : buttonOrId;
    const key = inFlightKey || 'safeSubmit';
    if (window.__safeSubmitInFlight && window.__safeSubmitInFlight[key]) {
        return;
    }
    if (window.__safeSubmitInFlight === undefined) window.__safeSubmitInFlight = {};
    window.__safeSubmitInFlight[key] = true;
    if (btn) {
        btn.disabled = true;
        btn.setAttribute('data-original-html', btn.innerHTML);
        btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Please wait...';
    }
    try {
        const result = await fn();
        return result;
    } finally {
        delete window.__safeSubmitInFlight[key];
        if (btn) {
            btn.disabled = false;
            const orig = btn.getAttribute('data-original-html');
            if (orig) btn.innerHTML = orig;
        }
    }
}

// Show toast notification
function showToast(message, type = 'info') {
    // Error noise reduction: suppress error toasts during navigation transition
    if (window.__suppressToasts === true && type === 'error') {
        return;
    }
    const container = document.getElementById('toastContainer');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    
    const icon = {
        success: 'fa-check-circle',
        error: 'fa-exclamation-circle',
        warning: 'fa-exclamation-triangle',
        info: 'fa-info-circle',
    }[type] || 'fa-info-circle';

    toast.innerHTML = `
        <i class="fas ${icon}"></i>
        <span>${message}</span>
    `;

    container.appendChild(toast);

    // Remove after 3 seconds
    setTimeout(() => {
        toast.style.animation = 'slideOut 0.3s ease';
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

// Show notification (alias for showToast, or use a simple alert/console for admin panel)
function showNotification(message, type = 'info') {
    if (window.__suppressToasts === true && type === 'error') {
        return;
    }
    // Try to use showToast if toast container exists
    const container = document.getElementById('toastContainer');
    if (container) {
        showToast(message, type);
        return;
    }
    
    // Fallback: create a simple notification
    console.log(`[${type.toUpperCase()}] ${message}`);
    
    // Create a simple notification element if no toast container
    const notification = document.createElement('div');
    notification.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        padding: 12px 20px;
        background: ${type === 'error' ? '#dc3545' : type === 'success' ? '#28a745' : '#007bff'};
        color: white;
        border-radius: 4px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.2);
        z-index: 10000;
        font-size: 14px;
        max-width: 300px;
    `;
    notification.textContent = message;
    document.body.appendChild(notification);
    
    setTimeout(() => {
        notification.style.opacity = '0';
        notification.style.transition = 'opacity 0.3s';
        setTimeout(() => notification.remove(), 300);
    }, 3000);
}

// Format currency
function formatCurrency(amount) {
    return new Intl.NumberFormat('en-KE', {
        style: 'currency',
        currency: 'KES',
        minimumFractionDigits: 2,
    }).format(amount);
}

// Format date
function formatDate(date) {
    if (!date) return '';
    const d = new Date(date);
    return d.toLocaleDateString('en-KE', {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
    });
}

// Format datetime
function formatDateTime(date) {
    if (!date) return '';
    const d = new Date(date);
    return d.toLocaleString('en-KE', {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
    });
}

// Show modal (no-op if modal elements not present, e.g. on admin.html)
function showModal(title, content, footer = '', modalClass = '') {
    const overlay = document.getElementById('modalOverlay');
    const modal = document.getElementById('modal');
    if (!overlay || !modal) return;

    // Add class if provided
    if (modalClass) {
        modal.classList.add(modalClass);
    } else {
        modal.classList.remove('modal-large');
    }

    modal.innerHTML = `
        <div class="modal-header">
            <h3 class="modal-title">${title}</h3>
            <button class="modal-close" onclick="closeModal()">
                <i class="fas fa-times"></i>
            </button>
        </div>
        <div class="modal-body">
            ${content}
        </div>
        ${footer ? `<div class="modal-footer">${footer}</div>` : ''}
    `;

    overlay.style.display = 'flex';
}

// Close modal (no-op if overlay not present)
function closeModal() {
    const overlay = document.getElementById('modalOverlay');
    if (overlay) overlay.style.display = 'none';
}

// Close modal on overlay click (only when overlay exists, e.g. on main app pages)
document.addEventListener('DOMContentLoaded', () => {
    const overlay = document.getElementById('modalOverlay');
    if (overlay) {
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) {
                closeModal();
            }
        });
    }
});

// Debounce function
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

// Format stock display (e.g., "8 boxes + 40 tablets")
function formatStockDisplay(availability) {
    if (!availability || !availability.unit_breakdown || availability.unit_breakdown.length === 0) {
        return `${availability?.total_base_units || 0} ${availability?.base_unit || ''}`;
    }
    
    const display = availability.unit_breakdown[0].display;
    return display || `${availability.total_base_units} ${availability.base_unit}`;
}

// Calculate VAT
function calculateVAT(amount, rate = CONFIG.VAT_RATE) {
    return (amount * rate) / 100;
}

// Calculate total with VAT
function calculateTotalWithVAT(amount, rate = CONFIG.VAT_RATE) {
    return amount + calculateVAT(amount, rate);
}

// Validate required fields
function validateRequired(formData, requiredFields) {
    const errors = [];
    requiredFields.forEach(field => {
        if (!formData[field] || formData[field] === '') {
            errors.push(`${field} is required`);
        }
    });
    return errors;
}

// Loading state
function setLoading(element, isLoading) {
    if (isLoading) {
        element.innerHTML = '<div class="spinner"></div>';
        element.style.pointerEvents = 'none';
    } else {
        element.style.pointerEvents = 'auto';
    }
}

// Make functions available globally (for script tag usage)
// Note: This file is loaded as a regular script tag, not a module
// So we don't use export statements here
if (typeof window !== 'undefined') {
    window.showNotification = showNotification;
    window.showToast = showToast;
    window.formatCurrency = formatCurrency;
    window.formatDate = formatDate;
    window.formatDateTime = formatDateTime;
    window.debounce = debounce;
}
