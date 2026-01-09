// API Client for PharmaSight

class APIClient {
    constructor(baseURL) {
        this.baseURL = baseURL;
    }

    async request(endpoint, options = {}) {
        const url = `${this.baseURL}${endpoint}`;
        const config = {
            headers: {
                'Content-Type': 'application/json',
                ...options.headers,
            },
            ...options,
        };

        if (config.body && typeof config.body === 'object') {
            config.body = JSON.stringify(config.body);
        }

        try {
            const response = await fetch(url, config);
            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.detail || `HTTP error! status: ${response.status}`);
            }

            return data;
        } catch (error) {
            console.error('API Error:', error);
            throw error;
        }
    }

    get(endpoint, params = {}) {
        const queryString = new URLSearchParams(params).toString();
        const url = queryString ? `${endpoint}?${queryString}` : endpoint;
        return this.request(url, { method: 'GET' });
    }

    post(endpoint, data) {
        return this.request(endpoint, {
            method: 'POST',
            body: data,
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
    // Items
    items: {
        list: (companyId) => api.get(`${CONFIG.API_ENDPOINTS.items}/company/${companyId}`),
        get: (itemId) => api.get(`${CONFIG.API_ENDPOINTS.items}/${itemId}`),
        create: (data) => api.post(`${CONFIG.API_ENDPOINTS.items}/`, data),
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
    },
};

