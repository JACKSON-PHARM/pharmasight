/**
 * Organization URL context (?org= / ?tenant= / tenants.subdomain).
 * Persists per-tab so API calls resolve the same company deterministically.
 */
(function (global) {
    'use strict';

    const STORAGE_KEY = 'pharmasight_org_slug';
    const LEGACY_KEY = 'pharmasight_tenant_subdomain';

    function normalizeOrgSlug(raw) {
        if (!raw) return null;
        const s = String(raw).trim().toLowerCase();
        if (!s || s === '__default__' || s === 'default' || s === 'null') return null;
        return s;
    }

    function readFromUrl() {
        try {
            const params = new URLSearchParams(global.location.search || '');
            return (
                normalizeOrgSlug(params.get('org')) ||
                normalizeOrgSlug(params.get('tenant')) ||
                normalizeOrgSlug(params.get('subdomain'))
            );
        } catch (_) {
            return null;
        }
    }

    function getOrgSlug() {
        const fromUrl = readFromUrl();
        if (fromUrl) {
            persistOrgSlug(fromUrl);
            return fromUrl;
        }
        try {
            if (typeof sessionStorage !== 'undefined') {
                const s = normalizeOrgSlug(sessionStorage.getItem(STORAGE_KEY));
                if (s) return s;
            }
        } catch (_) {}
        try {
            if (typeof localStorage !== 'undefined') {
                return (
                    normalizeOrgSlug(localStorage.getItem(STORAGE_KEY)) ||
                    normalizeOrgSlug(localStorage.getItem(LEGACY_KEY))
                );
            }
        } catch (_) {}
        return null;
    }

    function persistOrgSlug(slug) {
        const s = normalizeOrgSlug(slug);
        if (!s) return;
        try {
            if (typeof sessionStorage !== 'undefined') sessionStorage.setItem(STORAGE_KEY, s);
        } catch (_) {}
        try {
            if (typeof localStorage !== 'undefined') {
                localStorage.setItem(STORAGE_KEY, s);
                localStorage.setItem(LEGACY_KEY, s);
            }
        } catch (_) {}
    }

    function clearOrgSlug() {
        try {
            if (typeof sessionStorage !== 'undefined') sessionStorage.removeItem(STORAGE_KEY);
        } catch (_) {}
        try {
            if (typeof localStorage !== 'undefined') {
                localStorage.removeItem(STORAGE_KEY);
                localStorage.removeItem(LEGACY_KEY);
            }
        } catch (_) {}
    }

    function applyOrgHeaders(headers) {
        if (!headers) return;
        const slug = getOrgSlug();
        if (!slug) return;
        headers['X-Company-Org'] = slug;
        headers['X-Tenant-Subdomain'] = slug;
    }

    function loginUrlForOrg(slug) {
        const s = normalizeOrgSlug(slug);
        if (!s) return global.location.origin + '/app#login';
        return global.location.origin + '/app?org=' + encodeURIComponent(s) + '#login';
    }

    async function fetchOrgBootstrap(slug) {
        const s = normalizeOrgSlug(slug);
        if (!s) return null;
        try {
            if (typeof global.reconcileApiBaseUrlForCurrentHost === 'function') {
                global.reconcileApiBaseUrlForCurrentHost();
            }
            const host = global.location.hostname;
            let base =
                typeof global.CONFIG !== 'undefined' && global.CONFIG.API_BASE_URL
                    ? String(global.CONFIG.API_BASE_URL).replace(/\/+$/, '')
                    : '';
            if (
                !base &&
                typeof global.isLocalDevLoginHost === 'function' &&
                global.isLocalDevLoginHost(host) &&
                typeof global.getDefaultLocalApiBase === 'function'
            ) {
                base = global.getDefaultLocalApiBase();
            }
            const url = (base || '') + '/api/org/' + encodeURIComponent(s) + '/bootstrap';
            const r = await fetch(url);
            if (!r.ok) return null;
            return await r.json();
        } catch (e) {
            console.warn('[org_context] bootstrap failed:', e && e.message);
            return null;
        }
    }

    // On load, capture org from URL into storage
    try {
        const initial = readFromUrl();
        if (initial) persistOrgSlug(initial);
    } catch (_) {}

    global.OrgContext = {
        normalizeOrgSlug,
        getOrgSlug,
        persistOrgSlug,
        clearOrgSlug,
        applyOrgHeaders,
        loginUrlForOrg,
        fetchOrgBootstrap,
    };
})(typeof window !== 'undefined' ? window : globalThis);
