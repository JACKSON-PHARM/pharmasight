/**
 * Module UI service
 *
 * - Company entitlements: GET /api/company/modules → which modules are enabled for the tenant
 * - User capability (RBAC): GET /api/modules/me → which modules the user may use
 * - Switcher shows the intersection (enabled at company AND allowed for user)
 *
 * IMPORTANT: UI visibility only. Enforcement remains in backend route dependencies.
 */

(function () {
    const STORAGE_KEY = 'pharmasight_selected_module';

    const MODULE_LABELS = {
        pharmacy: 'Pharmacy',
        clinic: 'Clinic',
        lab: 'Lab',
        billing: 'Billing',
        finance: 'Finance',
        management: 'Admin',
    };

    /** Default hash route when entering a module or when current route is not allowed. */
    const MODULE_DEFAULT_PAGE = {
        pharmacy: 'dashboard',
        finance: 'cashbook',
        management: 'dashboard',
        clinic: 'patients',
        lab: 'module-coming-soon',
        billing: 'module-coming-soon',
    };

    /**
     * Sidebar definitions per module.
     * - Use `{ section, items: [...] }` for grouped nav; `{ page, label, icon, hasSub }` for a row.
     * - `page` must match loadPage() keys / hash routes.
     * Core surfaces (settings, reports, expenses) are merged in flattenSidebarConfig for non–Admin/Finance modules.
     */
    /** Appended to pharmacy, clinic, lab, billing (and unknown fallbacks). */
    const CORE_MANAGEMENT_SIDEBAR_BLOCKS = [
        {
            section: 'Management',
            items: [
                { page: 'settings', label: 'Settings', icon: 'fa-cog', hasSub: true },
                { page: 'reports', label: 'Reports', icon: 'fa-chart-bar', hasSub: true },
                { page: 'expenses', label: 'Expenses', icon: 'fa-money-bill-wave', hasSub: true },
            ],
        },
    ];

    const FINANCE_EXTRA_SETTINGS_BLOCK = [
        {
            section: 'Organization',
            items: [{ page: 'settings', label: 'Settings', icon: 'fa-cog', hasSub: true }],
        },
    ];

    const SIDEBAR_BY_MODULE = {
        pharmacy: [
            {
                section: 'Overview',
                items: [{ page: 'dashboard', label: 'Dashboard', icon: 'fa-chart-line', hasSub: false }],
            },
            {
                section: 'Sales',
                items: [{ page: 'sales', label: 'Sales', icon: 'fa-shopping-cart', hasSub: true }],
            },
            {
                section: 'Inventory',
                items: [{ page: 'inventory', label: 'Inventory', icon: 'fa-warehouse', hasSub: true }],
            },
            {
                section: 'Purchases',
                items: [{ page: 'purchases', label: 'Purchases', icon: 'fa-shopping-bag', hasSub: true }],
            },
        ],
        clinic: [
            {
                section: 'OPD',
                items: [
                    { page: 'patients', label: 'Patients', icon: 'fa-user-injured', hasSub: false },
                    { page: 'encounters', label: 'Queue', icon: 'fa-stream', hasSub: false },
                ],
            },
        ],
        lab: [],
        billing: [], // sidebar built from CORE_MANAGEMENT_SIDEBAR_BLOCKS in flattenSidebarConfig
        finance: [
            { page: 'cashbook', label: 'Cashbook', icon: 'fa-cash-register', hasSub: false },
            { page: 'expenses', label: 'Expenses', icon: 'fa-money-bill-wave', hasSub: true },
            { page: 'reports', label: 'Reports', icon: 'fa-chart-bar', hasSub: true },
        ],
        management: [
            {
                section: 'Overview',
                items: [{ page: 'dashboard', label: 'Dashboard', icon: 'fa-chart-line', hasSub: false }],
            },
            {
                section: 'Organization',
                items: [
                    { page: 'settings', label: 'Settings', icon: 'fa-cog', hasSub: true },
                    // Deep link: skips Settings submenu (same route as Settings → Users & Roles).
                    { page: 'settings-users', label: 'Users & Roles', icon: 'fa-users', hasSub: false },
                ],
            },
            {
                section: 'Insights',
                items: [{ page: 'reports', label: 'Reports', icon: 'fa-chart-bar', hasSub: true }],
            },
            // Platform admin section is injected dynamically for platform_super_admin.
        ],
    };

    /** Operational / system routes — module UX must not override these. */
    const MODULE_ROUTE_BYPASS = new Set(['branch-select', 'invite', 'stock-take']);

    /** Display order for the module switcher (not entitlement source). */
    const MODULE_SWITCHER_ORDER = ['pharmacy', 'clinic', 'lab', 'billing', 'finance', 'management'];

    let _modules = [];
    let _selected = null;
    let _initialized = false;
    /** Company-level enabled module names (from GET /api/company/modules). */
    let _enabledModules = new Set(['pharmacy']);
    let _companyModulesLoaded = false;

    function normalizeModuleName(m) {
        return String(m || '').trim().toLowerCase();
    }

    function safeReadSelectedModule() {
        try {
            const s = (localStorage.getItem(STORAGE_KEY) || sessionStorage.getItem(STORAGE_KEY) || '').trim();
            return s ? normalizeModuleName(s) : null;
        } catch (_) {
            return null;
        }
    }

    function safeWriteSelectedModule(m) {
        try {
            localStorage.setItem(STORAGE_KEY, m);
        } catch (_) {}
    }

    function moduleLabel(m) {
        return MODULE_LABELS[m] || (m ? m.charAt(0).toUpperCase() + m.slice(1) : 'Module');
    }

    function defaultPageForModule(moduleName) {
        const m = normalizeModuleName(moduleName);
        return MODULE_DEFAULT_PAGE[m] || 'dashboard';
    }

    function flattenSidebarConfig(moduleName) {
        const m = normalizeModuleName(moduleName);
        let root = SIDEBAR_BY_MODULE[m];
        if (!Array.isArray(root)) {
            root = [
                {
                    section: 'Overview',
                    items: [{ page: 'dashboard', label: 'Dashboard', icon: 'fa-chart-line', hasSub: false }],
                },
            ];
        }
        let blocks = root.slice();
        if (m === 'management' || m === 'finance') {
            if (m === 'finance') {
                blocks = blocks.concat(FINANCE_EXTRA_SETTINGS_BLOCK);
            }
        } else {
            blocks = blocks.concat(CORE_MANAGEMENT_SIDEBAR_BLOCKS);
        }
        const out = [];
        blocks.forEach((block) => {
            if (block && block.section && Array.isArray(block.items)) {
                out.push({ kind: 'section', label: block.section });
                block.items.forEach((it) => {
                    if (it && it.page) out.push({ kind: 'item', ...it });
                });
            } else if (block && block.page) {
                out.push({ kind: 'item', ...block });
            }
        });
        // Inject Platform Admin navigation only for platform_super_admin role.
        try {
            const roles = Array.isArray(window.__authMeRoles) ? window.__authMeRoles : [];
            const isPlatform = roles.map(normalizeModuleName).includes('platform_super_admin');
            if (m === 'management' && isPlatform) {
                out.push({ kind: 'section', label: 'Platform Admin' });
                out.push({ kind: 'item', page: 'platform-admin-companies', label: 'Companies', icon: 'fa-building', hasSub: false });
            }
        } catch (_) {}
        return out;
    }

    function allowedSidebarItems(moduleName) {
        const flat = flattenSidebarConfig(moduleName);
        return flat.filter((x) => x.kind === 'item');
    }

    /** Which top-level main-nav key should appear active for a full hash route. */
    function mainNavKeyForRoute(route) {
        const base = (route || '').split('?')[0] || '';
        const authPages = [
            'password-reset',
            'password-set',
            'reset-password',
            'branch-select',
            'stock-take',
            'tenant-invite-setup',
            'setup',
        ];
        if (authPages.includes(base)) return base;
        if (base === 'sales-history') return 'sales';
        if (base === 'cashbook') return 'reports';
        if (base === 'expenses-categories' || base === 'expenses-reports') return 'expenses';
        if (!base.includes('-')) return base;
        const first = base.split('-')[0];
        if (['sales', 'purchases', 'inventory', 'settings', 'expenses', 'reports'].includes(first)) {
            return first;
        }
        return base;
    }

    function isRouteAllowedForModule(moduleName, routeBase) {
        const m = normalizeModuleName(moduleName);
        const base = (routeBase || '').split('?')[0] || '';
        if (!base || MODULE_ROUTE_BYPASS.has(base)) return true;

        if (m === 'pharmacy') {
            if (base === 'landing') return false;
            if (base === 'dashboard' || base === 'stock-take' || base === 'items') {
                return true;
            }
            if (base.startsWith('sales')) return true;
            if (base.startsWith('purchases')) return true;
            if (base.startsWith('inventory')) return true;
            if (base.startsWith('settings')) return true;
            if (base.startsWith('reports')) return true;
            if (base.startsWith('expenses')) return true;
            if (base === 'cashbook') return true;
            return false;
        }
        if (m === 'finance') {
            if (base === 'landing') return false;
            if (base.startsWith('settings')) return true;
            if (base === 'cashbook') return true;
            if (base.startsWith('expenses')) return true;
            if (base.startsWith('reports')) return true;
            return false;
        }
        if (m === 'management') {
            if (base === 'landing') return false;
            if (base === 'dashboard') return true;
            if (base.startsWith('settings')) return true;
            if (base.startsWith('reports')) return true;
            if (base.startsWith('platform-admin-')) return true;
            return false;
        }
        if (m === 'clinic') {
            if (base === 'patients' || base === 'encounters' || base === 'consultation') return true;
            if (base.startsWith('settings')) return true;
            if (base.startsWith('reports')) return true;
            if (base.startsWith('expenses')) return true;
            if (base === 'cashbook') return true;
            return false;
        }
        if (m === 'lab' || m === 'billing') {
            if (base === 'module-coming-soon') return true;
            if (base.startsWith('settings')) return true;
            if (base.startsWith('reports')) return true;
            if (base.startsWith('expenses')) return true;
            if (base === 'cashbook') return true;
            return false;
        }
        // Unknown module: stay usable
        if (base === 'landing') return false;
        return true;
    }

    function firstVisibleModuleOrPharmacy() {
        if (_modules && _modules.length > 0) return _modules[0];
        return 'pharmacy';
    }

    function getRedirectIfOutsideModule(pageName) {
        const raw = String(pageName || '').split('?')[0] || '';
        if (!_initialized || !_selected) return null;
        if (MODULE_ROUTE_BYPASS.has(raw)) return null;

        const sel = normalizeModuleName(_selected);
        if (!_modules || !_modules.includes(sel)) {
            return defaultPageForModule(firstVisibleModuleOrPharmacy());
        }
        if (!isRouteAllowedForModule(sel, raw)) {
            return defaultPageForModule(sel);
        }
        return null;
    }

    function setActiveNavItem(page) {
        const mainNav = document.getElementById('mainNav');
        if (!mainNav) return;
        mainNav.querySelectorAll('.nav-item').forEach((a) => a.classList.remove('active'));
        const el = mainNav.querySelector(`.nav-item[data-page="${CSS.escape(page)}"]`);
        if (el) el.classList.add('active');
    }

    function renderSidebar(moduleName) {
        const mainNav = document.getElementById('mainNav');
        if (!mainNav) return;

        const rows = flattenSidebarConfig(moduleName);
        if (rows.length === 0) {
            mainNav.innerHTML =
                '<div class="nav-sidebar-empty-hint">This module has no navigation yet. Use the module switcher above to open another area.</div>';
            return;
        }

        const html = rows
            .map((row) => {
                if (row.kind === 'section') {
                    return `<div class="nav-section-label" role="presentation">${row.label}</div>`;
                }
                const it = row;
                const page = it.page;
                const hasSub = Boolean(it.hasSub && window.subNavItems && window.subNavItems[page]);
                const arrow = hasSub ? '<i class="fas fa-chevron-right nav-arrow"></i>' : '';
                return `
                <a href="#" class="nav-item" data-page="${page}" data-has-sub="${hasSub ? 'true' : 'false'}">
                    <i class="fas ${it.icon}"></i>
                    <span>${it.label}</span>
                    ${arrow}
                </a>`;
            })
            .join('\n');

        mainNav.innerHTML = html;

        try {
            const route = (window.location.hash || '').replace('#', '').split('?')[0] || '';
            setActiveNavItem(mainNavKeyForRoute(route));
        } catch (_) {}
    }

    function renderModuleSwitcher() {
        const wrap = document.getElementById('moduleSwitcher');
        if (!wrap) return;

        if (!_modules || _modules.length === 0) {
            wrap.innerHTML = '';
            return;
        }

        const buttons = _modules
            .map((m) => {
                const active = m === _selected ? 'active' : '';
                return `<button type="button" class="module-switcher-btn ${active}" data-module="${m}" aria-pressed="${m === _selected ? 'true' : 'false'}">${moduleLabel(m)}</button>`;
            })
            .join('');
        wrap.innerHTML = buttons;

        if (!wrap.__bound) {
            wrap.__bound = true;
            wrap.addEventListener('click', (e) => {
                const btn = e.target.closest('.module-switcher-btn');
                if (!btn) return;
                const m = normalizeModuleName(btn.getAttribute('data-module'));
                if (!m || m === _selected) return;
                setSelectedModule(m, { navigate: true, fromSwitcher: true });
            });
        }
    }

    function enforceCurrentRouteAllowed(opts = {}) {
        const route = (window.location.hash || '').replace('#', '').split('?')[0] || '';
        const target = getRedirectIfOutsideModule(route);
        if (!target) return;
        if (opts.fromSwitcher && typeof window.showToast === 'function') {
            window.showToast('Opening the default page for this module.', 'info');
        }
        if (typeof window.loadPage === 'function') {
            window.loadPage(target);
        } else {
            window.location.hash = '#' + target;
        }
    }

    function setSelectedModule(moduleName, opts = {}) {
        const m = normalizeModuleName(moduleName);
        if (!m) return;
        if (_modules && _modules.length > 0 && !_modules.includes(m)) return;

        _selected = m;
        safeWriteSelectedModule(m);
        renderModuleSwitcher();
        renderSidebar(m);

        if (opts.navigate === true) {
            enforceCurrentRouteAllowed({ fromSwitcher: Boolean(opts.fromSwitcher) });
        }
    }

    async function loadCompanyModules() {
        if (_companyModulesLoaded) return;
        try {
            if (!window.API || !API.company || typeof API.company.modules !== 'function') {
                _enabledModules = new Set(['pharmacy']);
            } else {
                const resp = await API.company.modules();
                const list = resp && Array.isArray(resp.modules) ? resp.modules : [];
                _enabledModules = new Set(
                    list.filter((x) => x && x.enabled).map((x) => normalizeModuleName(x.name)).filter(Boolean)
                );
                if (_enabledModules.size === 0) {
                    console.warn('[MODULE UI] No enabled modules from company API; defaulting pharmacy on.');
                    _enabledModules = new Set(['pharmacy']);
                }
            }
        } catch (e) {
            console.warn('[MODULE UI] Company modules unavailable; assuming pharmacy only.', e && e.message);
            _enabledModules = new Set(['pharmacy']);
        } finally {
            _companyModulesLoaded = true;
            if (window.ModuleUI) {
                window.ModuleUI.enabledModules = new Set(_enabledModules);
            }
        }
    }

    async function fetchUserModuleList() {
        try {
            if (!window.API || !API.modules || typeof API.modules.me !== 'function') {
                return [];
            }
            const resp = await API.modules.me();
            const list = resp && Array.isArray(resp.modules) ? resp.modules : [];
            return list.map(normalizeModuleName).filter(Boolean);
        } catch (e) {
            console.warn('[MODULE UI] /api/modules/me failed; falling back to pharmacy.', e && e.message);
            return [];
        }
    }

    function computeVisibleSwitcherModules(userList) {
        const u = userList.map(normalizeModuleName).filter(Boolean);
        // `/api/modules/me` already returns the safe visibility set:
        // (user RBAC modules) ∩ (core modules ∪ licensed company_modules).
        // So module switcher does not need to re-apply entitlement checks.
        let visible = MODULE_SWITCHER_ORDER.filter((m) => u.includes(m));
        if (!visible.length) visible = u;
        return visible;
    }

    async function init() {
        if (_initialized) return { modules: _modules, selected: _selected };
        _initialized = true;

        await loadCompanyModules();

        let userMods = await fetchUserModuleList();
        if (!userMods.length) {
            userMods = ['pharmacy'];
        }
        _modules = computeVisibleSwitcherModules(userMods);

        const stored = safeReadSelectedModule();
        let initial = stored && _modules.includes(stored) ? stored : _modules[0];
        if (!_modules.includes(normalizeModuleName(initial))) {
            initial = _modules[0];
        }
        _selected = normalizeModuleName(initial);
        safeWriteSelectedModule(_selected);

        renderModuleSwitcher();
        renderSidebar(_selected);

        return { modules: _modules, selected: _selected };
    }

    function bindComingSoonToast() {
        const mainNav = document.getElementById('mainNav');
        if (!mainNav || mainNav.__comingSoonBound) return;
        mainNav.__comingSoonBound = true;
        mainNav.addEventListener('click', (e) => {
            const a = e.target.closest('.nav-item[data-coming-soon="true"]');
            if (!a) return;
            try {
                if (typeof window.showToast === 'function') {
                    window.showToast('Coming soon.', 'info');
                }
            } catch (_) {}
        });
    }

    function loadModuleComingSoon() {
        const el = document.getElementById('module-coming-soon');
        if (!el) return;
        const label = moduleLabel(_selected);
        el.innerHTML = `
            <div class="card module-coming-soon-card">
                <div class="module-coming-soon-inner">
                    <div class="module-coming-soon-icon" aria-hidden="true"><i class="fas fa-layer-group"></i></div>
                    <h2>${label}</h2>
                    <p class="module-coming-soon-lead">This module is coming soon.</p>
                    <p class="module-coming-soon-hint">We are still building dedicated tools for this area. Switch modules above when you need Pharmacy, Finance, or Admin.</p>
                </div>
            </div>`;
    }

    window.loadModuleComingSoon = loadModuleComingSoon;

    window.ModuleUI = {
        loadCompanyModules,
        enabledModules: new Set(_enabledModules),
        init,
        getModules: () => _modules.slice(),
        getSelectedModule: () => _selected,
        setSelectedModule,
        getRedirectIfOutsideModule,
        defaultPageForModule,
        _bindComingSoonToast: bindComingSoonToast,
    };
})();
