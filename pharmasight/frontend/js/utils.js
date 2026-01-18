// Utility Functions

// Show toast notification
function showToast(message, type = 'info') {
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

// Show modal
function showModal(title, content, footer = '', modalClass = '') {
    const overlay = document.getElementById('modalOverlay');
    const modal = document.getElementById('modal');
    
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

// Close modal
function closeModal() {
    const overlay = document.getElementById('modalOverlay');
    overlay.style.display = 'none';
}

// Close modal on overlay click
document.addEventListener('DOMContentLoaded', () => {
    const overlay = document.getElementById('modalOverlay');
    overlay.addEventListener('click', (e) => {
        if (e.target === overlay) {
            closeModal();
        }
    });
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

