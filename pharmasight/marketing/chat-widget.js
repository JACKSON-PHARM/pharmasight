/**
 * Marketing floating chat (Ask). Loaded on all /marketing/*.html pages.
 * Pricing answers use sightops_pricing_catalog.json when available.
 */
(function () {
    'use strict';

    var STORAGE_OPEN = 'ps_marketing_chat_open';
    var STORAGE_BODY = 'ps_marketing_chat_body_html';
    var CATALOG_URL = '/js/pricing/sightops_pricing_catalog.json?v=2026-05-kenya';
    var pricingCatalog = null;
    var catalogReady = false;

    function normalizeWaDigits(raw, fallback) {
        var d = String(raw || '').replace(/\D/g, '');
        if (!d) d = String(fallback || '').replace(/\D/g, '');
        if (!d) d = '254708476318';
        if (d.charAt(0) === '0' && d.length >= 10) d = '254' + d.slice(1);
        if (d.length === 9 && d.charAt(0) === '7') d = '254' + d;
        return d;
    }

    function getWaUrl() {
        var cfg = window.MARKETING_CONFIG || {};
        var ss = cfg.SITE_SETTINGS || {};
        var waDigits = normalizeWaDigits(ss.whatsapp, cfg.WHATSAPP_E164 || '254708476318');
        return (
            'https://wa.me/' +
            waDigits +
            '?text=' +
            encodeURIComponent('Hi SightOps — I have a question about the product.')
        );
    }

    function formatKes(amount) {
        var n = Number(amount);
        if (Number.isNaN(n)) return String(amount || '');
        return 'KES ' + n.toLocaleString('en-KE', { maximumFractionDigits: 0 });
    }

    function tierSlug(slug) {
        if (!pricingCatalog || !pricingCatalog.tiers) return null;
        var s = String(slug || '').toLowerCase();
        var i;
        for (i = 0; i < pricingCatalog.tiers.length; i++) {
            if (pricingCatalog.tiers[i].slug === s) return pricingCatalog.tiers[i];
        }
        var alias =
            pricingCatalog.legacy_tier_aliases && pricingCatalog.legacy_tier_aliases[s];
        if (alias) return tierSlug(alias);
        return null;
    }

    function loadPricingCatalog() {
        if (catalogReady) return Promise.resolve(pricingCatalog);
        return fetch(CATALOG_URL)
            .then(function (r) {
                if (!r.ok) throw new Error('catalog fetch failed');
                return r.json();
            })
            .then(function (data) {
                pricingCatalog = data;
                catalogReady = true;
                return data;
            })
            .catch(function () {
                pricingCatalog = {
                    retail_anchor_kes_monthly: 1499,
                    retail_pro_anchor_kes_monthly: 2999,
                    extra_user_kes_monthly: 599,
                    cloud_vs_desktop_note:
                        'SightOps is cloud-based with a monthly maintenance fee, not a one-time desktop licence.',
                };
                catalogReady = true;
                return pricingCatalog;
            });
    }

    function injectWidget() {
        if (document.getElementById('psChat')) return;
        document.body.insertAdjacentHTML(
            'beforeend',
            [
                '<div class="ps-chat" id="psChat" aria-live="polite">',
                '  <button class="ps-chat-fab" id="psChatFab" type="button" aria-haspopup="dialog" aria-controls="psChatPanel" aria-expanded="false">Ask</button>',
                '  <section class="ps-chat-panel" id="psChatPanel" role="dialog" aria-modal="false" aria-label="SightOps assistant" hidden>',
                '    <header class="ps-chat-header">',
                '      <div class="ps-chat-title">SightOps assistant</div>',
                '      <button class="ps-chat-close" id="psChatClose" type="button" aria-label="Close chat">&times;</button>',
                '    </header>',
                '    <div class="ps-chat-body" id="psChatBody">',
                '      <div class="ps-chat-msg ps-chat-msg--bot">',
                '        Hi! Ask about pricing, cloud vs desktop, Solo vs Pro, setup, or what SightOps does. Quick picks below.',
                '      </div>',
                '      <div class="ps-chat-quick" id="psChatQuick">',
                '        <button type="button" class="ps-chat-chip" data-q="How much does SightOps cost?">Pricing</button>',
                '        <button type="button" class="ps-chat-chip" data-q="Why monthly subscription instead of one-time?">Cloud vs desktop</button>',
                '        <button type="button" class="ps-chat-chip" data-q="What is Retail Solo vs Retail Pro?">Solo vs Pro</button>',
                '        <button type="button" class="ps-chat-chip" data-q="What does SightOps do?">What does it do?</button>',
                '        <button type="button" class="ps-chat-chip" data-q="How do I get started?">Get started</button>',
                '        <button type="button" class="ps-chat-chip" data-q="How do you protect my data privacy?">Data privacy</button>',
                '      </div>',
                '    </div>',
                '    <form class="ps-chat-input" id="psChatForm">',
                '      <input id="psChatText" type="text" autocomplete="off" placeholder="Type your question…" aria-label="Your message">',
                '      <button class="btn btn-primary" type="submit">Send</button>',
                '    </form>',
                '    <div class="ps-chat-footer">',
                '      <a class="ps-chat-link" href="signup.html">Start free trial</a>',
                '      <span class="ps-chat-dot">&middot;</span>',
                '      <a class="ps-chat-link" href="pricing.html">Pricing</a>',
                '      <span class="ps-chat-dot">&middot;</span>',
                '      <a class="ps-chat-link" href="pricing-policy.html">Pricing Policy</a>',
                '    </div>',
                '  </section>',
                '</div>',
            ].join('\n'),
        );
    }

    function qs(x) {
        return String(x || '')
            .trim()
            .toLowerCase();
    }

    function ctaLinksHtml() {
        var wa = getWaUrl();
        return (
            "<div class='ps-chat-cta'>" +
            "<a href='signup.html'>Start free trial &rarr;</a>" +
            "<a href='pricing.html'>See pricing</a>" +
            "<a href='pricing-policy.html'>Pricing Policy</a>" +
            "<a href='" +
            wa +
            "' target='_blank' rel='noopener noreferrer'>WhatsApp</a>" +
            '</div>'
        );
    }

    function pricingSummaryHtml() {
        var c = pricingCatalog || {};
        var solo = tierSlug('retail_solo');
        var pro = tierSlug('retail_pro');
        var soloPrice = solo && solo.kes_monthly != null ? formatKes(solo.kes_monthly) : formatKes(c.retail_anchor_kes_monthly || 1499);
        var proPrice = pro && pro.kes_monthly != null ? formatKes(pro.kes_monthly) : formatKes(c.retail_pro_anchor_kes_monthly || 2999);
        var extra = formatKes(c.extra_user_kes_monthly || 599);
        return (
            '<p><strong>Maintenance (monthly)</strong> keeps our cloud running — unlike one-time offline desktop POS apps.</p>' +
            '<ul>' +
            '<li><strong>Retail Solo</strong> — ' +
            soloPrice +
            '/mo: affordable single shop (limited users/products; basic reports).</li>' +
            '<li><strong>Retail Pro</strong> — ' +
            proPrice +
            '/mo: full retail (extended reports, eTIMS path, priority support).</li>' +
            '<li>Multi-branch, wholesale depot, and clinic modules are on higher tiers.</li>' +
            '<li>Optional <strong>one-time</strong> setup &amp; training — separate from maintenance.</li>' +
            '<li>Extra users: ' +
            extra +
            '/user/month (beyond tier caps).</li>' +
            '<li>Pay annually: 2 months free (10 months paid, 12 months service).</li>' +
            '</ul>'
        );
    }

    function replyFor(question) {
        var q = qs(question);
        if (!q) return 'Ask me about pricing, setup, or what SightOps does.' + ctaLinksHtml();

        if (
            q.indexOf('policy') >= 0 ||
            q.indexOf('terms') >= 0 ||
            q.indexOf('contract') >= 0
        ) {
            return (
                '<p>Our <a href="pricing-policy.html">Pricing Policy</a> explains maintenance vs one-time setup/training, tier caps, and refunds. It is incorporated into our <a href="terms.html">Terms of Service</a>.</p>' +
                ctaLinksHtml()
            );
        }

        if (
            q.indexOf('one-time') >= 0 ||
            q.indexOf('one time') >= 0 ||
            q.indexOf('desktop') >= 0 ||
            q.indexOf('offline') >= 0 ||
            q.indexOf('perpetual') >= 0 ||
            (q.indexOf('why') >= 0 && q.indexOf('month') >= 0) ||
            (q.indexOf('cloud') >= 0 && q.indexOf('desktop') >= 0)
        ) {
            var note =
                (pricingCatalog && pricingCatalog.cloud_vs_desktop_note) ||
                'SightOps is cloud-based: multi-device access, backups, and updates without reinstalling.';
            return (
                '<p>' +
                note +
                '</p><p>Many Kenyan POS products charge once because they are offline desktop software on one PC. We charge <strong>monthly maintenance</strong> for servers, security, and ongoing development. Optional setup/training are <strong>one-time</strong> and do not replace maintenance.</p>' +
                ctaLinksHtml()
            );
        }

        if (
            q.indexOf('solo') >= 0 ||
            q.indexOf('pro') >= 0 ||
            (q.indexOf('difference') >= 0 && q.indexOf('plan') >= 0)
        ) {
            return (
                '<p><strong>Retail Solo</strong> is our affordable entry tier — usable for one small pharmacy with honest limits so you can start and leave reviews.</p>' +
                '<p><strong>Retail Pro</strong> is recommended: higher user/product caps, extended reports &amp; exports, eTIMS-ready workflows, and priority support. Wholesale, clinic, and multi-branch need Growth or higher.</p>' +
                pricingSummaryHtml() +
                ctaLinksHtml()
            );
        }

        if (
            q.indexOf('price') >= 0 ||
            q.indexOf('cost') >= 0 ||
            q.indexOf('pricing') >= 0 ||
            q.indexOf('how much') >= 0 ||
            q.indexOf('kes') >= 0 ||
            q.indexOf('subscription') >= 0 ||
            q.indexOf('maintenance') >= 0
        ) {
            return pricingSummaryHtml() + ctaLinksHtml();
        }

        if (
            q.indexOf('setup') >= 0 ||
            q.indexOf('training') >= 0 ||
            q.indexOf('onboard') >= 0 ||
            q.indexOf('implementation') >= 0
        ) {
            return (
                '<p><strong>Self-setup is free</strong> (tutorials). Paid optional packages include remote launch (~KES 10,000), on-site launch (~KES 20,000), migration, and staff training — all <strong>one-time</strong> and separate from monthly maintenance.</p>' +
                '<p>See <a href="pricing.html">Pricing</a> for current list prices.</p>' +
                ctaLinksHtml()
            );
        }

        if (
            q.indexOf('trial') >= 0 ||
            q.indexOf('demo') >= 0 ||
            q.indexOf('signup') >= 0 ||
            q.indexOf('sign up') >= 0 ||
            q.indexOf('get started') >= 0 ||
            q.indexOf('started') >= 0
        ) {
            return (
                '<p>Start a <strong>free trial</strong> on our signup page — create your organisation, then use the operations app. After trial, choose <strong>Retail Solo</strong> or <strong>Pro</strong> maintenance to continue.</p>' +
                ctaLinksHtml()
            );
        }

        if (q.indexOf('clinic') >= 0 || q.indexOf('opd') >= 0) {
            return (
                '<p>Clinic/OPD workflows are on <strong>Health Network</strong> tier and above (not Solo/Pro). Retail pharmacy starts at Solo/Pro maintenance.</p>' +
                ctaLinksHtml()
            );
        }

        if (q.indexOf('wholesale') >= 0 || q.indexOf('b2b') >= 0) {
            return (
                '<p>Wholesale B2B, customer AR, and batch lines on receipts need a <strong>wholesale depot branch</strong> and a plan that includes wholesale (Retail Growth or higher).</p>' +
                ctaLinksHtml()
            );
        }

        if (q.indexOf('agro') >= 0 || q.indexOf('agrovet') >= 0 || q.indexOf('vet') >= 0) {
            return (
                '<p>Agrovet counters use the same retail inventory and sales flows — typically <strong>Retail Solo</strong> or <strong>Pro</strong> for a single shop.</p>' +
                ctaLinksHtml()
            );
        }

        if (q.indexOf('what') >= 0 && (q.indexOf('do') >= 0 || q.indexOf('does') >= 0)) {
            return (
                '<p>SightOps is cloud ERP for stock-heavy teams: inventory, sales, purchases, expiry/batch awareness, margins, and branch-aware operations — pharmacy, clinic, wholesale, and agrovet.</p>' +
                ctaLinksHtml()
            );
        }

        if (
            q.indexOf('expiry') >= 0 ||
            q.indexOf('expiries') >= 0 ||
            q.indexOf('expire') >= 0 ||
            q.indexOf('batch') >= 0
        ) {
            return (
                '<p>Yes — track batches and see items nearing expiry so you can act before losses.</p>' +
                ctaLinksHtml()
            );
        }

        if (
            q.indexOf('privacy') >= 0 ||
            q.indexOf('confidential') >= 0 ||
            q.indexOf('spy') >= 0 ||
            q.indexOf('spying') >= 0 ||
            q.indexOf('supabase') >= 0 ||
            q.indexOf('leak') >= 0 ||
            q.indexOf('secure') >= 0 ||
            q.indexOf('security') >= 0
        ) {
            return (
                '<p>Great question. We uphold confidentiality at all times — SightOps is not built to spy on client data.</p>' +
                '<p>Your data is handled in a multi-tenant setup with company-level isolation and internal authentication/authorization controls, so one client cannot browse another client's records.</p>' +
                '<p>We host data on Supabase-backed infrastructure and apply controlled application access paths rather than open direct access.</p>' +
                '<p>During onboarding, we can also review user roles and permissions with your team so access is limited to authorized staff only.</p>' +
                ctaLinksHtml()
            );
        }

        if (q.indexOf('margin') >= 0 || q.indexOf('profit') >= 0) {
            return (
                '<p>Margins are visible while you price and sell so you can make confident decisions.</p>' +
                ctaLinksHtml()
            );
        }

        return (
            '<p>I can help with pricing, cloud vs desktop, Solo vs Pro, setup, or product fit. Try a quick question above.</p>' +
            ctaLinksHtml()
        );
    }

    function persistSnapshot(bodyEl, panelEl) {
        try {
            if (bodyEl) sessionStorage.setItem(STORAGE_BODY, bodyEl.innerHTML);
            var open = panelEl && !panelEl.hidden;
            sessionStorage.setItem(STORAGE_OPEN, open ? '1' : '0');
        } catch (_e) {}
    }

    function init() {
        loadPricingCatalog();
        injectWidget();

        var fab = document.getElementById('psChatFab');
        var panel = document.getElementById('psChatPanel');
        var closeBtn = document.getElementById('psChatClose');
        var askBtn = document.getElementById('askQuestionBtn');
        var body = document.getElementById('psChatBody');
        var form = document.getElementById('psChatForm');
        var input = document.getElementById('psChatText');
        var quick = document.getElementById('psChatQuick');

        if (!fab || !panel || !body) return;

        try {
            var savedBody = sessionStorage.getItem(STORAGE_BODY);
            if (savedBody && savedBody.indexOf('psChatQuick') >= 0) {
                body.innerHTML = savedBody;
                quick = document.getElementById('psChatQuick');
                form = document.getElementById('psChatForm');
                input = document.getElementById('psChatText');
                body.scrollTop = body.scrollHeight;
            }
        } catch (_e) {}

        function appendMsg(container, text, isUser, allowHtml) {
            var el = document.createElement('div');
            el.className = 'ps-chat-msg ' + (isUser ? 'ps-chat-msg--user' : 'ps-chat-msg--bot');
            if (!isUser && allowHtml) {
                el.innerHTML = text;
            } else {
                el.textContent = text;
            }
            container.appendChild(el);
            container.scrollTop = container.scrollHeight;
            persistSnapshot(body, panel);
        }

        function openChat(opts) {
            var focus = opts && opts.focus;
            panel.hidden = false;
            fab.setAttribute('aria-expanded', 'true');
            persistSnapshot(body, panel);
            if (focus !== false) {
                setTimeout(function () {
                    if (input) input.focus();
                }, 0);
            }
        }

        function closeChat() {
            panel.hidden = true;
            fab.setAttribute('aria-expanded', 'false');
            persistSnapshot(body, panel);
        }

        try {
            if (sessionStorage.getItem(STORAGE_OPEN) === '1') {
                openChat({ focus: false });
                body.scrollTop = body.scrollHeight;
            }
        } catch (_e2) {}

        fab.addEventListener('click', function () {
            if (panel.hidden) openChat({ focus: true });
            else closeChat();
        });
        if (closeBtn) closeBtn.addEventListener('click', closeChat);
        if (askBtn) askBtn.addEventListener('click', function () {
            openChat({ focus: true });
        });

        if (quick) {
            quick.addEventListener('click', function (e) {
                var t = e && e.target;
                if (!t || !t.getAttribute) return;
                var qq = t.getAttribute('data-q');
                if (!qq) return;
                openChat({ focus: true });
                appendMsg(body, qq, true);
                loadPricingCatalog().then(function () {
                    appendMsg(body, replyFor(qq), false, true);
                });
            });
        }

        if (form) {
            form.addEventListener('submit', function (e) {
                e.preventDefault();
                var txt = input ? input.value : '';
                if (!String(txt || '').trim()) return;
                appendMsg(body, txt, true);
                if (input) input.value = '';
                loadPricingCatalog().then(function () {
                    appendMsg(body, replyFor(txt), false, true);
                });
            });
        }

        document.addEventListener('keydown', function (e) {
            if (!panel || panel.hidden) return;
            if (e && e.key === 'Escape') closeChat();
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
