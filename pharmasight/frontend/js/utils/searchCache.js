/**
 * Search Result Cache
 * Caches item search results to reduce API calls and improve performance
 */

class SearchCache {
    constructor(maxSize = 100, ttl = 5 * 60 * 1000) { // 5 minutes TTL
        this.cache = new Map();
        this.maxSize = maxSize;
        this.ttl = ttl;
    }

    /**
     * Generate cache key from search parameters
     */
    getKey(query, companyId, branchId, limit) {
        return `${companyId}:${branchId || 'null'}:${query.toLowerCase()}:${limit}`;
    }

    /**
     * Get cached result if available and not expired
     */
    get(query, companyId, branchId, limit) {
        const key = this.getKey(query, companyId, branchId, limit);
        const cached = this.cache.get(key);
        
        if (!cached) {
            return null;
        }
        
        // Check if expired
        if (Date.now() - cached.timestamp > this.ttl) {
            this.cache.delete(key);
            return null;
        }
        
        return cached.data;
    }

    /**
     * Store result in cache
     */
    set(query, companyId, branchId, limit, data) {
        const key = this.getKey(query, companyId, branchId, limit);
        
        // Evict oldest if cache is full
        if (this.cache.size >= this.maxSize) {
            const firstKey = this.cache.keys().next().value;
            this.cache.delete(firstKey);
        }
        
        this.cache.set(key, {
            data,
            timestamp: Date.now()
        });
    }

    /**
     * Clear cache
     */
    clear() {
        this.cache.clear();
    }

    /**
     * Clear expired entries
     */
    clearExpired() {
        const now = Date.now();
        for (const [key, value] of this.cache.entries()) {
            if (now - value.timestamp > this.ttl) {
                this.cache.delete(key);
            }
        }
    }
}

// Global search cache instance
window.searchCache = new SearchCache();
