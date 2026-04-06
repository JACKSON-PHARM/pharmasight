/**
 * Subscription / trial messaging and shell restrictions.
 * Primary: GET /api/auth/me (subscription_access).
 * Fallback: any API 403 with detail.code === "trial_expired" (syncs UI with enforcement).
 */
(function () {
    var notifiedFromApi = false;

    function effectiveAccess() {
        var me = window.__authMe;
        var fromMe = me && me.subscription_access ? me.subscription_access : null;
        if (fromMe === 'full' || fromMe === 'trial') {
            if (fromMe === 'full') {
                notifiedFromApi = false;
                try {
                    window.__pharmasightTrialExpiredFromApi = false;
                } catch (_) {}
            }
            return fromMe;
        }
        if (fromMe === 'trial_expired') {
            return 'trial_expired';
        }
        if (notifiedFromApi || window.__pharmasightTrialExpiredFromApi) {
            return 'trial_expired';
        }
        return 'full';
    }

    function accessFromMe() {
        return effectiveAccess();
    }

    function getRedirectIfOutsideSubscription(routeBase) {
        if (effectiveAccess() !== 'trial_expired') return null;
        var allowed = new Set([
            'dashboard',
            'branch-select',
            'setup',
            'password-set',
            'password-reset',
            'reset-password',
            'tenant-invite-setup',
        ]);
        if (allowed.has(routeBase)) return null;
        return 'dashboard';
    }

    function ensureAuthMeTrialExpired() {
        window.__authMe = window.__authMe || {};
        window.__authMe.subscription_access = 'trial_expired';
    }

    function showGlobalNotice(message) {
        var el = document.getElementById('trialExpiredGlobalNotice');
        if (!el) return;
        var text =
            message && String(message).trim()
                ? String(message).trim()
                : 'Your trial has ended. Upgrade to restore full access — contact support.';
        el.removeAttribute('hidden');
        el.classList.add('is-visible');
        el.setAttribute('aria-hidden', 'false');
        el.innerHTML =
            '<span class="trial-expired-global-inner"><i class="fas fa-exclamation-triangle" aria-hidden="true"></i> ' +
            text +
            '</span>';
        if (document.body) {
            document.body.classList.add('trial-expired-global-active');
        }
    }

    function hideGlobalNotice() {
        var el = document.getElementById('trialExpiredGlobalNotice');
        if (el) {
            el.setAttribute('hidden', '');
            el.classList.remove('is-visible');
            el.setAttribute('aria-hidden', 'true');
            el.innerHTML = '';
        }
        if (document.body) {
            document.body.classList.remove('trial-expired-global-active');
        }
    }

    /**
     * Called when any app API returns 403 with trial_expired (e.g. stock-take) so the user
     * always sees the notice even if /api/auth/me was wrong or cached without subscription_access.
     */
    function notifyTrialExpiredFromApi(message) {
        if (notifiedFromApi) {
            return;
        }
        notifiedFromApi = true;
        try {
            window.__pharmasightTrialExpiredFromApi = true;
        } catch (_) {}
        ensureAuthMeTrialExpired();
        showGlobalNotice(message);
        refreshBannerAndShell();
        try {
            if (window.ModuleUI && typeof window.ModuleUI.setSelectedModule === 'function') {
                var sel = window.ModuleUI.getSelectedModule && window.ModuleUI.getSelectedModule();
                if (typeof sel === 'string' && sel) {
                    window.ModuleUI.setSelectedModule(sel, { navigate: false });
                }
            }
        } catch (_) {}
    }

    function refreshBannerAndShell() {
        var acc = effectiveAccess();
        var banner = document.getElementById('subscriptionBanner');
        var body = document.body;
        if (body) {
            body.classList.toggle('subscription-trial-expired', acc === 'trial_expired');
            body.classList.toggle('subscription-trial-active', acc === 'trial');
        }

        var searchBar = document.getElementById('globalItemSearchBar');
        var quick = document.getElementById('topBarQuickActions');
        var modSwitch = document.getElementById('moduleSwitcher');
        if (acc === 'trial_expired') {
            if (searchBar) searchBar.style.display = 'none';
            if (quick) quick.style.display = 'none';
            if (modSwitch) modSwitch.style.display = 'none';
            showGlobalNotice('');
        } else {
            if (searchBar) searchBar.style.display = '';
            if (quick) quick.style.display = '';
            if (modSwitch) modSwitch.style.display = '';
            hideGlobalNotice();
        }

        if (!banner) return;

        banner.classList.remove('subscription-banner-strip--danger');

        if (acc === 'full') {
            banner.style.display = 'none';
            banner.innerHTML = '';
            return;
        }

        if (acc === 'trial') {
            var me = window.__authMe || {};
            var days = me.trial_days_remaining;
            var ends = me.trial_ends_at;
            var line = 'Trial';
            if (days != null && days !== '') {
                line =
                    Number(days) === 1
                        ? 'Trial · 1 day remaining'
                        : 'Trial · ' + String(days) + ' days remaining';
            } else if (ends) {
                try {
                    line = 'Trial · ends ' + new Date(ends).toLocaleDateString();
                } catch (_) {
                    line = 'Trial';
                }
            } else {
                line = 'Trial';
            }
            banner.style.display = 'flex';
            banner.innerHTML =
                '<span class="subscription-banner-icon" aria-hidden="true"><i class="fas fa-hourglass-half"></i></span>' +
                '<span class="subscription-banner-text">' +
                line +
                '</span>';
            return;
        }

        if (acc === 'trial_expired') {
            banner.style.display = 'flex';
            banner.classList.add('subscription-banner-strip--danger');
            banner.innerHTML =
                '<span class="subscription-banner-icon subscription-banner-warn" aria-hidden="true"><i class="fas fa-exclamation-circle"></i></span>' +
                '<span class="subscription-banner-text">Your trial has ended. Contact support to upgrade and restore full access.</span>';
        }
    }

    function flushPendingFromApiFlag() {
        if (window.__pharmasightTrialExpiredFromApi && !notifiedFromApi) {
            notifyTrialExpiredFromApi('');
        }
    }

    window.SubscriptionUI = {
        accessFromMe,
        effectiveAccess,
        getRedirectIfOutsideSubscription,
        refreshBannerAndShell,
        notifyTrialExpiredFromApi,
        flushPendingFromApiFlag,
    };

    flushPendingFromApiFlag();
})();
