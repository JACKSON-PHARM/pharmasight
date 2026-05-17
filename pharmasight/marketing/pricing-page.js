/**
 * SightOps marketing pricing page — maintenance tiers, setup/training, feature matrix.
 */
import { loadPricingCatalog, formatKes } from '/js/pricing/sightops_pricing_catalog.js?v=2026-05-kenya';

function esc(s) {
    const d = document.createElement('div');
    d.textContent = s == null ? '' : String(s);
    return d.innerHTML;
}

function renderTierCard(t, featured) {
    const annual = t.kes_annual ? `<div class="pricing-tier-annual">or ${esc(formatKes(t.kes_annual))}/year (2 months free)</div>` : '';
    const badge = featured
        ? '<span class="badge badge-featured">Recommended</span>'
        : t.slug === 'retail_solo'
          ? '<span class="badge">Affordable</span>'
          : `<span class="badge">${esc(t.title.split(' ')[0])}</span>`;
    const caps = [
        t.users != null ? `${t.users} users included` : null,
        t.branches != null ? `${t.branches} branch${t.branches === 1 ? '' : 'es'}` : null,
        t.products != null ? `${Number(t.products).toLocaleString('en-KE')} products` : null,
    ].filter(Boolean);
    const cta =
        t.slug === 'retail_solo' || t.slug === 'retail_pro'
            ? '<p><a class="btn btn-primary" href="signup.html">Start free trial</a></p>'
            : t.slug === 'enterprise' || t.slug === 'health_network'
              ? '<p><a class="btn btn-secondary pricing-wa-cta" href="#">Talk to sales</a></p>'
              : t.slug === 'retail_growth'
                ? '<p><a class="btn btn-secondary pricing-wa-cta" href="#">Upgrade on WhatsApp</a></p>'
                : '';
    return `
        <div class="card pricing-tier${featured ? ' pricing-tier--featured' : ''}">
            ${badge}
            <h2>${esc(t.title)}</h2>
            <p class="pricing-tier-sub">${esc(t.subtitle)}</p>
            <p class="pricing-tier-price">${esc(t.price_display)}</p>
            ${annual}
            <p class="pricing-tier-maint-label"><strong>Maintenance</strong> (cloud hosting &amp; updates)</p>
            <ul class="pricing-tier-caps">${caps.map((c) => `<li>${esc(c)}</li>`).join('')}</ul>
            <p class="pricing-tier-modules">${esc(t.modules_summary)}</p>
            ${cta}
        </div>`;
}

function renderFeatureMatrix(catalog) {
    const rows = catalog.feature_matrix || [];
    const body = rows
        .map((r) => {
            const solo = r.solo === true ? '✓' : r.solo === false ? '—' : esc(String(r.solo));
            const pro = r.pro === true ? '✓' : r.pro === false ? '—' : esc(String(r.pro));
            return `<tr><td>${esc(r.feature)}</td><td style="text-align:center;">${solo}</td><td style="text-align:center;">${pro}</td></tr>`;
        })
        .join('');
    return `
        <section style="margin-top:3rem;">
            <h2>Retail Solo vs Retail Pro</h2>
            <p style="color:var(--muted); max-width:42rem;">Solo keeps SightOps usable and affordable; Pro unlocks the full retail capability we reserve for paying customers. Both require <strong>monthly maintenance</strong> — we are cloud-based, not a one-time desktop licence.</p>
            <table class="pricing-doctrine-table" style="max-width:40rem;">
                <thead><tr><th>Capability</th><th>Solo</th><th>Pro</th></tr></thead>
                <tbody>${body}</tbody>
            </table>
        </section>`;
}

function renderOnceFees(catalog) {
    const setup = (catalog.setup_packages || [])
        .map((p) => `<li><strong>${esc(p.title)}</strong> — ${p.kes_once ? esc(formatKes(p.kes_once)) : 'Free'} <span style="color:var(--muted);">${esc(p.description)}</span></li>`)
        .join('');
    const train = (catalog.training_packages || [])
        .map((p) => `<li><strong>${esc(p.title)}</strong> — ${esc(formatKes(p.kes_once))}</li>`)
        .join('');
    return `
        <section style="margin-top:2.5rem; padding:1.25rem; border:1px solid var(--border,#e2e8f0); border-radius:12px;">
            <h2 style="margin-top:0;">Optional one-time fees (not a substitute for maintenance)</h2>
            <p style="color:var(--muted);">Unlike offline POS sold once per PC, SightOps needs ongoing maintenance for servers and updates. Setup and training are optional extras.</p>
            <h3 style="font-size:1rem;">Setup</h3>
            <ul style="line-height:1.5;">${setup}</ul>
            <h3 style="font-size:1rem;">Training</h3>
            <ul style="line-height:1.5;">${train}</ul>
        </section>`;
}

function renderRetailIncludes(catalog) {
    const items = (catalog.retail_solo_includes || []).map((line) => `<li>${esc(line)}</li>`).join('');
    return `
        <section class="pricing-retail-includes" style="margin-top:2rem;">
            <h2>Built for the Kenyan small pharmacy</h2>
            <p style="color:var(--muted);">Buy, sell, receive stock, adjust inventory, manage users, and watch expiries — on maintenance from <strong>${esc(formatKes(catalog.retail_anchor_kes_monthly))}/month</strong> (Solo).</p>
            <ul style="line-height:1.5;">${items}</ul>
        </section>`;
}

export async function initPricingPage() {
    const grid = document.getElementById('pricing-tier-grid');
    const extra = document.getElementById('pricing-extra-sections');
    if (!grid) return;

    const catalog = await loadPricingCatalog();
    const tiers = (catalog.tiers || []).filter((t) => t.slug !== 'demo');

    grid.innerHTML = tiers.map((t) => renderTierCard(t, t.featured === true)).join('');

    if (extra) {
        extra.innerHTML =
            renderRetailIncludes(catalog) +
            renderFeatureMatrix(catalog) +
            renderOnceFees(catalog);
    }

    const policyLink = document.getElementById('pricing-policy-link');
    if (policyLink && catalog.policy_url) policyLink.href = catalog.policy_url;

    try {
        const cfg = window.MARKETING_CONFIG || {};
        const wa = 'https://wa.me/' + (cfg.WHATSAPP_E164 || '254700000000') + '?text=';
        document.querySelectorAll('.pricing-wa-cta').forEach((el) => {
            el.href = wa + encodeURIComponent('Hi — I would like SightOps pricing for my pharmacy.');
        });
    } catch (_) {}
}

initPricingPage().catch((e) => console.error('[pricing-page]', e));
