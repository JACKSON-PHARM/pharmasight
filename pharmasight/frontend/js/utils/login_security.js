/**
 * Login Security Utility
 * 
 * Brute Force Protection & Account Locking
 * - Blocks account after 5 failed login attempts within 15 minutes
 * - Shows remaining attempts to user
 * - Tracks attempts by email in localStorage
 * - Provides admin interface to unblock users
 */

const LoginSecurity = {
    MAX_ATTEMPTS: 5,
    LOCKOUT_DURATION: 15 * 60 * 1000, // 15 minutes in milliseconds
    STORAGE_KEY_PREFIX: 'login_attempts_',
    
    /**
     * Get storage key for email
     */
    getStorageKey(email) {
        return this.STORAGE_KEY_PREFIX + email.toLowerCase();
    },
    
    /**
     * Get attempt data for email
     */
    getAttemptData(email) {
        const key = this.getStorageKey(email);
        const data = localStorage.getItem(key);
        
        if (!data) {
            return {
                attempts: 0,
                firstAttempt: null,
                lastAttempt: null,
                blocked: false,
                blockedUntil: null
            };
        }
        
        try {
            const parsed = JSON.parse(data);
            // Check if lockout period has expired
            if (parsed.blockedUntil && new Date(parsed.blockedUntil) > new Date()) {
                parsed.blocked = true;
            } else if (parsed.blockedUntil && new Date(parsed.blockedUntil) <= new Date()) {
                // Lockout expired, reset
                parsed.blocked = false;
                parsed.blockedUntil = null;
                parsed.attempts = 0;
                parsed.firstAttempt = null;
            }
            
            // Check if attempts window has expired (15 minutes since first attempt)
            if (parsed.firstAttempt) {
                const firstAttemptTime = new Date(parsed.firstAttempt);
                const now = new Date();
                const timeSinceFirst = now - firstAttemptTime;
                
                if (timeSinceFirst > this.LOCKOUT_DURATION) {
                    // Window expired, reset attempts
                    parsed.attempts = 0;
                    parsed.firstAttempt = null;
                    parsed.lastAttempt = null;
                    if (!parsed.blocked) {
                        parsed.blockedUntil = null;
                    }
                }
            }
            
            return parsed;
        } catch (error) {
            console.error('[LOGIN SECURITY] Error parsing attempt data:', error);
            return {
                attempts: 0,
                firstAttempt: null,
                lastAttempt: null,
                blocked: false,
                blockedUntil: null
            };
        }
    },
    
    /**
     * Save attempt data for email
     */
    saveAttemptData(email, data) {
        const key = this.getStorageKey(email);
        try {
            localStorage.setItem(key, JSON.stringify(data));
        } catch (error) {
            console.error('[LOGIN SECURITY] Error saving attempt data:', error);
        }
    },
    
    /**
     * Record a failed login attempt
     */
    recordFailedAttempt(email) {
        const data = this.getAttemptData(email);
        const now = new Date();
        
        // Initialize first attempt if this is the first
        if (!data.firstAttempt) {
            data.firstAttempt = now.toISOString();
        }
        
        // Increment attempts
        data.attempts++;
        data.lastAttempt = now.toISOString();
        
        // Check if should block
        if (data.attempts >= this.MAX_ATTEMPTS) {
            data.blocked = true;
            const blockedUntil = new Date(now.getTime() + this.LOCKOUT_DURATION);
            data.blockedUntil = blockedUntil.toISOString();
            
            console.log(`[LOGIN SECURITY] Account blocked: ${email} until ${blockedUntil.toISOString()}`);
        }
        
        this.saveAttemptData(email, data);
        
        return {
            attempts: data.attempts,
            remaining: Math.max(0, this.MAX_ATTEMPTS - data.attempts),
            blocked: data.blocked,
            blockedUntil: data.blockedUntil
        };
    },
    
    /**
     * Clear failed attempts (on successful login)
     */
    clearAttempts(email) {
        const key = this.getStorageKey(email);
        localStorage.removeItem(key);
        console.log(`[LOGIN SECURITY] Cleared attempts for: ${email}`);
    },
    
    /**
     * Check if user is blocked
     */
    isUserBlocked(email) {
        const data = this.getAttemptData(email);
        return data.blocked && data.blockedUntil && new Date(data.blockedUntil) > new Date();
    },
    
    /**
     * Get remaining attempts
     */
    getRemainingAttempts(email) {
        const data = this.getAttemptData(email);
        return Math.max(0, this.MAX_ATTEMPTS - data.attempts);
    },
    
    /**
     * Get blocked until time
     */
    getBlockedUntil(email) {
        const data = this.getAttemptData(email);
        return data.blockedUntil ? new Date(data.blockedUntil) : null;
    },
    
    /**
     * Unblock user (admin function)
     */
    unblockUser(email) {
        const data = this.getAttemptData(email);
        data.blocked = false;
        data.blockedUntil = null;
        data.attempts = 0;
        data.firstAttempt = null;
        data.lastAttempt = null;
        
        this.saveAttemptData(email, data);
        console.log(`[LOGIN SECURITY] User unblocked: ${email}`);
    },
    
    /**
     * Get all blocked users (for admin interface)
     * Note: This only works for users with attempts in localStorage
     * For production, this should query a backend API
     */
    getAllBlockedUsers() {
        const blockedUsers = [];
        
        // Iterate through localStorage to find all blocked users
        for (let i = 0; i < localStorage.length; i++) {
            const key = localStorage.key(i);
            if (key && key.startsWith(this.STORAGE_KEY_PREFIX)) {
                const email = key.replace(this.STORAGE_KEY_PREFIX, '');
                const data = this.getAttemptData(email);
                
                if (data.blocked && data.blockedUntil && new Date(data.blockedUntil) > new Date()) {
                    blockedUsers.push({
                        email: email,
                        attempts: data.attempts,
                        blockedUntil: data.blockedUntil,
                        lastAttempt: data.lastAttempt
                    });
                }
            }
        }
        
        return blockedUsers;
    },
    
    /**
     * Get attempt statistics for a user (for admin interface)
     */
    getUserStats(email) {
        const data = this.getAttemptData(email);
        return {
            email: email,
            attempts: data.attempts,
            remaining: Math.max(0, this.MAX_ATTEMPTS - data.attempts),
            blocked: data.blocked,
            blockedUntil: data.blockedUntil,
            lastAttempt: data.lastAttempt,
            firstAttempt: data.firstAttempt
        };
    },
    
    /**
     * Format time until unblock (for display)
     */
    formatTimeUntilUnblock(blockedUntil) {
        if (!blockedUntil) return null;
        
        const now = new Date();
        const until = new Date(blockedUntil);
        const diff = until - now;
        
        if (diff <= 0) return null;
        
        const minutes = Math.floor(diff / 60000);
        const seconds = Math.floor((diff % 60000) / 1000);
        
        return `${minutes}:${seconds.toString().padStart(2, '0')}`;
    }
};

// Export for use in other modules
if (typeof window !== 'undefined') {
    window.LoginSecurity = LoginSecurity;
}

// Export for Node.js/ES6 modules if needed
if (typeof module !== 'undefined' && module.exports) {
    module.exports = LoginSecurity;
}
