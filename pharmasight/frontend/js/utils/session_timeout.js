/**
 * Session Timeout Management
 * 
 * Automatically logs out users after 30 minutes of inactivity.
 * Shows a 5-minute warning before logout.
 * Resets timer on any user activity (click, keypress, scroll, touch).
 * Handles tab visibility changes.
 */

const SessionTimeout = {
    TIMEOUT_DURATION: 30 * 60 * 1000, // 30 minutes in milliseconds
    WARNING_DURATION: 5 * 60 * 1000,  // 5 minutes warning before logout
    WARNING_THRESHOLD: 25 * 60 * 1000, // Show warning at 25 minutes (5 min before logout)
    
    timeoutId: null,
    warningTimeoutId: null,
    warningModal: null,
    countdownInterval: null,
    isInitialized: false,
    
    /**
     * Initialize session timeout monitoring
     * Call this after user is authenticated
     */
    init() {
        if (this.isInitialized) {
            console.log('[SESSION TIMEOUT] Already initialized');
            return;
        }
        
        console.log('[SESSION TIMEOUT] Initializing session timeout monitoring');
        this.isInitialized = true;
        
        // Reset timer on user activity
        this.setupActivityListeners();
        
        // Handle tab visibility changes
        this.setupVisibilityListener();
        
        // Start the timeout
        this.resetTimer();
    },
    
    /**
     * Setup event listeners for user activity.
     * keypress is excluded for item-search-input so typing in search does not reset the session timer.
     */
    setupActivityListeners() {
        const events = ['mousedown', 'mousemove', 'scroll', 'touchstart', 'click'];
        
        events.forEach(event => {
            document.addEventListener(event, () => {
                this.resetTimer();
            }, { passive: true });
        });
        
        // keypress: reset only for meaningful input (not item search field)
        document.addEventListener('keypress', (e) => {
            if (e.target && e.target.closest && e.target.closest('.item-search-input')) {
                return; // Do not reset session timer on item search keystrokes
            }
            this.resetTimer();
        }, { passive: true });
        
        console.log('[SESSION TIMEOUT] Activity listeners registered');
    },
    
    /**
     * Handle tab visibility changes
     * When user switches tabs, pause/resume timer appropriately
     */
    setupVisibilityListener() {
        document.addEventListener('visibilitychange', () => {
            if (document.hidden) {
                // Tab is hidden - pause timer (don't logout while user is away)
                console.log('[SESSION TIMEOUT] Tab hidden, pausing timer');
                this.pauseTimer();
            } else {
                // Tab is visible - resume timer
                console.log('[SESSION TIMEOUT] Tab visible, resuming timer');
                this.resumeTimer();
            }
        });
    },
    
    /**
     * Reset the timeout timer
     * Call this whenever user activity is detected
     */
    resetTimer() {
        // Clear existing timers
        this.clearTimers();
        
        // Hide warning modal if visible
        this.hideWarning();
        
        // Set new timeout for warning (at 25 minutes)
        this.warningTimeoutId = setTimeout(() => {
            this.showWarning();
        }, this.WARNING_THRESHOLD);
        
        // Set new timeout for logout (at 30 minutes)
        this.timeoutId = setTimeout(() => {
            this.handleTimeout();
        }, this.TIMEOUT_DURATION);
        
        console.log('[SESSION TIMEOUT] Timer reset - warning in 25 min, logout in 30 min');
    },
    
    /**
     * Pause timer (when tab is hidden)
     */
    pauseTimer() {
        // Store remaining time
        if (this.timeoutId) {
            const remaining = this.getRemainingTime();
            this.pausedRemaining = remaining;
            this.clearTimers();
        }
    },
    
    /**
     * Resume timer (when tab becomes visible)
     */
    resumeTimer() {
        if (this.pausedRemaining) {
            const remaining = this.pausedRemaining;
            this.pausedRemaining = null;
            
            // If less than warning threshold, show warning immediately
            if (remaining <= this.WARNING_DURATION) {
                this.showWarning();
            } else {
                // Reset warning timer
                const warningTime = remaining - this.WARNING_DURATION;
                this.warningTimeoutId = setTimeout(() => {
                    this.showWarning();
                }, warningTime);
            }
            
            // Set logout timer
            this.timeoutId = setTimeout(() => {
                this.handleTimeout();
            }, remaining);
        } else {
            // No paused time, just reset normally
            this.resetTimer();
        }
    },
    
    /**
     * Get remaining time until logout
     */
    getRemainingTime() {
        // This is approximate - actual implementation would track start time
        // For simplicity, we'll use a fixed calculation
        return this.TIMEOUT_DURATION;
    },
    
    /**
     * Show warning modal with countdown
     */
    showWarning() {
        if (this.warningModal) {
            return; // Already showing
        }
        
        console.log('[SESSION TIMEOUT] Showing warning modal');
        
        // Create modal
        const modal = document.createElement('div');
        modal.id = 'sessionTimeoutWarning';
        modal.className = 'session-timeout-modal';
        modal.innerHTML = `
            <div class="session-timeout-content">
                <div class="session-timeout-icon">
                    <i class="fas fa-clock"></i>
                </div>
                <h3>Session Timeout Warning</h3>
                <p>Your session will expire due to inactivity in <strong id="sessionCountdown">5:00</strong></p>
                <p style="font-size: 0.875rem; color: var(--text-secondary); margin-top: 0.5rem;">
                    Click anywhere or press any key to continue your session.
                </p>
                <button class="btn btn-primary" id="sessionTimeoutContinue">
                    <i class="fas fa-check"></i> Continue Session
                </button>
            </div>
        `;
        
        document.body.appendChild(modal);
        this.warningModal = modal;
        
        // Start countdown
        let secondsRemaining = 300; // 5 minutes
        this.countdownInterval = setInterval(() => {
            secondsRemaining--;
            const minutes = Math.floor(secondsRemaining / 60);
            const seconds = secondsRemaining % 60;
            const countdownEl = document.getElementById('sessionCountdown');
            if (countdownEl) {
                countdownEl.textContent = `${minutes}:${seconds.toString().padStart(2, '0')}`;
            }
            
            if (secondsRemaining <= 0) {
                clearInterval(this.countdownInterval);
            }
        }, 1000);
        
        // Handle continue button
        const continueBtn = document.getElementById('sessionTimeoutContinue');
        if (continueBtn) {
            continueBtn.addEventListener('click', () => {
                this.resetTimer();
            });
        }
        
        // Reset on any activity while warning is shown
        const resetOnActivity = () => {
            this.resetTimer();
        };
        
        document.addEventListener('click', resetOnActivity, { once: false });
        document.addEventListener('keypress', resetOnActivity, { once: false });
    },
    
    /**
     * Hide warning modal
     */
    hideWarning() {
        if (this.warningModal) {
            this.warningModal.remove();
            this.warningModal = null;
        }
        
        if (this.countdownInterval) {
            clearInterval(this.countdownInterval);
            this.countdownInterval = null;
        }
    },
    
    /**
     * Handle session timeout - logout user
     */
    async handleTimeout() {
        console.log('[SESSION TIMEOUT] Session expired, logging out');
        
        // Hide warning if still showing
        this.hideWarning();
        
        // Show logout message
        if (typeof showToast === 'function') {
            showToast('Your session has expired due to inactivity. Please log in again.', 'warning');
        }
        
        // Sign out via Supabase
        try {
            if (window.AuthBootstrap && typeof window.AuthBootstrap.signOut === 'function') {
                await window.AuthBootstrap.signOut();
            } else if (window.initSupabaseClient) {
                const supabase = window.initSupabaseClient();
                if (supabase) {
                    await supabase.auth.signOut();
                }
            }
        } catch (error) {
            console.error('[SESSION TIMEOUT] Error signing out:', error);
        }
        
        // Redirect to login
        if (window.loadPage) {
            window.loadPage('login');
        } else {
            window.location.hash = '#login';
        }
        
        // Clean up
        this.cleanup();
    },
    
    /**
     * Clear all timers
     */
    clearTimers() {
        if (this.timeoutId) {
            clearTimeout(this.timeoutId);
            this.timeoutId = null;
        }
        
        if (this.warningTimeoutId) {
            clearTimeout(this.warningTimeoutId);
            this.warningTimeoutId = null;
        }
    },
    
    /**
     * Clean up and stop monitoring
     * Call this on logout
     */
    cleanup() {
        console.log('[SESSION TIMEOUT] Cleaning up');
        this.clearTimers();
        this.hideWarning();
        this.isInitialized = false;
        this.pausedRemaining = null;
    }
};

// Export for use in other modules
if (typeof window !== 'undefined') {
    window.SessionTimeout = SessionTimeout;
}

// Export for Node.js/ES6 modules if needed
if (typeof module !== 'undefined' && module.exports) {
    module.exports = SessionTimeout;
}
