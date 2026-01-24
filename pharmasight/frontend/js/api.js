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

        try {
            const response = await fetch(url, config);
            clearTimeout(timeoutId);
            
            // Try to parse JSON, but handle non-JSON responses
            let data;
            try {
                data = await response.json();
            } catch (parseError) {
                const text = await response.text();
                throw new Error(`Server error (${response.status}): ${text.substring(0, 200)}`);
            }

            if (!response.ok) {
                const errorMsg = data.detail || data.message || JSON.stringify(data) || `HTTP error! status: ${response.status}`;
                const error = new Error(errorMsg);
                error.status = response.status;
                error.data = data;
                console.error('API Error Response:', { url, status: response.status, data });
                throw error;
            }

            return data;
        } catch (error) {
            clearTimeout(timeoutId);
            
            // If it's already our formatted error, re-throw it
            if (error.status || error.data) {
                throw error;
            }
            
            // Handle abort (timeout)
            if (error.name === 'AbortError') {
                throw new Error(`Request timed out after ${timeoutMs/1000} seconds. Is the backend server running on ${this.baseURL}?`);
            }
            
            // Handle network errors, CORS errors, etc.
            console.error('API Request Failed:', { url, error: error.message });
            throw new Error(`Network error: ${error.message}. Please check if the backend server is running on ${this.baseURL}`);
        }
    }

    get(endpoint, params = {}) {
        const queryString = new URLSearchParams(params).toString();
        const url = queryString ? `${endpoint}?${queryString}` : endpoint;
        return this.request(url, { method: 'GET' });
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
        getSetupStatus: (userId) => api.get('/api/setup/status', { user_id: userId }),
        markSetupComplete: (userId) => api.post(`/api/invite/mark-setup-complete?user_id=${userId}`, null),
    },
    // Company & Branch
    company: {
        list: () => api.get('/api/companies'),
        get: (companyId) => api.get(`/api/companies/${companyId}`),
        create: (data) => api.post('/api/companies', data),
        update: (companyId, data) => api.put(`/api/companies/${companyId}`, data),
    },
    branch: {
        list: (companyId) => api.get(`/api/branches/company/${companyId}`),
        get: (branchId) => api.get(`/api/branches/${branchId}`),
        create: (data) => api.post('/api/branches', data),
        update: (branchId, data) => api.put(`/api/branches/${branchId}`, data),
    },

    // Items
    items: {
        search: (q, companyId, limit = 10, branchId = null) => {
            const params = { q, company_id: companyId, limit };
            if (branchId) params.branch_id = branchId;
            return api.get(`${CONFIG.API_ENDPOINTS.items}/search`, params);
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
        get: (itemId) => api.get(`${CONFIG.API_ENDPOINTS.items}/${itemId}`),
        create: (data) => api.post(`${CONFIG.API_ENDPOINTS.items}/`, data),
        bulkCreate: (data) => api.post(`${CONFIG.API_ENDPOINTS.items}/bulk`, data, { timeout: 300000 }), // 5 minute timeout for bulk
        update: (itemId, data) => api.put(`${CONFIG.API_ENDPOINTS.items}/${itemId}`, data),
        delete: (itemId) => api.delete(`${CONFIG.API_ENDPOINTS.items}/${itemId}`),
        getRecommendedPrice: (itemId, branchId, companyId, unitName) => 
            api.get(`${CONFIG.API_ENDPOINTS.items}/${itemId}/recommended-price`, {
                branch_id: branchId,
                company_id: companyId,
                unit_name: unitName,
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
            api.get(`${CONFIG.API_ENDPOINTS.inventory}/branch/${branchId}/all`),
        getStockOverview: (branchId) =>
            api.get(`${CONFIG.API_ENDPOINTS.inventory}/branch/${branchId}/overview`),
        allocateFEFO: (itemId, branchId, quantity, unitName) => 
            api.post(`${CONFIG.API_ENDPOINTS.inventory}/allocate-fefo`, {
                item_id: itemId,
                branch_id: branchId,
                quantity: quantity,
                unit_name: unitName,
            }),
    },

    // Sales
    sales: {
        createInvoice: (data) => api.post(`${CONFIG.API_ENDPOINTS.sales}/invoice`, data),
        getInvoice: (invoiceId) => api.get(`${CONFIG.API_ENDPOINTS.sales}/invoice/${invoiceId}`),
        getBranchInvoices: (branchId) => 
            api.get(`${CONFIG.API_ENDPOINTS.sales}/branch/${branchId}/invoices`),
    },

    // Purchases
    purchases: {
        createGRN: (data) => api.post(`${CONFIG.API_ENDPOINTS.purchases}/grn`, data),
        getGRN: (grnId) => api.get(`${CONFIG.API_ENDPOINTS.purchases}/grn/${grnId}`),
        createInvoice: (data) => api.post(`${CONFIG.API_ENDPOINTS.purchases}/invoice`, data),
        getInvoice: (invoiceId) => 
            api.get(`${CONFIG.API_ENDPOINTS.purchases}/invoice/${invoiceId}`),
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
        updateOrder: (orderId, data) => api.put(`${CONFIG.API_ENDPOINTS.purchases}/order/${orderId}`, data),
        deleteOrder: (orderId) => api.delete(`${CONFIG.API_ENDPOINTS.purchases}/order/${orderId}`),
        listInvoices: (companyId, branchId) => {
            const params = { company_id: companyId };
            if (branchId) params.branch_id = branchId;
            const queryString = new URLSearchParams(params);
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
    
    // Excel Import
    excel: {
        import: (file, companyId, branchId, userId, forceMode = null) => {
            const formData = new FormData();
            formData.append('file', file);
            formData.append('company_id', companyId);
            formData.append('branch_id', branchId);
            formData.append('user_id', userId);
            if (forceMode) {
                formData.append('force_mode', forceMode);
            }
            // For FormData, don't set Content-Type - browser will set it with boundary
            return api.request('/api/excel/import', {
                method: 'POST',
                body: formData,
                headers: {} // Let browser set Content-Type for FormData
            });
        },
        getMode: (companyId) => api.get(`/api/excel/mode/${companyId}`),
    },
    
    // User Management
    users: {
        list: (includeDeleted = false) => api.get('/api/users', { include_deleted: includeDeleted }),
        get: (userId) => api.get(`/api/users/${userId}`),
        create: (data) => api.post('/api/users', data),
        update: (userId, data) => api.put(`/api/users/${userId}`, data),
        activate: (userId, isActive) => api.post(`/api/users/${userId}/activate`, { is_active: isActive }),
        delete: (userId) => api.delete(`/api/users/${userId}`),
        restore: (userId) => api.post(`/api/users/${userId}/restore`, null),
        sendInvitation: (userId) => api.post(`/api/users/${userId}/send-invitation`, null),
        assignRole: (userId, roleData) => api.post(`/api/users/${userId}/roles`, roleData),
        listRoles: () => api.get('/api/users/roles'),
    },
};

// Expose API to window for global access
if (typeof window !== 'undefined') {
    window.API = API;
}
