/**
 * Resolve company / branch context for navigation (single shared DB, company_id tenancy).
 */
(function (global) {
    'use strict';

    function normalizeCompanies(res) {
        if (Array.isArray(res)) return res;
        if (res && Array.isArray(res.companies)) return res.companies;
        return [];
    }

    function normalizeBranches(res) {
        if (Array.isArray(res)) return res;
        if (res && Array.isArray(res.branches)) return res.branches;
        return [];
    }

    function readCompanyIdFromAccessToken() {
        try {
            if (typeof localStorage === 'undefined') return null;
            const t = localStorage.getItem('pharmasight_access_token');
            if (!t) return null;
            const parts = t.split('.');
            if (parts.length < 2) return null;
            const b64 = parts[1].replace(/-/g, '+').replace(/_/g, '/');
            const pad = b64.length % 4 === 0 ? '' : '='.repeat(4 - (b64.length % 4));
            const payload = JSON.parse(atob(b64 + pad));
            const cid = (payload.company_id || '').trim();
            return cid || null;
        } catch (_) {
            return null;
        }
    }

    async function validateCompanyId(companyId) {
        if (!companyId || !global.API || !global.API.company || typeof global.API.company.get !== 'function') {
            return false;
        }
        try {
            await global.API.company.get(companyId);
            return true;
        } catch (e) {
            if (e && (e.status === 404 || e.status === 403)) return false;
            throw e;
        }
    }

    /**
     * Resolve the user's company id for navigation (auth/me, list, config, JWT, startup).
     * @returns {Promise<string|null>}
     */
    async function resolveUserCompanyId() {
        const me = global.__authMe;
        if (me && me.company_id) {
            if (await validateCompanyId(me.company_id)) return String(me.company_id);
        }

        const jwtCid = readCompanyIdFromAccessToken();
        if (jwtCid && (await validateCompanyId(jwtCid))) return jwtCid;

        if (global.API && global.API.company && typeof global.API.company.list === 'function') {
            try {
                const companies = normalizeCompanies(await global.API.company.list());
                if (companies.length > 0 && companies[0].id) return String(companies[0].id);
            } catch (e) {
                console.warn('[tenant_company] company.list failed:', e && e.message);
            }
        }

        const cfg =
            typeof global.CONFIG !== 'undefined' && global.CONFIG.COMPANY_ID
                ? String(global.CONFIG.COMPANY_ID)
                : '';
        if (cfg && (await validateCompanyId(cfg))) return cfg;

        if (global.API && global.API.startup && typeof global.API.startup.status === 'function') {
            try {
                const st = await global.API.startup.status();
                if (st && st.initialized && st.company_id && (await validateCompanyId(st.company_id))) {
                    return String(st.company_id);
                }
            } catch (e) {
                console.warn('[tenant_company] startup.status failed:', e && e.message);
            }
        }

        return null;
    }

    function userCanListAllBranches() {
        const roles = Array.isArray(global.__authMeRoles) ? global.__authMeRoles : [];
        return roles.some((r) =>
            ['admin', 'owner', 'super admin', 'manager', 'super_admin'].includes(String(r).toLowerCase())
        );
    }

    /**
     * @returns {Promise<{ branches: Array, hasVisibleBranches: boolean }>}
     */
    async function resolveUserBranches(companyId) {
        if (!companyId || !global.API || !global.API.branch) {
            return { branches: [], hasVisibleBranches: false };
        }

        const fetchList = async (fn) => {
            try {
                return normalizeBranches(await fn());
            } catch (e) {
                console.warn('[tenant_company] branch list failed:', e && e.message);
                return [];
            }
        };

        let branches = [];
        if (typeof global.API.branch.list === 'function') {
            branches = await fetchList(() => global.API.branch.list(companyId));
        }
        if (branches.length === 0 && userCanListAllBranches() && typeof global.API.branch.listAll === 'function') {
            branches = await fetchList(() => global.API.branch.listAll(companyId));
        }

        return { branches, hasVisibleBranches: branches.length > 0 };
    }

    /**
     * True only when no company exists yet (brand-new tenant). API errors with known company → not setup.
     */
    async function shouldShowSetupWizard() {
        const companyId = await resolveUserCompanyId();
        if (companyId) return false;

        if (global.API && global.API.startup && typeof global.API.startup.status === 'function') {
            try {
                const st = await global.API.startup.status();
                return !(st && st.initialized);
            } catch (e) {
                console.warn('[tenant_company] startup.status for setup gate failed:', e && e.message);
                return false;
            }
        }
        return true;
    }

    global.TenantCompany = {
        normalizeCompanies,
        normalizeBranches,
        readCompanyIdFromAccessToken,
        resolveUserCompanyId,
        resolveUserBranches,
        shouldShowSetupWizard,
        userCanListAllBranches,
    };
})(typeof window !== 'undefined' ? window : globalThis);
