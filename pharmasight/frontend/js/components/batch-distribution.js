/**
 * Batch Distribution Modal Component
 * 
 * Allows users to distribute a single item quantity across multiple batches
 * with batch numbers, expiry dates, and individual costs.
 */

(function() {
    'use strict';
    
    let currentBatchData = {
        itemIndex: null,
        itemId: null,
        itemName: '',
        totalQuantity: 0,
        unitName: '',
        unitCost: 0,
        baseUnit: '',
        requiresExpiry: false,
        batches: []
    };
    
    /**
     * Show batch distribution modal
     * @param {Object} options - Configuration options
     * @param {number} options.itemIndex - Index of item in transaction table
     * @param {string} options.itemId - Item ID
     * @param {string} options.itemName - Item name
     * @param {number} options.totalQuantity - Total quantity to distribute
     * @param {string} options.unitName - Unit name (box, carton, etc.)
     * @param {number} options.unitCost - Unit cost
     * @param {string} options.baseUnit - Base unit name
     * @param {boolean} options.requiresExpiry - Whether item requires expiry tracking
     * @param {Array} options.existingBatches - Existing batch distribution (for editing)
     */
    window.showBatchDistributionModal = function(options) {
        // Store current batch data
        currentBatchData = {
            itemIndex: options.itemIndex,
            itemId: options.itemId,
            itemName: options.itemName || 'Item',
            totalQuantity: parseFloat(options.totalQuantity) || 0,
            unitName: options.unitName || '',
            unitCost: parseFloat(options.unitCost) || 0,
            baseUnit: options.baseUnit || '',
            requiresExpiry: options.requiresExpiry || false,
            batches: options.existingBatches || []
        };
        
        // If no existing batches, create one default batch
        if (currentBatchData.batches.length === 0) {
            currentBatchData.batches.push({
                batch_number: '',
                expiry_date: '',
                quantity: currentBatchData.totalQuantity,
                unit_cost: currentBatchData.unitCost
            });
        }
        
        renderBatchModal();
    };
    
    /**
     * Render batch distribution modal
     */
    function renderBatchModal() {
        const modalContent = `
            <div class="batch-distribution-modal" style="max-width: 900px;">
                <div class="batch-header" style="margin-bottom: 1.5rem;">
                    <h3 style="margin: 0 0 0.5rem 0; display: flex; align-items: center; gap: 0.5rem;">
                        <i class="fas fa-boxes"></i> Batch Distribution
                    </h3>
                    <p style="margin: 0; color: var(--text-secondary);">
                        <strong>${escapeHtml(currentBatchData.itemName)}</strong> - 
                        Distribute ${currentBatchData.totalQuantity} ${currentBatchData.unitName}
                    </p>
                </div>
                
                <div class="batch-summary" style="display: flex; gap: 2rem; padding: 1rem; background: #f8f9fa; border-radius: 0.5rem; margin-bottom: 1.5rem;">
                    <div class="summary-item">
                        <span style="color: var(--text-secondary); font-size: 0.9rem;">Total to distribute:</span>
                        <strong style="display: block; font-size: 1.1rem; margin-top: 0.25rem;">
                            ${currentBatchData.totalQuantity} ${currentBatchData.unitName}
                        </strong>
                    </div>
                    <div class="summary-item">
                        <span style="color: var(--text-secondary); font-size: 0.9rem;">Distributed:</span>
                        <strong id="distributedTotal" style="display: block; font-size: 1.1rem; margin-top: 0.25rem; color: var(--primary-color);">
                            0 ${currentBatchData.unitName}
                        </strong>
                    </div>
                    <div class="summary-item">
                        <span style="color: var(--text-secondary); font-size: 0.9rem;">Balance:</span>
                        <strong id="balanceTotal" style="display: block; font-size: 1.1rem; margin-top: 0.25rem; color: var(--success-color);">
                            ${currentBatchData.totalQuantity} ${currentBatchData.unitName}
                        </strong>
                    </div>
                </div>
                
                <div class="batch-table-container" style="margin-bottom: 1.5rem;">
                    <table class="batch-table" style="width: 100%; border-collapse: collapse;">
                        <thead>
                            <tr style="background: #f8f9fa; border-bottom: 2px solid var(--border-color);">
                                <th style="padding: 0.75rem; text-align: left; font-weight: 600;">Batch Number *</th>
                                ${currentBatchData.requiresExpiry ? '<th style="padding: 0.75rem; text-align: left; font-weight: 600;">Expiry Date *</th>' : '<th style="padding: 0.75rem; text-align: left; font-weight: 600;">Expiry Date</th>'}
                                <th style="padding: 0.75rem; text-align: left; font-weight: 600;">Quantity *</th>
                                <th style="padding: 0.75rem; text-align: left; font-weight: 600;">Unit Cost *</th>
                                <th style="padding: 0.75rem; text-align: left; font-weight: 600;">Total Cost</th>
                                <th style="padding: 0.75rem; text-align: center; font-weight: 600; width: 80px;">Actions</th>
                            </tr>
                        </thead>
                        <tbody id="batchRows">
                            <!-- Batch rows will be rendered here -->
                        </tbody>
                    </table>
                    <button type="button" class="btn btn-outline" onclick="addBatchRow()" style="margin-top: 1rem;">
                        <i class="fas fa-plus"></i> Add Batch
                    </button>
                </div>
                
                <div class="batch-validation" style="margin-bottom: 1rem;">
                    <div id="batchErrors" class="alert alert-danger" style="display: none; margin-bottom: 1rem;"></div>
                    <div class="avg-cost-info" style="padding: 0.75rem; background: #e7f3ff; border-radius: 0.25rem; border-left: 3px solid var(--primary-color);">
                        <strong>Weighted Average Cost:</strong> 
                        <span id="weightedAvgCost" style="font-weight: 600; color: var(--primary-color);">0.00</span>
                        ${currentBatchData.unitCost > 0 ? `(Original: ${formatCurrency(currentBatchData.unitCost)})` : ''}
                    </div>
                </div>
            </div>
        `;
        
        const modalFooter = `
            <button class="btn btn-secondary" onclick="closeBatchModal()">
                <i class="fas fa-times"></i> Cancel
            </button>
            <button class="btn btn-primary" onclick="saveBatchDistribution()">
                <i class="fas fa-save"></i> Save Batch Distribution
            </button>
        `;
        
        // Use existing modal system (assuming showModal function exists)
        if (typeof showModal === 'function') {
            showModal('Batch Distribution', modalContent, modalFooter, 'modal-lg');
        } else {
            // Fallback: create modal manually
            createModalManually(modalContent, modalFooter);
        }
        
        // Render batch rows
        renderBatchRows();
        updateBatchSummary();
    }
    
    /**
     * Render batch rows
     */
    function renderBatchRows() {
        const tbody = document.getElementById('batchRows');
        if (!tbody) return;
        
        tbody.innerHTML = currentBatchData.batches.map((batch, index) => {
            return `
                <tr data-batch-index="${index}" style="border-bottom: 1px solid var(--border-color);">
                    <td style="padding: 0.75rem;">
                        <input type="text" 
                               class="form-input batch-batch-number" 
                               value="${escapeHtml(batch.batch_number || '')}"
                               placeholder="BATCH001"
                               required
                               onchange="updateBatchField(${index}, 'batch_number', this.value)"
                               style="width: 100%;">
                    </td>
                    <td style="padding: 0.75rem;">
                        <input type="date" 
                               class="form-input batch-expiry-date" 
                               value="${batch.expiry_date || ''}"
                               ${currentBatchData.requiresExpiry ? 'required' : ''}
                               onchange="updateBatchField(${index}, 'expiry_date', this.value)"
                               style="width: 100%;">
                    </td>
                    <td style="padding: 0.75rem;">
                        <input type="number" 
                               class="form-input batch-quantity" 
                               value="${batch.quantity || 0}"
                               min="0"
                               step="0.01"
                               required
                               onchange="updateBatchField(${index}, 'quantity', parseFloat(this.value) || 0)"
                               oninput="updateBatchField(${index}, 'quantity', parseFloat(this.value) || 0)"
                               style="width: 100%;">
                    </td>
                    <td style="padding: 0.75rem;">
                        <input type="number" 
                               class="form-input batch-unit-cost" 
                               value="${batch.unit_cost || 0}"
                               min="0"
                               step="0.01"
                               required
                               onchange="updateBatchField(${index}, 'unit_cost', parseFloat(this.value) || 0)"
                               oninput="updateBatchField(${index}, 'unit_cost', parseFloat(this.value) || 0)"
                               style="width: 100%;">
                    </td>
                    <td style="padding: 0.75rem;">
                        <span class="batch-total-cost" style="font-weight: 600;">
                            ${formatCurrency((batch.quantity || 0) * (batch.unit_cost || 0))}
                        </span>
                    </td>
                    <td style="padding: 0.75rem; text-align: center;">
                        ${currentBatchData.batches.length > 1 ? `
                            <button type="button" 
                                    class="btn btn-sm btn-danger" 
                                    onclick="removeBatchRow(${index})"
                                    title="Remove batch">
                                <i class="fas fa-trash"></i>
                            </button>
                        ` : ''}
                    </td>
                </tr>
            `;
        }).join('');
    }
    
    /**
     * Update batch field
     */
    window.updateBatchField = function(index, field, value) {
        if (!currentBatchData.batches[index]) return;
        
        currentBatchData.batches[index][field] = value;
        
        // Update total cost display
        const row = document.querySelector(`tr[data-batch-index="${index}"]`);
        if (row) {
            const batch = currentBatchData.batches[index];
            const totalCost = (batch.quantity || 0) * (batch.unit_cost || 0);
            const totalCostCell = row.querySelector('.batch-total-cost');
            if (totalCostCell) {
                totalCostCell.textContent = formatCurrency(totalCost);
            }
        }
        
        updateBatchSummary();
    };
    
    /**
     * Add batch row
     */
    window.addBatchRow = function() {
        const remaining = getRemainingQuantity();
        currentBatchData.batches.push({
            batch_number: '',
            expiry_date: '',
            quantity: remaining > 0 ? remaining : 0,
            unit_cost: currentBatchData.unitCost
        });
        renderBatchRows();
        updateBatchSummary();
    };
    
    /**
     * Remove batch row
     */
    window.removeBatchRow = function(index) {
        if (currentBatchData.batches.length <= 1) {
            showToast('At least one batch is required', 'error');
            return;
        }
        currentBatchData.batches.splice(index, 1);
        renderBatchRows();
        updateBatchSummary();
    };
    
    /**
     * Get remaining quantity to distribute
     */
    function getRemainingQuantity() {
        const distributed = currentBatchData.batches.reduce((sum, batch) => {
            return sum + (parseFloat(batch.quantity) || 0);
        }, 0);
        return currentBatchData.totalQuantity - distributed;
    }
    
    /**
     * Update batch summary
     */
    function updateBatchSummary() {
        const distributed = currentBatchData.batches.reduce((sum, batch) => {
            return sum + (parseFloat(batch.quantity) || 0);
        }, 0);
        
        const remaining = currentBatchData.totalQuantity - distributed;
        
        // Update distributed total
        const distributedEl = document.getElementById('distributedTotal');
        if (distributedEl) {
            distributedEl.textContent = `${distributed.toFixed(2)} ${currentBatchData.unitName}`;
        }
        
        // Update balance
        const balanceEl = document.getElementById('balanceTotal');
        if (balanceEl) {
            balanceEl.textContent = `${remaining.toFixed(2)} ${currentBatchData.unitName}`;
            balanceEl.style.color = remaining === 0 ? 'var(--success-color)' : 
                                   remaining < 0 ? 'var(--danger-color)' : 'var(--warning-color)';
        }
        
        // Calculate weighted average cost
        const totalCost = currentBatchData.batches.reduce((sum, batch) => {
            return sum + ((parseFloat(batch.quantity) || 0) * (parseFloat(batch.unit_cost) || 0));
        }, 0);
        
        const weightedAvg = distributed > 0 ? totalCost / distributed : 0;
        const avgCostEl = document.getElementById('weightedAvgCost');
        if (avgCostEl) {
            avgCostEl.textContent = formatCurrency(weightedAvg);
        }
        
        // Validate and show errors
        validateBatches();
    }
    
    /**
     * Validate batches
     */
    function validateBatches() {
        const errors = [];
        const distributed = currentBatchData.batches.reduce((sum, batch) => {
            return sum + (parseFloat(batch.quantity) || 0);
        }, 0);
        
        // Check quantity match
        if (Math.abs(distributed - currentBatchData.totalQuantity) > 0.01) {
            errors.push(`Total distributed quantity (${distributed.toFixed(2)}) must equal ${currentBatchData.totalQuantity}`);
        }
        
        // Check required fields
        currentBatchData.batches.forEach((batch, index) => {
            if (!batch.batch_number || batch.batch_number.trim() === '') {
                errors.push(`Batch ${index + 1}: Batch number is required`);
            }
            if (currentBatchData.requiresExpiry && !batch.expiry_date) {
                errors.push(`Batch ${index + 1}: Expiry date is required`);
            }
            if ((parseFloat(batch.quantity) || 0) <= 0) {
                errors.push(`Batch ${index + 1}: Quantity must be greater than 0`);
            }
            if ((parseFloat(batch.unit_cost) || 0) < 0) {
                errors.push(`Batch ${index + 1}: Unit cost cannot be negative`);
            }
        });
        
        // Check cost variance
        if (currentBatchData.unitCost > 0 && distributed > 0) {
            const totalCost = currentBatchData.batches.reduce((sum, batch) => {
                return sum + ((parseFloat(batch.quantity) || 0) * (parseFloat(batch.unit_cost) || 0));
            }, 0);
            const weightedAvg = totalCost / distributed;
            const variance = Math.abs(weightedAvg - currentBatchData.unitCost) / currentBatchData.unitCost;
            if (variance > 0.01) {  // 1% variance
                errors.push(`Weighted average cost (${formatCurrency(weightedAvg)}) differs significantly from original cost (${formatCurrency(currentBatchData.unitCost)})`);
            }
        }
        
        // Show/hide errors
        const errorEl = document.getElementById('batchErrors');
        if (errorEl) {
            if (errors.length > 0) {
                errorEl.innerHTML = '<strong>Validation Errors:</strong><ul style="margin: 0.5rem 0 0 1.5rem;"><li>' + 
                    errors.join('</li><li>') + '</li></ul>';
                errorEl.style.display = 'block';
            } else {
                errorEl.style.display = 'none';
            }
        }
        
        return errors.length === 0;
    }
    
    /**
     * Save batch distribution
     */
    window.saveBatchDistribution = function() {
        if (!validateBatches()) {
            showToast('Please fix validation errors before saving', 'error');
            return;
        }
        
        // Call callback to save batches
        if (window.onBatchDistributionSave) {
            window.onBatchDistributionSave(currentBatchData.itemIndex, currentBatchData.batches);
        }
        
        closeBatchModal();
        showToast('Batch distribution saved', 'success');
    };
    
    /**
     * Close batch modal
     */
    window.closeBatchModal = function() {
        if (typeof closeModal === 'function') {
            closeModal();
        } else {
            // Fallback: remove modal manually
            const modal = document.getElementById('batchDistributionModal');
            if (modal) {
                modal.remove();
            }
        }
    };
    
    /**
     * Create modal manually (fallback)
     */
    function createModalManually(content, footer) {
        // Remove existing modal if any
        const existing = document.getElementById('batchDistributionModal');
        if (existing) existing.remove();
        
        const modal = document.createElement('div');
        modal.id = 'batchDistributionModal';
        modal.className = 'modal-overlay';
        modal.style.cssText = 'position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.5); z-index: 10000; display: flex; align-items: center; justify-content: center;';
        
        modal.innerHTML = `
            <div class="modal-content" style="background: white; border-radius: 0.5rem; max-width: 900px; width: 90%; max-height: 90vh; overflow-y: auto; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">
                <div class="modal-header" style="padding: 1.5rem; border-bottom: 1px solid var(--border-color); display: flex; justify-content: space-between; align-items: center;">
                    <h3 style="margin: 0;">Batch Distribution</h3>
                    <button onclick="window.closeBatchModal()" style="background: none; border: none; font-size: 1.5rem; cursor: pointer;">&times;</button>
                </div>
                <div class="modal-body" style="padding: 1.5rem;">
                    ${content}
                </div>
                <div class="modal-footer" style="padding: 1.5rem; border-top: 1px solid var(--border-color); display: flex; justify-content: flex-end; gap: 0.5rem;">
                    ${footer}
                </div>
            </div>
        `;
        
        document.body.appendChild(modal);
        
        // Close on overlay click
        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                window.closeBatchModal();
            }
        });
    }
    
    /**
     * Helper: Escape HTML
     */
    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
    
    /**
     * Helper: Format currency
     */
    function formatCurrency(amount) {
        return new Intl.NumberFormat('en-KE', {
            style: 'currency',
            currency: 'KES',
            minimumFractionDigits: 2
        }).format(amount || 0);
    }
    
    // Expose formatCurrency globally if not exists
    if (typeof window.formatCurrency === 'undefined') {
        window.formatCurrency = formatCurrency;
    }
    
})();
