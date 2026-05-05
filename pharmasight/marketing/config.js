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
        WHATSAPP_E164: ((metaWa || '').replace(/\D/g, '')) || '254708476318'
    };
})();
