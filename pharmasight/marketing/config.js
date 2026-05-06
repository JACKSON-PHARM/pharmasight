/**
 * If user lands on / or /marketing/* with an ERP hash (#login, #password-reset, handoff, etc.),
 * send them to the SPA mount at /app so they never see the marketing shell by mistake.
 */
(function () {
    try {
        var path = window.location.pathname || '';
        var onMarketingShell =
            path === '/' ||
            path === '/marketing' ||
            path.indexOf('/marketing/') === 0;
        if (!onMarketingShell) return;
        var h = window.location.hash || '';
        if (h.length > 1) {
            window.location.replace(window.location.origin + '/app' + window.location.search + h);
        }
    } catch (_e) {}
})();

/**
 * Global marketing light/dark theme: localStorage key ps_theme. Same preference on every /marketing/* page.
 * Default when unset: dark (matches signup, portal, pricing).
 */
(function () {
    if (typeof document === 'undefined') return;
    try {
        var saved = localStorage.getItem('ps_theme');
        var mode = saved === 'light' || saved === 'dark' ? saved : 'dark';
        document.documentElement.setAttribute('data-theme', mode);
    } catch (_e) {
        document.documentElement.setAttribute('data-theme', 'dark');
    }
})();

/**
 * Override via optional <meta name="pharmasight-api-base" content="https://api.example.com">
 * and <meta name="pharmasight-erp-url" content="https://app.example.com"> on each HTML page.
 */
(function () {
    if (typeof window === 'undefined') return;
    function readMeta(name) {
        var el = document.querySelector('meta[name="' + name + '"]');
        return el && el.getAttribute('content') ? el.getAttribute('content').trim() : '';
    }
    var metaApi = readMeta('pharmasight-api-base');
    var metaErp = readMeta('pharmasight-erp-url');
    var metaWa = readMeta('pharmasight-whatsapp');
    var h = window.location.hostname;
    var sameOrigin = (window.location.origin || '').replace(/\/$/, '');
    var api = metaApi ? metaApi.replace(/\/$/, '') : sameOrigin;
    if ((h === 'localhost' || h === '127.0.0.1') && !metaApi) {
        var p = window.location.port;
        if (p && p !== '8000' && p !== '8001') {
            api = 'http://127.0.0.1:8000';
        }
    }
    window.MARKETING_CONFIG = {
        API_BASE_URL: api,
        ERP_APP_URL: (metaErp || sameOrigin).replace(/\/$/, ''),
        WHATSAPP_E164: ((metaWa || '').replace(/\D/g, '')) || '254708476318',
        SITE_SETTINGS: null,
        site_settings_ready: null
    };

    function applyMarketingAssets(settings) {
        if (!settings || typeof document === 'undefined') return;
        var logo = (settings.logo_url || '').trim();
        document.querySelectorAll('[data-marketing-logo]').forEach(function (img) {
            if (logo) img.src = logo;
        });
        var images = settings.marketing_images || {};
        document.querySelectorAll('[data-marketing-image]').forEach(function (el) {
            var key = el.getAttribute('data-marketing-image');
            if (!key || !images[key]) return;
            var u = String(images[key]).trim();
            if (!u) return;
            el.src = u;
            if (el.tagName === 'IMG') el.style.display = 'block';
        });
        document.querySelectorAll('[data-marketing-meta]').forEach(function (el) {
            var key = el.getAttribute('data-marketing-meta');
            if (!key || !images[key]) return;
            var u = String(images[key]).trim();
            if (!u) return;
            el.setAttribute('content', u);
        });
        document.querySelectorAll('[data-marketing-link]').forEach(function (el) {
            var key = el.getAttribute('data-marketing-link');
            if (!key || !images[key]) return;
            var u = String(images[key]).trim();
            if (!u) return;
            el.setAttribute('href', u);
        });
    }

    function scheduleApplyMarketingAssets(settings) {
        function run() {
            try {
                applyMarketingAssets(settings || {});
            } catch (_e) {}
        }
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', run);
        } else {
            run();
        }
    }

    try {
        window.addEventListener('pharmasight:site-settings', function (ev) {
            scheduleApplyMarketingAssets(ev && ev.detail ? ev.detail : {});
        });
    } catch (_e) {}

    // Fetch public site settings (contacts). Pages can await MARKETING_CONFIG.site_settings_ready
    // or listen to `pharmasight:site-settings` event.
    try {
        window.MARKETING_CONFIG.site_settings_ready = fetch(api + '/api/public/site-settings', {
            method: 'GET',
            headers: { 'Content-Type': 'application/json' }
        })
            .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
            .then(function (x) {
                window.MARKETING_CONFIG.SITE_SETTINGS = (x && x.ok && x.j) ? x.j : {};
                scheduleApplyMarketingAssets(window.MARKETING_CONFIG.SITE_SETTINGS);
                try {
                    window.dispatchEvent(new CustomEvent('pharmasight:site-settings', { detail: window.MARKETING_CONFIG.SITE_SETTINGS }));
                } catch (_e) {}
                return window.MARKETING_CONFIG.SITE_SETTINGS;
            })
            .catch(function () {
                window.MARKETING_CONFIG.SITE_SETTINGS = {};
                scheduleApplyMarketingAssets(window.MARKETING_CONFIG.SITE_SETTINGS);
                return window.MARKETING_CONFIG.SITE_SETTINGS;
            });
    } catch (_e) {
        window.MARKETING_CONFIG.SITE_SETTINGS = {};
        scheduleApplyMarketingAssets(window.MARKETING_CONFIG.SITE_SETTINGS);
        window.MARKETING_CONFIG.site_settings_ready = Promise.resolve(window.MARKETING_CONFIG.SITE_SETTINGS);
    }
})();

/**
 * Optional button id="themeToggle" on marketing pages — keeps icon in sync and persists ps_theme.
 */
(function () {
    if (typeof document === 'undefined') return;
    function bindMarketingThemeToggle() {
        var themeBtn = document.getElementById('themeToggle');
        if (!themeBtn || themeBtn.getAttribute('data-ps-theme-bound') === '1') return;
        themeBtn.setAttribute('data-ps-theme-bound', '1');
        function syncIcon() {
            var m = document.documentElement.getAttribute('data-theme') || 'dark';
            themeBtn.textContent = m === 'light' ? '☀️' : '🌙';
        }
        syncIcon();
        themeBtn.addEventListener('click', function () {
            var c = document.documentElement.getAttribute('data-theme') || 'dark';
            var next = c === 'light' ? 'dark' : 'light';
            document.documentElement.setAttribute('data-theme', next);
            try {
                localStorage.setItem('ps_theme', next);
            } catch (_e2) {}
            syncIcon();
        });
    }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', bindMarketingThemeToggle);
    } else {
        bindMarketingThemeToggle();
    }
})();
