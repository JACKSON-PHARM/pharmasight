/**
 * Marketing floating chat (Ask). Loaded on all /marketing/*.html pages.
 * Persists panel open state + conversation in sessionStorage for this tab only.
 */
(function () {
    'use strict';

    var STORAGE_OPEN = 'ps_marketing_chat_open';
    var STORAGE_BODY = 'ps_marketing_chat_body_html';

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
            encodeURIComponent('Hi PharmaSight — I have a question about the product.')
        );
    }

    function injectWidget() {
        if (document.getElementById('psChat')) return;
        document.body.insertAdjacentHTML(
            'beforeend',
            [
                '<div class="ps-chat" id="psChat" aria-live="polite">',
                '  <button class="ps-chat-fab" id="psChatFab" type="button" aria-haspopup="dialog" aria-controls="psChatPanel" aria-expanded="false">Ask</button>',
                '  <section class="ps-chat-panel" id="psChatPanel" role="dialog" aria-modal="false" aria-label="PharmaSight assistant" hidden>',
                '    <header class="ps-chat-header">',
                '      <div class="ps-chat-title">PharmaSight assistant</div>',
                '      <button class="ps-chat-close" id="psChatClose" type="button" aria-label="Close chat">&times;</button>',
                '    </header>',
                '    <div class="ps-chat-body" id="psChatBody">',
                '      <div class="ps-chat-msg ps-chat-msg--bot">',
                '        Hi! Ask me anything about pricing, setup, or what PharmaSight does. You can also pick a quick question below.',
                '      </div>',
                '      <div class="ps-chat-quick" id="psChatQuick">',
                '        <button type="button" class="ps-chat-chip" data-q="What does PharmaSight do?">What does it do?</button>',
                '        <button type="button" class="ps-chat-chip" data-q="How do I get started with PharmaSight?">Get started</button>',
                '        <button type="button" class="ps-chat-chip" data-q="How much does it cost?">Pricing</button>',
                '        <button type="button" class="ps-chat-chip" data-q="Can I use it for clinics or agrovets?">Clinic / Agrovet</button>',
                '      </div>',
                '    </div>',
                '    <form class="ps-chat-input" id="psChatForm">',
                '      <input id="psChatText" type="text" autocomplete="off" placeholder="Type your question…" aria-label="Your message">',
                '      <button class="btn btn-primary" type="submit">Send</button>',
                '    </form>',
                '    <div class="ps-chat-footer">',
                '      <a class="ps-chat-link" href="signup.html">Start using PharmaSight now</a>',
                '      <span class="ps-chat-dot">&middot;</span>',
                '      <a class="ps-chat-link" href="pricing.html">Pricing</a>',
                '      <span class="ps-chat-dot">&middot;</span>',
                '      <a class="ps-chat-link" href="help.html">Help</a>',
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
            "<a href='signup.html'>Start using PharmaSight now &rarr;</a>" +
            "<a href='" +
            wa +
            "' target='_blank' rel='noopener noreferrer'>Chat on WhatsApp</a>" +
            '</div>'
        );
    }

    function replyFor(question) {
        var q = qs(question);
        if (!q) return 'Ask me about pricing, setup, or what PharmaSight does.' + ctaLinksHtml();
        if (q.indexOf('price') >= 0 || q.indexOf('cost') >= 0 || q.indexOf('pricing') >= 0) {
            return (
                'PharmaSight pricing is straightforward and built for real pharmacy operations. The best way to judge fit is to try it with your own workflow—stock in, sales out, and margins visible immediately.' +
                ctaLinksHtml()
            );
        }
        if (
            q.indexOf('trial') >= 0 ||
            q.indexOf('demo') >= 0 ||
            q.indexOf('signup') >= 0 ||
            q.indexOf('sign up') >= 0
        ) {
            return (
                'You can start immediately — no setup stress. Create your account, log in, and begin tracking stock and sales right away. If you want help, message us and we’ll guide you.' +
                ctaLinksHtml()
            );
        }
        if (q.indexOf('clinic') >= 0 || q.indexOf('opd') >= 0) {
            return (
                'Yes—PharmaSight works well for clinics. You get clean stock control, fast billing flows, and real-time visibility so you don’t run out of essentials mid-day.' +
                ctaLinksHtml()
            );
        }
        if (q.indexOf('agro') >= 0 || q.indexOf('agrovet') >= 0 || q.indexOf('vet') >= 0) {
            return (
                'Yes—Agrovet SKUs work well. You’ll use the same inventory, sales, and purchases flows—optimized for fast counter work, clear costs, and reliable stock control.' +
                ctaLinksHtml()
            );
        }
        if (q.indexOf('what') >= 0 && (q.indexOf('do') >= 0 || q.indexOf('does') >= 0)) {
            return (
                'PharmaSight helps you run inventory, sales, purchases, and reporting with batch-aware stock, clear margins, and branch-friendly workflows—so you always know what you have and what you’re earning.' +
                ctaLinksHtml()
            );
        }
        if (
            q.indexOf('expiry') >= 0 ||
            q.indexOf('expiries') >= 0 ||
            q.indexOf('expire') >= 0 ||
            q.indexOf('expiration') >= 0 ||
            q.indexOf('batch') >= 0
        ) {
            return (
                'Yes — PharmaSight helps reduce expiries by tracking stock by batch and highlighting items that are close to expiry, so you can act early and avoid losses.' +
                ctaLinksHtml()
            );
        }
        if (q.indexOf('margin') >= 0 || q.indexOf('profit') >= 0) {
            return (
                'Yes—margins are visible while you price and sell, so you stop guessing profitability and can make confident pricing decisions.' +
                ctaLinksHtml()
            );
        }
        return (
            'I can help you quickly. Are you trying to solve:\n\n• Stock issues\n• Pricing / margins\n• Expiries\n• Sales tracking\n\nTell me which one, and I’ll show you exactly how PharmaSight helps.' +
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
        if (askBtn) askBtn.addEventListener('click', function () { openChat({ focus: true }); });

        if (quick) {
            quick.addEventListener('click', function (e) {
                var t = e && e.target;
                if (!t || !t.getAttribute) return;
                var qq = t.getAttribute('data-q');
                if (!qq) return;
                openChat({ focus: true });
                appendMsg(body, qq, true);
                appendMsg(body, replyFor(qq), false, true);
            });
        }

        if (form) {
            form.addEventListener('submit', function (e) {
                e.preventDefault();
                var txt = input ? input.value : '';
                if (!String(txt || '').trim()) return;
                appendMsg(body, txt, true);
                if (input) input.value = '';
                appendMsg(body, replyFor(txt), false, true);
            });
        }

        document.addEventListener('keydown', function (e) {
            if (!panel || panel.hidden) return;
            if (e && e.key === 'Escape') closeChat();
        });

        try {
            window.addEventListener('pharmasight:site-settings', function () {
                persistSnapshot(body, panel);
            });
        } catch (_e3) {}
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
