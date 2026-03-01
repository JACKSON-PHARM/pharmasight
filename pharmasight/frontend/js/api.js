// API Client for PharmaSight

class APIClient {
    constructor(baseURL) {
        this.baseURL = baseURL;
    }

    async request(endpoint, options = {}) {
        const url = `${this.baseURL}${endpoint}`;
        
        // Add timeout using AbortController (default 60 seconds for startup)
        const timeoutMs = options.timeout || 60000;
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
        
        // Check if body is FormData (for file uploads)
        const isFormData = options.body instanceof FormData;
        
        const config = {
            headers: isFormData ? {} : {
                'Content-Type': 'application/json',
                ...options.headers,
            },
            signal: controller.signal,
            ...options,
        };
        
        // Only JSON.stringify if it's not FormData
        if (config.body && typeof config.body === 'object' && !isFormData) {
            config.body = JSON.stringify(config.body);
        }
        
        // Merge any additional headers (but don't override FormData handling)
        if (options.headers && !isFormData) {
            config.headers = { ...config.headers, ...options.headers };
        }

        // Tenant context (database-per-tenant): send X-Tenant-Subdomain for app APIs when set.
        // Skip for /api/admin/* (master-only). No header → legacy DB.
        try {
            // Prefer per-tab tenant (sessionStorage) to avoid cross-tab collisions; fall back to localStorage.
            var sub = null;
            try {
                if (typeof sessionStorage !== 'undefined') sub = sessionStorage.getItem('pharmasight_tenant_subdomain');
            } catch (_) {}
            if (!sub && typeof localStorage !== 'undefined') sub = localStorage.getItem('pharmasight_tenant_subdomain');
            if (sub && endpoint.indexOf('/api/admin/') !== 0) {
                config.headers['X-Tenant-Subdomain'] = sub;
            }
        } catch (_) {}

        // Internal auth: send Bearer token when we have one.
        // Admin routes (except login): use admin_token. Other app routes: use pharmasight_access_token. Skip for auth endpoints.
        const isAuthEndpoint = endpoint.indexOf('/api/auth/username-login') !== -1 ||
            endpoint.indexOf('/api/auth/refresh') !== -1 ||
            endpoint.indexOf('/api/auth/request-reset') !== -1 ||
            endpoint.indexOf('/api/auth/reset-password') !== -1;
        const isAdminRoute = endpoint.indexOf('/api/admin/') === 0;
        const isAdminLogin = endpoint.indexOf('/api/admin/auth/login') !== -1;
        try {
            if (typeof localStorage !== 'undefined') {
                if (isAdminRoute && !isAdminLogin) {
                    const adminToken = localStorage.getItem('admin_token');
                    if (adminToken) {
                        config.headers['Authorization'] = 'Bearer ' + adminToken;
                    }
                } else if (!isAuthEndpoint) {
                    const accessToken = localStorage.getItem('pharmasight_access_token');
                    if (accessToken) {
                        config.headers['Authorization'] = 'Bearer ' + accessToken;
                    }
                }
            }
        } catch (_) {}

        try {
            const response = await fetch(url, config);
            clearTimeout(timeoutId);

            const text = await response.text();
            let data;
            try {
                data = text ? JSON.parse(text) : {};
            } catch (parseError) {
                throw new Error(`Server error (${response.status}): ${text.substring(0, 200)}`);
            }

            if (!response.ok) {
                let errorMsg = data.message || `HTTP error! status: ${response.status}`;
                if (data.detail != null) {
                    errorMsg = Array.isArray(data.detail)
                        ? data.detail.map((d) => (d && typeof d.msg === 'string' ? d.msg : JSON.stringify(d))).join('; ')
                        : (typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail));
                } else if (!data.message) {
                    errorMsg = JSON.stringify(data) || errorMsg;
                }
                const error = new Error(errorMsg);
                error.status = response.status;
                error.data = data;
                console.error('API Error Response:', { url, status: response.status, data });
                if (response.status === 401) {
                    var alreadyRetried = options._retried401 === true;
                    var isInternalAuth = false;
                    try {
                        if (typeof localStorage !== 'undefined' && !isAuthEndpoint && !isAdminRoute) {
                            var at = localStorage.getItem('pharmasight_access_token');
                            var rt = localStorage.getItem('pharmasight_refresh_token');
                            isInternalAuth = !!(at && rt);
                        }
                    } catch (_) {}
                    if (isInternalAuth && !alreadyRetried) {
                        try {
                            var refreshResp = await fetch(this.baseURL + '/api/auth/refresh', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ refresh_token: localStorage.getItem('pharmasight_refresh_token') }),
                            });
                            var refreshData = refreshResp.ok ? (await refreshResp.json().catch(function() { return null; })) : null;
                            if (refreshResp.ok && refreshData && refreshData.access_token) {
                                localStorage.setItem('pharmasight_access_token', refreshData.access_token);
                                if (refreshData.refresh_token) localStorage.setItem('pharmasight_refresh_token', refreshData.refresh_token);
                                var retryOpts = { ...options, _retried401: true };
                                return await this.request(endpoint, retryOpts);
                            }
                        } catch (refreshErr) {
                            console.warn('Token refresh failed:', refreshErr);
                        }
                    }
                    if (typeof window.showToast === 'function') {
                        window.showToast('Session expired. Please log in again.', 'warning');
                    }
                    if (typeof window.globalLogout === 'function') {
                        window.globalLogout();
                    }
                }
                throw error;
            }

            return data;
        } catch (error) {
            clearTimeout(timeoutId);
            
            // If it's already our formatted error, re-throw it
            if (error.status || error.data) {
                throw error;
            }
            
            // Preserve AbortError so callers can detect cancelled requests (e.g. item search)
            if (error.name === 'AbortError') {
                // If we created the controller (no external signal), treat as timeout
                if (!options.signal) {
                    throw new Error(`Request timed out after ${timeoutMs/1000} seconds. The server may be starting (e.g. on Render). Try again in a moment.`);
                }
                throw error;
            }
            
            // Handle network errors, CORS errors, etc.
            console.error('API Request Failed:', { url, error: error.message });
            throw new Error(`Network error: ${error.message}. Please check if the backend server is running on ${this.baseURL}`);
        }
    }

    get(endpoint, params = {}, requestOptions = {}) {
        const queryString = new URLSearchParams(params).toString();
        const url = queryString
            ? (endpoint.includes('?') ? `${endpoint}&${queryString}` : `${endpoint}?${queryString}`)
            : endpoint;
        return this.request(url, { method: 'GET', ...requestOptions });
    }

    post(endpoint, data, options = {}) {
        return this.request(endpoint, {
            method: 'POST',
            body: data,
            ...options,
        });
    }

    put(endpoint, data) {
        return this.request(endpoint, {
            method: 'PUT',
            body: data,
        });
    }

    patch(endpoint, data) {
        return this.request(endpoint, {
            method: 'PATCH',
            body: data,
        });
    }

    delete(endpoint) {
        return this.request(endpoint, { method: 'DELETE' });
    }
}

// Create API client instance
const api = new APIClient(CONFIG.API_BASE_URL);

// API Methods
const API = {
    // Startup (Complete initialization)
    startup: {
        initialize: (data) => api.post('/api/startup', data),
        status: () => api.get('/api/startup/status'),
    },
    // Invite & Setup
    invite: {
        inviteAdmin: (data) => api.post('/api/invite/admin', data),
        // Tenant setup status (company exists?) for the authenticated user (backend route is /api/setup/status)
        getSetupStatus: (userId) => api.get('/api/setup/status', { user_id: userId }),
        markSetupComplete: (userId) => api.post(`/api/invite/mark-setup-complete?user_id=${userId}`, null),
    },
    tenantInviteSetup: {
        validateToken: (token) => api.get(`/api/onboarding/validate-token/${encodeURIComponent(token)}`),
        complete: (data) => api.post('/api/onboarding/complete-tenant-invite', data),
    },
    // Company & Branch
    company: {
        list: () => api.get('/api/companies'),
        get: (companyId) => api.get(`/api/companies/${companyId}`),
        getLogoUrl: (companyId) => api.get(`/api/companies/${companyId}/logo-url`),
        create: (data) => api.post('/api/companies', data),
        update: (companyId, data) => api.put(`/api/companies/${companyId}`, data),
        getSettings: (companyId, key = null) =>
            api.get(`/api/companies/${companyId}/settings`, key ? { key } : {}),
        updateSetting: (companyId, data) => api.put(`/api/companies/${companyId}/settings`, data),
        uploadLogo: (companyId, file) => {
            const formData = new FormData();
            formData.append('file', file);
            return api.post(`/api/companies/${companyId}/logo`, formData, {
                headers: {} // Let browser set Content-Type with boundary
            });
        },
        uploadStamp: (companyId, file) => {
            const formData = new FormData();
            formData.append('file', file);
            return api.post(`/api/companies/${companyId}/stamp`, formData, { headers: {} });
        },
    },
    branch: {
        list: (companyId) => api.get(`/api/branches/company/${companyId}`),
        get: (branchId) => api.get(`/api/branches/${branchId}`),
        create: (data) => api.post('/api/branches', data),
        update: (branchId, data) => api.put(`/api/branches/${branchId}`, data),
        setAsHq: (branchId) => api.post(`/api/branches/${branchId}/set-hq`, null),
        getSettings: (branchId) => api.get(`/api/branches/${branchId}/settings`),
        updateSettings: (branchId, data) => api.patch(`/api/branches/${branchId}/settings`, data),
    },

    // Items
    items: {
        search: (q, companyId, limit = 10, branchId = null, includePricing = false, context = null, requestOptions = {}, fast = false) => {
            const params = { q, company_id: companyId, limit, include_pricing: includePricing };
            if (branchId) params.branch_id = branchId;
            if (context) params.context = context;
            if (fast) params.fast = true;
            return api.get(`${CONFIG.API_ENDPOINTS.items}/search`, params, requestOptions);
        },
        stockBatch: (itemIds, branchId, companyId, requestOptions = {}) => {
            return api.post(`${CONFIG.API_ENDPOINTS.items}/stock-batch`, { item_ids: itemIds, branch_id: branchId, company_id: companyId }, requestOptions);
        },
        list: (companyId, options = {}) => {
            const params = new URLSearchParams();
            if (options.limit) params.append('limit', options.limit);
            if (options.offset) params.append('offset', options.offset);
            if (options.include_units !== undefined) params.append('include_units', options.include_units);
            const query = params.toString();
            return api.get(`${CONFIG.API_ENDPOINTS.items}/company/${companyId}${query ? '?' + query : ''}`);
        },
        overview: (companyId, branchId = null) => {
            const params = new URLSearchParams();
            if (branchId) params.append('branch_id', branchId);
            const query = params.toString();
            return api.get(`${CONFIG.API_ENDPOINTS.items}/company/${companyId}/overview${query ? '?' + query : ''}`);
        },
        count: (companyId) => api.get(`${CONFIG.API_ENDPOINTS.items}/company/${companyId}/count`),
        get: (itemId, branchId = null) => {
            const params = branchId ? { branch_id: branchId } : {};
            return api.get(`${CONFIG.API_ENDPOINTS.items}/${itemId}`, params);
        },
        getActivity: (itemId, branchId) => {
            if (!branchId) return Promise.reject(new Error('branch_id required for item activity'));
            return api.get(`${CONFIG.API_ENDPOINTS.items}/${itemId}/activity`, { branch_id: branchId });
        },
        create: (data) => api.post(`${CONFIG.API_ENDPOINTS.items}/`, data),
        bulkCreate: (data) => api.post(`${CONFIG.API_ENDPOINTS.items}/bulk`, data, { timeout: 300000 }), // 5 minute timeout for bulk
        update: (itemId, data) => api.put(`${CONFIG.API_ENDPOINTS.items}/${itemId}`, data),
        delete: (itemId) => api.delete(`${CONFIG.API_ENDPOINTS.items}/${itemId}`),
        hasTransactions: (itemId, branchId) => api.get(`${CONFIG.API_ENDPOINTS.items}/${itemId}/has-transactions`, { branch_id: branchId }),
        adjustStock: (itemId, data) => api.post(`${CONFIG.API_ENDPOINTS.items}/${itemId}/adjust-stock`, data),
        getLedgerBatches: (itemId, branchId) =>
            api.get(`${CONFIG.API_ENDPOINTS.items}/${itemId}/ledger-batches`, { branch_id: branchId }),
        corrections: {
            costAdjustment: (itemId, data) => api.post(`${CONFIG.API_ENDPOINTS.items}/${itemId}/corrections/cost-adjustment`, data),
            batchQuantityCorrection: (itemId, data) => api.post(`${CONFIG.API_ENDPOINTS.items}/${itemId}/corrections/batch-quantity-correction`, data),
            batchMetadataCorrection: (itemId, data) => api.post(`${CONFIG.API_ENDPOINTS.items}/${itemId}/corrections/batch-metadata-correction`, data),
        },
        getRecommendedPrice: (itemId, branchId, companyId, unitName, tier) => 
            api.get(`${CONFIG.API_ENDPOINTS.items}/${itemId}/recommended-price`, {
                branch_id: branchId,
                company_id: companyId,
                unit_name: unitName,
                ...(tier ? { tier } : {}),
            }),
    },

    // Inventory
    inventory: {
        getStock: (itemId, branchId) => 
            api.get(`${CONFIG.API_ENDPOINTS.inventory}/stock/${itemId}/${branchId}`),
        getAvailability: (itemId, branchId) => 
            api.get(`${CONFIG.API_ENDPOINTS.inventory}/availability/${itemId}/${branchId}`),
        getBatches: (itemId, branchId) => 
            api.get(`${CONFIG.API_ENDPOINTS.inventory}/batches/${itemId}/${branchId}`),
        checkAvailability: (itemId, branchId, quantity, unitName) => 
            api.get(`${CONFIG.API_ENDPOINTS.inventory}/check-availability`, {
                item_id: itemId,
                branch_id: branchId,
                quantity: quantity,
                unit_name: unitName,
            }),
        getAllStock: (branchId) =>
            api.get(`${CONFIG.API_ENDPOINTS.inventory}/branch/${branchId}/all`, { timeout: 120000 }),
        getValuation: (params) => {
            const q = new URLSearchParams();
            if (params.branch_id) q.set('branch_id', params.branch_id);
            if (params.as_of_date) q.set('as_of_date', params.as_of_date);
            if (params.valuation) q.set('valuation', params.valuation);
            if (params.stock_only !== undefined) q.set('stock_only', params.stock_only ? 'true' : 'false');
            return api.get(`${CONFIG.API_ENDPOINTS.inventory}/valuation?${q.toString()}`, {}, { timeout: 120000 });
        },
        getItemsInStockCount: (branchId) =>
            api.get(`${CONFIG.API_ENDPOINTS.inventory}/branch/${branchId}/items-in-stock-count`),
        getStockOverview: (branchId) =>
            api.get(`${CONFIG.API_ENDPOINTS.inventory}/branch/${branchId}/overview`),
        getExpiringCount: (branchId, days = 365) =>
            api.get(`${CONFIG.API_ENDPOINTS.inventory}/branch/${branchId}/expiring-count?days=${days}`),
        getExpiringList: (branchId, days = 365) =>
            api.get(`${CONFIG.API_ENDPOINTS.inventory}/branch/${branchId}/expiring?days=${days}`),
        getTotalStockValue: (branchId) =>
            api.get(`${CONFIG.API_ENDPOINTS.inventory}/branch/${branchId}/total-value`),
        allocateFEFO: (itemId, branchId, quantity, unitName) => 
            api.post(`${CONFIG.API_ENDPOINTS.inventory}/allocate-fefo`, {
                item_id: itemId,
                branch_id: branchId,
                quantity: quantity,
                unit_name: unitName,
            }),
    },

    // Branch Inventory (branch orders, transfers, receipts)
    branchInventory: {
        base: () => (CONFIG.API_ENDPOINTS.branchInventory || '/api/branch-inventory'),
        getOrders: (params = {}) => {
            const q = new URLSearchParams();
            if (params.ordering_branch_id) q.set('ordering_branch_id', params.ordering_branch_id);
            if (params.supplying_branch_id) q.set('supplying_branch_id', params.supplying_branch_id);
            if (params.status) q.set('status', params.status);
            return api.get(`${CONFIG.API_ENDPOINTS.branchInventory || '/api/branch-inventory'}/orders?${q.toString()}`);
        },
        getOrder: (orderId) => api.get(`${CONFIG.API_ENDPOINTS.branchInventory || '/api/branch-inventory'}/orders/${orderId}`),
        createOrder: (data) => api.post(`${CONFIG.API_ENDPOINTS.branchInventory || '/api/branch-inventory'}/orders`, data),
        updateOrder: (orderId, data) => api.patch(`${CONFIG.API_ENDPOINTS.branchInventory || '/api/branch-inventory'}/orders/${orderId}`, data),
        batchOrder: (orderId) => api.post(`${CONFIG.API_ENDPOINTS.branchInventory || '/api/branch-inventory'}/orders/${orderId}/batch`),
        getPendingOrdersForSupply: (supplyingBranchId) =>
            api.get(`${CONFIG.API_ENDPOINTS.branchInventory || '/api/branch-inventory'}/orders/pending-supply?supplying_branch_id=${supplyingBranchId}`),
        getTransfers: (params = {}) => {
            const q = new URLSearchParams();
            if (params.supplying_branch_id) q.set('supplying_branch_id', params.supplying_branch_id);
            if (params.receiving_branch_id) q.set('receiving_branch_id', params.receiving_branch_id);
            if (params.status) q.set('status', params.status);
            return api.get(`${CONFIG.API_ENDPOINTS.branchInventory || '/api/branch-inventory'}/transfers?${q.toString()}`);
        },
        getTransfer: (transferId) => api.get(`${CONFIG.API_ENDPOINTS.branchInventory || '/api/branch-inventory'}/transfers/${transferId}`),
        createTransfer: (data) => api.post(`${CONFIG.API_ENDPOINTS.branchInventory || '/api/branch-inventory'}/transfers`, data),
        completeTransfer: (transferId) => api.post(`${CONFIG.API_ENDPOINTS.branchInventory || '/api/branch-inventory'}/transfers/${transferId}/complete`),
        getReceipts: (params = {}) => {
            const q = new URLSearchParams();
            if (params.receiving_branch_id) q.set('receiving_branch_id', params.receiving_branch_id);
            if (params.status) q.set('status', params.status);
            return api.get(`${CONFIG.API_ENDPOINTS.branchInventory || '/api/branch-inventory'}/receipts?${q.toString()}`);
        },
        getPendingReceipts: (receivingBranchId) =>
            api.get(`${CONFIG.API_ENDPOINTS.branchInventory || '/api/branch-inventory'}/receipts/pending?receiving_branch_id=${receivingBranchId}`),
        getReceipt: (receiptId) => api.get(`${CONFIG.API_ENDPOINTS.branchInventory || '/api/branch-inventory'}/receipts/${receiptId}`),
        receiveReceipt: (receiptId) => api.post(`${CONFIG.API_ENDPOINTS.branchInventory || '/api/branch-inventory'}/receipts/${receiptId}/receive`),
    },

    // Sales
    sales: {
        createInvoice: (data) => api.post(`${CONFIG.API_ENDPOINTS.sales}/invoice`, data),
        getInvoice: (invoiceId) => api.get(`${CONFIG.API_ENDPOINTS.sales}/invoice/${invoiceId}`),
        getBranchInvoices: (branchId) => 
            api.get(`${CONFIG.API_ENDPOINTS.sales}/branch/${branchId}/invoices`),
        getTodaySummary: (branchId, userId) =>
            api.get(`${CONFIG.API_ENDPOINTS.sales}/branch/${branchId}/today-summary`, userId != null ? { user_id: userId } : {}),
        getGrossProfit: (branchId, params = {}) =>
            api.get(`${CONFIG.API_ENDPOINTS.sales}/branch/${branchId}/gross-profit`, params),
        updateInvoice: (invoiceId, data) => 
            api.put(`${CONFIG.API_ENDPOINTS.sales}/invoice/${invoiceId}`, data),
        addInvoiceItem: (invoiceId, item) =>
            api.post(`${CONFIG.API_ENDPOINTS.sales}/invoice/${invoiceId}/items`, item),
        updateInvoiceItem: (invoiceId, itemId, payload) =>
            api.patch(`${CONFIG.API_ENDPOINTS.sales}/invoice/${invoiceId}/items/${itemId}`, payload),
        deleteInvoiceItem: (invoiceId, itemId) =>
            api.delete(`${CONFIG.API_ENDPOINTS.sales}/invoice/${invoiceId}/items/${itemId}`),
        deleteInvoice: (invoiceId) => 
            api.delete(`${CONFIG.API_ENDPOINTS.sales}/invoice/${invoiceId}`),
        batchInvoice: (invoiceId, batchedBy, body = null) =>
            api.post(`${CONFIG.API_ENDPOINTS.sales}/invoice/${invoiceId}/batch?batched_by=${batchedBy}`, body),
        // Split payments
        addPayment: (invoiceId, payment) => 
            api.post(`${CONFIG.API_ENDPOINTS.sales}/invoice/${invoiceId}/payments`, payment),
        getPayments: (invoiceId) => 
            api.get(`${CONFIG.API_ENDPOINTS.sales}/invoice/${invoiceId}/payments`),
        deletePayment: (paymentId) => 
            api.delete(`${CONFIG.API_ENDPOINTS.sales}/invoice/payments/${paymentId}`),
        convertToQuotation: (invoiceId) => 
            api.post(`${CONFIG.API_ENDPOINTS.sales}/invoice/${invoiceId}/convert-to-quotation`, null),
        /** Download sales invoice as PDF. Opens a window first (user gesture) then assigns blob so download isn't blocked. */
        downloadPdf: async (invoiceId, invoiceNo = null) => {
            const base = (typeof CONFIG !== 'undefined' && CONFIG.API_ENDPOINTS && CONFIG.API_ENDPOINTS.sales) ? CONFIG.API_ENDPOINTS.sales : '/api/sales';
            const url = `${api.baseURL}${base}/invoice/${invoiceId}/pdf`;
            const headers = {};
            try {
                const sub = typeof sessionStorage !== 'undefined' && sessionStorage.getItem('pharmasight_tenant_subdomain') || (typeof localStorage !== 'undefined' && localStorage.getItem('pharmasight_tenant_subdomain'));
                if (sub) headers['X-Tenant-Subdomain'] = sub;
                const token = typeof localStorage !== 'undefined' && localStorage.getItem('pharmasight_access_token');
                if (token) headers['Authorization'] = 'Bearer ' + token;
            } catch (_) {}
            const w = window.open('', '_blank');
            const res = await fetch(url, { method: 'GET', headers });
            if (!res.ok) {
                if (w) w.close();
                let msg = 'Failed to download PDF';
                try {
                    const text = await res.text();
                    let data;
                    try { data = text ? JSON.parse(text) : {}; } catch (_) { data = {}; }
                    const d = data.detail || data.message;
                    if (d) msg += ': ' + (typeof d === 'string' ? d : JSON.stringify(d));
                } catch (_) {}
                throw new Error(msg);
            }
            const blob = await res.blob();
            const blobUrl = URL.createObjectURL(blob);
            if (w && !w.closed) {
                w.location.href = blobUrl;
                setTimeout(() => URL.revokeObjectURL(blobUrl), 60000);
            } else {
                const a = document.createElement('a');
                a.href = blobUrl;
                a.download = `sales-invoice-${(invoiceNo != null && invoiceNo !== '') ? String(invoiceNo).replace(/\s+/g, '-') : invoiceId}.pdf`;
                a.click();
                URL.revokeObjectURL(blobUrl);
            }
        },
    },

    // Reports (branch from session via X-Branch-ID)
    reports: {
        getItemMovement: (itemId, startDate, endDate) => {
            const params = { item_id: itemId, start_date: startDate, end_date: endDate };
            const headers = {};
            if (typeof CONFIG !== 'undefined' && CONFIG.BRANCH_ID) {
                headers['X-Branch-ID'] = CONFIG.BRANCH_ID;
            }
            return api.get('/api/reports/item-movement', params, { headers });
        },
        getBatchMovement: (itemId, batchNo, startDate, endDate, branchId) => {
            const params = { item_id: itemId, batch_no: batchNo, start_date: startDate, end_date: endDate };
            if (branchId) params.branch_id = branchId;
            const headers = {};
            if (typeof CONFIG !== 'undefined' && CONFIG.BRANCH_ID) {
                headers['X-Branch-ID'] = CONFIG.BRANCH_ID;
            }
            return api.get('/api/reports/batch-movement', params, { headers });
        },
        getBatchesForItem: (itemId, branchId) => {
            const params = { branch_id: branchId };
            const headers = {};
            if (typeof CONFIG !== 'undefined' && CONFIG.BRANCH_ID) {
                headers['X-Branch-ID'] = CONFIG.BRANCH_ID;
            }
            return api.get(`/api/items/${itemId}/batches`, params, { headers });
        },
    },

    // Quotations (sales documents that do not affect stock)
    quotations: {
        create: (data) => api.post('/api/quotations', data),
        get: (quotationId) => api.get(`/api/quotations/${quotationId}`),
        listByBranch: (branchId) => api.get(`/api/quotations/branch/${branchId}`),
        addItem: (quotationId, item) => api.post(`/api/quotations/${quotationId}/items`, item),
        deleteItem: (quotationId, itemId) => api.delete(`/api/quotations/${quotationId}/items/${itemId}`),
        update: (quotationId, data) => api.put(`/api/quotations/${quotationId}`, data),
        delete: (quotationId) => api.delete(`/api/quotations/${quotationId}`),
        /** Download quotation as PDF. Opens a window first (user gesture) then assigns blob so download isn't blocked. */
        downloadPdf: async (quotationId, quotationNo = null) => {
            const url = `${api.baseURL}/api/quotations/${quotationId}/pdf`;
            const headers = {};
            try {
                const sub = typeof sessionStorage !== 'undefined' && sessionStorage.getItem('pharmasight_tenant_subdomain') || (typeof localStorage !== 'undefined' && localStorage.getItem('pharmasight_tenant_subdomain'));
                if (sub) headers['X-Tenant-Subdomain'] = sub;
                const token = typeof localStorage !== 'undefined' && localStorage.getItem('pharmasight_access_token');
                if (token) headers['Authorization'] = 'Bearer ' + token;
            } catch (_) {}
            const w = window.open('', '_blank');
            const res = await fetch(url, { method: 'GET', headers });
            if (!res.ok) {
                if (w) w.close();
                let msg = 'Failed to download PDF';
                try {
                    const text = await res.text();
                    let data;
                    try { data = text ? JSON.parse(text) : {}; } catch (_) { data = {}; }
                    const d = data.detail || data.message;
                    if (d) msg += ': ' + (typeof d === 'string' ? d : JSON.stringify(d));
                } catch (_) {}
                throw new Error(msg);
            }
            const blob = await res.blob();
            const blobUrl = URL.createObjectURL(blob);
            if (w && !w.closed) {
                w.location.href = blobUrl;
                setTimeout(() => URL.revokeObjectURL(blobUrl), 60000);
            } else {
                const a = document.createElement('a');
                a.href = blobUrl;
                a.download = `quotation-${(quotationNo || quotationId).toString().replace(/\s+/g, '-')}.pdf`;
                a.click();
                URL.revokeObjectURL(blobUrl);
            }
        },
        convertToInvoice: (quotationId, data = {}) => 
            api.post(`/api/quotations/${quotationId}/convert-to-invoice`, data),
    },

    // Purchases
    purchases: {
        createGRN: (data) => api.post(`${CONFIG.API_ENDPOINTS.purchases}/grn`, data),
        getGRN: (grnId) => api.get(`${CONFIG.API_ENDPOINTS.purchases}/grn/${grnId}`),
        /** Download GRN as PDF. Opens a window first (user gesture) then assigns blob so download isn't blocked. */
        downloadGrnPdf: async (grnId, grnNo = null) => {
            const base = (typeof CONFIG !== 'undefined' && CONFIG.API_ENDPOINTS && CONFIG.API_ENDPOINTS.purchases) ? CONFIG.API_ENDPOINTS.purchases : '/api/purchases';
            const url = `${api.baseURL}${base}/grn/${grnId}/pdf`;
            const headers = {};
            try {
                const sub = typeof sessionStorage !== 'undefined' && sessionStorage.getItem('pharmasight_tenant_subdomain') || (typeof localStorage !== 'undefined' && localStorage.getItem('pharmasight_tenant_subdomain'));
                if (sub) headers['X-Tenant-Subdomain'] = sub;
                const token = typeof localStorage !== 'undefined' && localStorage.getItem('pharmasight_access_token');
                if (token) headers['Authorization'] = 'Bearer ' + token;
            } catch (_) {}
            const w = window.open('', '_blank');
            const res = await fetch(url, { method: 'GET', headers });
            if (!res.ok) {
                if (w) w.close();
                let msg = 'Failed to download PDF';
                try {
                    const text = await res.text();
                    let data;
                    try { data = text ? JSON.parse(text) : {}; } catch (_) { data = {}; }
                    const d = data.detail || data.message;
                    if (d) msg += ': ' + (typeof d === 'string' ? d : JSON.stringify(d));
                } catch (_) {}
                throw new Error(msg);
            }
            const blob = await res.blob();
            const blobUrl = URL.createObjectURL(blob);
            const name = (grnNo != null && grnNo !== '') ? String(grnNo).replace(/\s+/g, '-') : grnId;
            if (w && !w.closed) {
                w.location.href = blobUrl;
                setTimeout(() => URL.revokeObjectURL(blobUrl), 60000);
            } else {
                const a = document.createElement('a');
                a.href = blobUrl;
                a.download = `grn-${name}.pdf`;
                a.click();
                URL.revokeObjectURL(blobUrl);
            }
        },
        createInvoice: (data) => api.post(`${CONFIG.API_ENDPOINTS.purchases}/invoice`, data),
        getInvoice: (invoiceId) => 
            api.get(`${CONFIG.API_ENDPOINTS.purchases}/invoice/${invoiceId}`),
        addInvoiceItem: (invoiceId, item) =>
            api.post(`${CONFIG.API_ENDPOINTS.purchases}/invoice/${invoiceId}/items`, item),
        updateInvoiceItem: (invoiceId, itemId, payload) =>
            api.patch(`${CONFIG.API_ENDPOINTS.purchases}/invoice/${invoiceId}/items/${itemId}`, payload),
        deleteInvoiceItem: (invoiceId, itemId) =>
            api.delete(`${CONFIG.API_ENDPOINTS.purchases}/invoice/${invoiceId}/items/${itemId}`),
        updateInvoice: (invoiceId, data) => 
            api.put(`${CONFIG.API_ENDPOINTS.purchases}/invoice/${invoiceId}`, data),
        deleteInvoice: (invoiceId) => 
            api.delete(`${CONFIG.API_ENDPOINTS.purchases}/invoice/${invoiceId}`),
        batchInvoice: (invoiceId) => 
            api.post(`${CONFIG.API_ENDPOINTS.purchases}/invoice/${invoiceId}/batch`, null),
        updateInvoicePayment: (invoiceId, amountPaid) => 
            api.put(`${CONFIG.API_ENDPOINTS.purchases}/invoice/${invoiceId}/payment?amount_paid=${amountPaid}`, null),
        /** Download supplier invoice as PDF. Opens a window first (user gesture) then assigns blob so download isn't blocked. */
        downloadSupplierInvoicePdf: async (invoiceId, invoiceNumber = null) => {
            const base = (typeof CONFIG !== 'undefined' && CONFIG.API_ENDPOINTS && CONFIG.API_ENDPOINTS.purchases) ? CONFIG.API_ENDPOINTS.purchases : '/api/purchases';
            const url = `${api.baseURL}${base}/invoice/${invoiceId}/pdf`;
            const headers = {};
            try {
                const sub = typeof sessionStorage !== 'undefined' && sessionStorage.getItem('pharmasight_tenant_subdomain') || (typeof localStorage !== 'undefined' && localStorage.getItem('pharmasight_tenant_subdomain'));
                if (sub) headers['X-Tenant-Subdomain'] = sub;
                const token = typeof localStorage !== 'undefined' && localStorage.getItem('pharmasight_access_token');
                if (token) headers['Authorization'] = 'Bearer ' + token;
            } catch (_) {}
            const w = window.open('', '_blank');
            const res = await fetch(url, { method: 'GET', headers });
            if (!res.ok) {
                if (w) w.close();
                let msg = 'Failed to download PDF';
                try {
                    const text = await res.text();
                    let data;
                    try { data = text ? JSON.parse(text) : {}; } catch (_) { data = {}; }
                    const d = data.detail || data.message;
                    if (d) msg += ': ' + (typeof d === 'string' ? d : JSON.stringify(d));
                } catch (_) {}
                throw new Error(msg);
            }
            const blob = await res.blob();
            const blobUrl = URL.createObjectURL(blob);
            const name = (invoiceNumber != null && invoiceNumber !== '') ? String(invoiceNumber).replace(/\s+/g, '-') : invoiceId;
            if (w && !w.closed) {
                w.location.href = blobUrl;
                setTimeout(() => URL.revokeObjectURL(blobUrl), 60000);
            } else {
                const a = document.createElement('a');
                a.href = blobUrl;
                a.download = `supplier-invoice-${name}.pdf`;
                a.click();
                URL.revokeObjectURL(blobUrl);
            }
        },
        // Purchase Orders
        createOrder: (data) => api.post(`${CONFIG.API_ENDPOINTS.purchases}/order`, data),
        listOrders: (params) => {
            const queryString = new URLSearchParams();
            Object.keys(params).forEach(key => {
                if (params[key] !== null && params[key] !== undefined) {
                    queryString.append(key, params[key]);
                }
            });
            return api.get(`${CONFIG.API_ENDPOINTS.purchases}/order?${queryString.toString()}`);
        },
        getOrder: (orderId) => api.get(`${CONFIG.API_ENDPOINTS.purchases}/order/${orderId}`),
        addOrderItem: (orderId, item) => api.post(`${CONFIG.API_ENDPOINTS.purchases}/order/${orderId}/items`, item),
        deleteOrderItem: (orderId, itemId) => api.delete(`${CONFIG.API_ENDPOINTS.purchases}/order/${orderId}/items/${itemId}`),
        updateOrder: (orderId, data) => api.put(`${CONFIG.API_ENDPOINTS.purchases}/order/${orderId}`, data),
        deleteOrder: (orderId) => api.delete(`${CONFIG.API_ENDPOINTS.purchases}/order/${orderId}`),
        approveOrder: (orderId) => api.patch(`${CONFIG.API_ENDPOINTS.purchases}/order/${orderId}/approve`, null),
        getOrderPdfUrl: (orderId) => api.get(`${CONFIG.API_ENDPOINTS.purchases}/order/${orderId}/pdf-url`),
        listInvoices: (params) => {
            const queryString = new URLSearchParams();
            Object.keys(params).forEach(key => {
                if (params[key] !== null && params[key] !== undefined) {
                    queryString.append(key, params[key]);
                }
            });
            return api.get(`${CONFIG.API_ENDPOINTS.purchases}/invoice?${queryString.toString()}`);
        },
    },
    
    // Suppliers
    suppliers: {
        search: (q, companyId, limit = 10) => 
            api.get(`${CONFIG.API_ENDPOINTS.suppliers}/search`, { q, company_id: companyId, limit }),
        list: (companyId) => api.get(`${CONFIG.API_ENDPOINTS.suppliers}/company/${companyId}`),
        get: (supplierId) => api.get(`${CONFIG.API_ENDPOINTS.suppliers}/${supplierId}`),
        create: (data) => api.post(`${CONFIG.API_ENDPOINTS.suppliers}/`, data),
        update: (supplierId, data) => api.put(`${CONFIG.API_ENDPOINTS.suppliers}/${supplierId}`, data),
    },
    
    // Excel Import (supports Vyper-style column mapping)
    excel: {
        getExpectedFields: () => api.get('/api/excel/expected-fields'),
        import: (file, companyId, branchId, userId, forceMode = null, columnMapping = null, sync = true) => {
            const formData = new FormData();
            formData.append('file', file);
            formData.append('company_id', companyId);
            formData.append('branch_id', branchId);
            formData.append('user_id', userId);
            if (forceMode) {
                formData.append('force_mode', forceMode);
            }
            if (columnMapping && typeof columnMapping === 'object' && Object.keys(columnMapping).length > 0) {
                formData.append('column_mapping', JSON.stringify(columnMapping));
            }
            if (sync) {
                formData.append('sync', '1');
            }
            // sync=1: long timeout (import runs in request; 90 min for large sheets). sync=0: short timeout (job starts, poll progress).
            const timeoutMs = sync ? 90 * 60 * 1000 : 30000; // 90 min sync, 30 s async
            return api.request('/api/excel/import', {
                method: 'POST',
                body: formData,
                headers: {},
                timeout: timeoutMs
            });
        },
        getProgress: (jobId) => api.get(`/api/excel/import/${jobId}/progress`),
        getMode: (companyId) => api.get(`/api/excel/mode/${companyId}`),
        /** Clear company data for fresh Excel import. Only allowed when no live transactions. */
        clearForReimport: (companyId) => api.post('/api/excel/clear-for-reimport', { company_id: companyId }),
    },
    
    // User Management
    users: {
        list: (includeDeleted = false) => api.get('/api/users', { include_deleted: includeDeleted }),
        /**
         * Get user profile
         * Optional params are passed as query string (e.g. cache busters like {_t: Date.now()})
         */
        get: (userId, params = {}) => api.get(`/api/users/${userId}`, params),
        create: (data) => api.post('/api/users', data),
        update: (userId, data) => api.put(`/api/users/${userId}`, data),
        uploadSignature: (userId, file) => {
            const formData = new FormData();
            formData.append('file', file);
            return api.post(`/api/users/${userId}/signature`, formData, { headers: {} });
        },
        activate: (userId, isActive) => api.post(`/api/users/${userId}/activate`, { is_active: isActive }),
        delete: (userId) => api.delete(`/api/users/${userId}`),
        restore: (userId) => api.post(`/api/users/${userId}/restore`, null),
        sendInvitation: (userId) => api.post(`/api/users/${userId}/send-invitation`, null),
        assignRole: (userId, roleData) => api.post(`/api/users/${userId}/roles`, roleData),
        listRoles: () => api.get('/api/users/roles'),
        updateRole: (roleId, data) => api.patch(`/api/users/roles/${roleId}`, data),
        getRolePermissions: (roleId) => api.get(`/api/users/roles/${roleId}/permissions`),
        updateRolePermissions: (roleId, permissions) => api.put(`/api/users/roles/${roleId}/permissions`, { permissions }),
        getUserPermissions: (userId, branchId = null) => {
            const params = branchId ? { branch_id: branchId } : {};
            return api.get(`/api/users/${userId}/permissions`, params);
        },
    },
    // Permissions (Vyapar-style matrix)
    permissions: {
        list: () => api.get('/api/permissions'),
        hqOnly: () => api.get('/api/permissions/hq-only'),
    },
    
    // Stock Take (Multi-User)
    stockTake: {
        // Sessions
        createSession: (data, createdBy) => api.post(`/api/stock-take/sessions?created_by=${createdBy}`, data),
        listSessions: (branchId = null, statusFilter = null) => {
            const params = {};
            if (branchId) params.branch_id = branchId;
            if (statusFilter) params.status_filter = statusFilter;
            return api.get('/api/stock-take/sessions', params);
        },
        getSession: (sessionId) => api.get(`/api/stock-take/sessions/${sessionId}`),
        getSessionByCode: (sessionCode) => api.get(`/api/stock-take/sessions/code/${sessionCode}`),
        updateSession: (sessionId, data, userId) => api.put(`/api/stock-take/sessions/${sessionId}?user_id=${userId}`, data),
        startSession: (sessionId, userId) => api.post(`/api/stock-take/sessions/${sessionId}/start?user_id=${userId}`, null),
        
        // Counts
        createCount: (data, countedBy) => api.post(`/api/stock-take/counts?counted_by=${countedBy}`, data),
        listCounts: (sessionId, counterId = null) => {
            const params = {};
            if (counterId) params.counter_id = counterId;
            return api.get(`/api/stock-take/sessions/${sessionId}/counts`, params);
        },
        
        // Locks
        lockItem: (data, counterId) => api.post(`/api/stock-take/locks?counter_id=${counterId}`, data),
        unlockItem: (itemId, counterId) => api.delete(`/api/stock-take/locks?item_id=${itemId}&counter_id=${counterId}`),
        listLocks: (sessionId) => api.get(`/api/stock-take/sessions/${sessionId}/locks`),
        
        // Progress (legacy - session-based)
        getSessionProgress: (sessionId) => api.get(`/api/stock-take/sessions/${sessionId}/progress`),
        
        // Branch Stock Take (Automatic Participation)
        getBranchStatus: (branchId) => {
            // Add cache busting timestamp to force fresh check
            const timestamp = new Date().getTime();
            return api.get(`/api/stock-take/branch/${branchId}/status?t=${timestamp}`);
        },
        isBranchInStockTake: (branchId) => api.get(`/api/stock-take/branch/${branchId}/status`).then(r => r.inStockTake || false).catch(() => false),
        hasDraftDocuments: (branchId) => {
            // Add cache busting timestamp to force fresh check
            const timestamp = new Date().getTime();
            return api.get(`/api/stock-take/branch/${branchId}/has-drafts?t=${timestamp}`);
        },
        startForBranch: (branchId, userId) => {
            const queryParams = userId ? `?user_id=${userId}` : '';
            return api.post(`/api/stock-take/branch/${branchId}/start${queryParams}`, null);
        },
        saveCount: (data, userId) => {
            // Add user_id to query params
            const queryParams = userId ? `?counted_by=${userId}` : '';
            return api.post(`/api/stock-take/counts${queryParams}`, data);
        },
        getMyCounts: (branchId, userId) => api.get(`/api/stock-take/branch/${branchId}/my-counts`, { user_id: userId }),
        getProgress: (branchId) => api.get(`/api/stock-take/branch/${branchId}/progress`),
        completeForBranch: (branchId, userId) => {
            const queryParams = userId ? `?user_id=${userId}` : '';
            return api.post(`/api/stock-take/branch/${branchId}/complete${queryParams}`, null);
        },
        getVarianceReport: (branchId, sessionId) => api.get(`/api/stock-take/branch/${branchId}/variance-report`, { session_id: sessionId }),
        cancelForBranch: (branchId, userId) => {
            const queryParams = userId ? `?user_id=${userId}` : '';
            return api.post(`/api/stock-take/branch/${branchId}/cancel${queryParams}`, null);
        },
        getCount: (countId) => api.get(`/api/stock-take/counts/${countId}`),
        updateCount: (countId, data, userId) => {
            const queryParams = userId ? `?user_id=${userId}` : '';
            return api.put(`/api/stock-take/counts/${countId}${queryParams}`, data);
        },
        deleteCount: (countId, userId) => {
            const queryParams = userId ? `?user_id=${userId}` : '';
            return api.delete(`/api/stock-take/counts/${countId}${queryParams}`);
        },
        getShelves: (branchId) => api.get(`/api/stock-take/branch/${branchId}/shelves`),
        getShelfCounts: (branchId, shelfName) => api.get(`/api/stock-take/branch/${branchId}/shelves/${encodeURIComponent(shelfName)}/counts`),
        approveShelf: (branchId, shelfName, userId) => {
            const queryParams = userId ? `?user_id=${userId}` : '';
            return api.post(`/api/stock-take/branch/${branchId}/shelves/${encodeURIComponent(shelfName)}/approve${queryParams}`, null);
        },
        rejectShelf: (branchId, shelfName, userId, reason) => {
            const queryParams = userId ? `?user_id=${userId}` : '';
            return api.post(`/api/stock-take/branch/${branchId}/shelves/${encodeURIComponent(shelfName)}/reject${queryParams}`, { reason });
        },
        /** Download A4 PDF recording template (Item Name, Wholesale/Retail Units, Expiry, Batch; placeholders: Shelf, Counted By, Verified By, Keyed In By). */
        downloadTemplatePdf: async () => {
            const url = `${api.baseURL}/api/stock-take/template/pdf`;
            const headers = {};
            try {
                const sub = typeof localStorage !== 'undefined' && localStorage.getItem('pharmasight_tenant_subdomain');
                if (sub) headers['X-Tenant-Subdomain'] = sub;
            } catch (_) {}
            const res = await fetch(url, { method: 'GET', headers, credentials: 'include' });
            if (!res.ok) {
                let msg = 'Failed to download template';
                try {
                    const text = await res.text();
                    let data;
                    try { data = text ? JSON.parse(text) : {}; } catch (_) { data = {}; }
                    const detail = data.detail;
                    if (detail) msg += ': ' + (typeof detail === 'string' ? detail : (detail.msg || JSON.stringify(detail)));
                } catch (_) {}
                const err = new Error(msg);
                err.status = res.status;
                throw err;
            }
            const blob = await res.blob();
            const a = document.createElement('a');
            a.href = URL.createObjectURL(blob);
            a.download = 'stock-take-recording-sheet.pdf';
            a.click();
            URL.revokeObjectURL(a.href);
        },
        /** URL for printable HTML template (fallback when PDF is unavailable). */
        getTemplateHtmlUrl: () => `${api.baseURL}/api/stock-take/template/html`,
    },
    
    // Order Book
    orderBook: {
        // List entries (optional: statusFilter, dateFrom, dateTo, includeOrdered, supplierId)
        list: (branchId, companyId, statusFilter = null, options = {}) => {
            const params = { branch_id: branchId, company_id: companyId };
            if (statusFilter) params.status_filter = statusFilter;
            if (options.dateFrom) params.date_from = options.dateFrom;
            if (options.dateTo) params.date_to = options.dateTo;
            if (options.includeOrdered === true) params.include_ordered = 'true';
            if (options.supplierId) params.supplier_id = options.supplierId;
            return api.get('/api/order-book', params);
        },
        
        // Create entry
        create: (data, companyId, branchId, createdBy) => {
            const queryParams = new URLSearchParams({
                company_id: companyId,
                branch_id: branchId,
                created_by: createdBy
            });
            return api.post(`/api/order-book?${queryParams}`, data);
        },
        
        // Bulk create
        bulkCreate: (data, companyId, branchId, createdBy) => {
            const queryParams = new URLSearchParams({
                company_id: companyId,
                branch_id: branchId,
                created_by: createdBy
            });
            return api.post(`/api/order-book/bulk?${queryParams}`, data);
        },
        
        // Update entry
        update: (entryId, data) => api.put(`/api/order-book/${entryId}`, data),
        
        // Delete entry
        delete: (entryId) => api.delete(`/api/order-book/${entryId}`),
        
        // Auto-generate
        autoGenerate: (branchId, companyId) => api.post('/api/order-book/auto-generate', { branch_id: branchId, company_id: companyId }),
        
        // Create purchase order from selected entries
        createPurchaseOrder: (data, companyId, branchId, createdBy) => {
            const queryParams = new URLSearchParams({
                company_id: companyId,
                branch_id: branchId,
                created_by: createdBy
            });
            return api.post(`/api/order-book/create-purchase-order?${queryParams}`, data);
        },

        // Dashboard: pending order book count for today (optional: include preview entries via limit)
        getTodaySummary: (branchId, companyId, limit = 10) => {
            const params = { branch_id: branchId, company_id: companyId, limit };
            return api.get('/api/order-book/today-summary', params);
        },
        
        // Get history
        getHistory: (branchId, companyId, limit = 100) => {
            const params = { branch_id: branchId, company_id: companyId, limit };
            return api.get('/api/order-book/history', params);
        },
    },
    // Authentication
    auth: {
        usernameLogin: (data) => api.post('/api/auth/username-login', data),
    },
    // Admin Authentication
    adminAuth: {
        login: (data) => api.post('/api/admin/auth/login', data),
        verify: (token) => api.get('/api/admin/auth/verify', { token }),
    },
    // Admin - Tenant Management
    admin: {
        tenants: {
            list: (params = {}) => api.get('/api/admin/tenants', params),
            get: (tenantId) => api.get(`/api/admin/tenants/${tenantId}`),
            create: (data) => api.post('/api/admin/tenants', data),
            update: (tenantId, data) => api.patch(`/api/admin/tenants/${tenantId}`, data),
            delete: (tenantId) => api.delete(`/api/admin/tenants/${tenantId}`),
            initializeStatus: (tenantId) => api.get(`/api/admin/tenants/${tenantId}/initialize-status`),
            initialize: (tenantId, data) => api.post(`/api/admin/tenants/${tenantId}/initialize`, data),
            invites: {
                create: (tenantId, data) => api.post(`/api/admin/tenants/${tenantId}/invites`, { expires_in_days: 7, send_email: true, ...data }, { timeout: 120000 }),
                list: (tenantId) => api.get(`/api/admin/tenants/${tenantId}/invites`),
            },
            subscription: (tenantId) => api.get(`/api/admin/tenants/${tenantId}/subscription`),
            modules: (tenantId) => api.get(`/api/admin/tenants/${tenantId}/modules`),
        },
        plans: {
            list: () => api.get('/api/admin/plans'),
        },
        migrations: {
            run: (data) => api.post('/api/admin/migrations/run', data),
            status: () => api.get('/api/admin/migrations/status'),
        },
    },
};

// Expose API to window for global access
if (typeof window !== 'undefined') {
    window.API = API;
}
