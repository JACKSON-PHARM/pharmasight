/**
 * Subscription / trial messaging and shell restrictions.
 * Primary: GET /api/auth/me (subscription_access).
 * Fallback: any API 403 with detail.code === "trial_expired" (syncs UI with enforcement).
 */
(function () {
    var notifiedFromApi = false;
    var bannerCountdownTimer = null;

    var PLAN_LABELS = {
        demo: 'Demo',
        clinic_starter: 'Clinic Starter',
        pharmacy_growth: 'Growth',
        health_network: 'Network',
        enterprise: 'Enterprise',
    };

    function planLabel(slug) {
        if (!slug || String(slug).trim() === '') {
            return 'Standard';
        }
        var s = String(slug).trim().toLowerCase();
        if (PLAN_LABELS[s]) {
            return PLAN_LABELS[s];
        }
        return s.replace(/_/g, ' ').replace(/\b\w/g, function (ch) {
            return ch.toUpperCase();
        });
    }

    function clearBannerCountdown() {
        if (bannerCountdownTimer) {
            clearInterval(bannerCountdownTimer);
            bannerCountdownTimer = null;
        }
    }

    function formatCountdownParts(ms) {
        if (ms <= 0) {
            return { text: '0m', done: true };
        }
        var sec = Math.floor(ms / 1000);
        var d = Math.floor(sec / 86400);
        var h = Math.floor((sec % 86400) / 3600);
        var m = Math.floor((sec % 3600) / 60);
        var parts = [];
        if (d > 0) {
            parts.push(d + 'd');
        }
        if (h > 0 || d > 0) {
            parts.push(h + 'h');
        }
        parts.push(m + 'm');
        return { text: parts.join(' '), done: false };
    }

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
        if (fromMe === 'blocked') {
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
            var me = window.__authMe || {};
            var msg = '';
            if (me && me.subscription_access === 'blocked') {
                msg = 'Your account is inactive. Contact support to restore access.';
            }
            showGlobalNotice(msg);
        } else {
            if (searchBar) searchBar.style.display = '';
            if (quick) quick.style.display = '';
            if (modSwitch) modSwitch.style.display = '';
            hideGlobalNotice();
        }

        if (!banner) return;

        clearBannerCountdown();
        banner.classList.remove(
            'subscription-banner-strip--danger',
            'subscription-banner-strip--ok',
            'subscription-banner-strip--urgent',
        );

        if (!window.__authMe) {
            banner.style.display = 'none';
            banner.innerHTML = '';
            return;
        }

        if (acc === 'trial_expired') {
            banner.style.display = 'flex';
            banner.classList.add('subscription-banner-strip--danger');
            var meDead = window.__authMe || {};
            var pDead = planLabel(meDead.subscription_plan);
            banner.innerHTML =
                '<span class="subscription-banner-icon subscription-banner-warn" aria-hidden="true"><i class="fas fa-exclamation-circle"></i></span>' +
                '<span class="subscription-banner-text"><strong>' +
                pDead +
                '</strong> · Your access period has ended. Contact support to renew or upgrade.</span>';
            return;
        }

        var me = window.__authMe || {};
        var plan = planLabel(me.subscription_plan);
        var endIso = me.subscription_period_ends_at || me.trial_ends_at;
        var FIVE_DAYS_MS = 5 * 24 * 60 * 60 * 1000;

        banner.style.display = 'flex';

        if (!endIso) {
            banner.classList.add('subscription-banner-strip--ok');
            banner.innerHTML =
                '<span class="subscription-banner-icon" aria-hidden="true"><i class="fas fa-circle-check"></i></span>' +
                '<span class="subscription-banner-text"><strong>' +
                plan +
                '</strong> · Active. No renewal end date is set on your company profile.</span>';
            return;
        }

        var endMs = null;
        try {
            endMs = new Date(endIso).getTime();
        } catch (_) {
            endMs = null;
        }
        if (endMs == null || isNaN(endMs)) {
            banner.classList.add('subscription-banner-strip--ok');
            banner.innerHTML =
                '<span class="subscription-banner-icon" aria-hidden="true"><i class="fas fa-circle-check"></i></span>' +
                '<span class="subscription-banner-text"><strong>' + plan + '</strong> · Active</span>';
            return;
        }

        function paintBannerUrgent() {
            var now = Date.now();
            var left = endMs - now;
            var parts = formatCountdownParts(left);
            var icon =
                '<span class="subscription-banner-icon" aria-hidden="true"><i class="fas fa-clock"></i></span>';
            var dateStr = '';
            try {
                dateStr = new Date(endIso).toLocaleString();
            } catch (_) {
                dateStr = '';
            }
            banner.innerHTML =
                icon +
                '<span class="subscription-banner-text"><strong>' +
                plan +
                '</strong> · <span style="font-weight:700;">Renews/ends in ' +
                parts.text +
                '</span>' +
                (dateStr ? ' <span style="opacity:0.9;">(' + dateStr + ')</span>' : '') +
                '</span>';
            if (parts.done) {
                clearBannerCountdown();
            }
        }

        var now0 = Date.now();
        var diff0 = endMs - now0;

        if (diff0 > FIVE_DAYS_MS) {
            banner.classList.add('subscription-banner-strip--ok');
            var dateLong = '';
            try {
                dateLong = new Date(endIso).toLocaleString();
            } catch (_) {
                dateLong = '';
            }
            banner.innerHTML =
                '<span class="subscription-banner-icon" aria-hidden="true"><i class="fas fa-circle-check"></i></span>' +
                '<span class="subscription-banner-text"><strong>' +
                plan +
                '</strong> · Active. Access window ends <strong>' +
                dateLong +
                '</strong> (more than 5 days from now).</span>';
            return;
        }

        if (diff0 > 0) {
            banner.classList.add('subscription-banner-strip--urgent');
            paintBannerUrgent();
            var tickMs = diff0 < 48 * 60 * 60 * 1000 ? 1000 : 60 * 1000;
            bannerCountdownTimer = setInterval(paintBannerUrgent, tickMs);
            return;
        }

        banner.classList.add('subscription-banner-strip--urgent');
        banner.innerHTML =
            '<span class="subscription-banner-icon" aria-hidden="true"><i class="fas fa-exclamation-triangle"></i></span>' +
            '<span class="subscription-banner-text"><strong>' +
            plan +
            '</strong> · The scheduled end date has passed. Contact your administrator or support if you still need access.</span>';
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
