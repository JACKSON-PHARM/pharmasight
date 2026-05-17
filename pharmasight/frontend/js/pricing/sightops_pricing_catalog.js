/**
 * SightOps Kenya pricing catalog — single source for admin UI, marketing, Stripe metadata hints.
 * Data: sightops_pricing_catalog.json (keep in sync when editing numbers).
 */

let _catalogPromise = null;

export async function loadPricingCatalog() {
    if (!_catalogPromise) {
        _catalogPromise = fetch('/js/pricing/sightops_pricing_catalog.json?v=2026-05-kenya')
            .then((r) => {
                if (!r.ok) throw new Error('Pricing catalog not found');
                return r.json();
            })
            .catch((e) => {
                console.warn('[pricing] catalog fetch failed, using embedded fallback', e);
                return _FALLBACK_CATALOG;
            });
    }
    return _catalogPromise;
}

export function formatKes(amount) {
    if (amount == null || amount === '') return '—';
    const n = Number(amount);
    if (Number.isNaN(n)) return String(amount);
    return `KES ${n.toLocaleString('en-KE', { maximumFractionDigits: 0 })}`;
}

export function tierBySlug(catalog, slug) {
    const s = (slug || '').trim().toLowerCase();
    if (!catalog || !Array.isArray(catalog.tiers)) return null;
    let t = catalog.tiers.find((x) => x.slug === s);
    if (t) return t;
    const alias = catalog.legacy_tier_aliases && catalog.legacy_tier_aliases[s];
    if (alias) return catalog.tiers.find((x) => x.slug === alias) || null;
    return null;
}

export function saasTiersFromCatalog(catalog) {
    return (catalog.tiers || []).map((t) => ({
        slug: t.slug,
        title: t.title,
        subtitle: t.subtitle,
        price: t.price_display || formatKes(t.kes_monthly),
        kes_monthly: t.kes_monthly,
        users: t.users,
        branches: t.branches,
        branch_credits: t.branch_credits,
        products: t.products,
        modules: t.modules_summary,
        default_operating_model: t.default_operating_model,
        default_hq_doctrine: t.default_hq_doctrine,
        stripe_metadata: t.stripe_metadata || {},
    }));
}

export function renderSeatCreditTableHtml(catalog, esc) {
    const e = esc || ((s) => String(s ?? ''));
    const sc = catalog.seat_credits || {};
    const rows = Object.keys(sc)
        .map((key) => {
            const row = sc[key];
            return `<tr>
                <td><strong>${e(row.label)}</strong><br><code style="font-size:0.75rem;">${e(key)}</code></td>
                <td style="text-align:center;">${e(String(row.credits))}</td>
                <td style="text-align:right;">${e(formatKes(row.kes_monthly_list))}</td>
                <td style="font-size:0.85rem;color:#475569;">${e(row.description)}</td>
            </tr>`;
        })
        .join('');
    return `
        <table class="pricing-seat-table" style="width:100%; border-collapse:collapse; font-size:0.88rem;">
            <thead>
                <tr style="background:#f1f5f9; text-align:left;">
                    <th style="padding:8px 10px;">Branch doctrine</th>
                    <th style="padding:8px 10px; text-align:center;">Seat credits</th>
                    <th style="padding:8px 10px; text-align:right;">List / month</th>
                    <th style="padding:8px 10px;">Notes</th>
                </tr>
            </thead>
            <tbody>${rows}</tbody>
        </table>
        <p style="margin:10px 0 0; font-size:0.82rem; color:#64748b;">
            Retail Solo list: <strong>${e(formatKes(catalog.retail_anchor_kes_monthly))}</strong>/mo · Retail Pro: <strong>${e(formatKes(catalog.retail_pro_anchor_kes_monthly || 2999))}</strong>/mo.
            Extra users: <strong>${e(formatKes(catalog.extra_user_kes_monthly))}</strong>/user/mo.
            <a href="/marketing/pricing-policy.html" target="_blank" rel="noopener">Pricing Policy</a> (customer-facing).
        </p>`;
}

function renderPackageTable(packages, e) {
    if (!packages || !packages.length) return '';
    const rows = packages
        .map((p) => `<tr><td>${e(p.title)}</td><td style="text-align:right;">${p.kes_once ? e(formatKes(p.kes_once)) : 'Free'}</td><td style="font-size:0.85rem;color:#475569;">${e(p.description || '')}</td></tr>`)
        .join('');
    return `<table style="width:100%;border-collapse:collapse;font-size:0.88rem;margin:8px 0;"><tbody>${rows}</tbody></table>`;
}

export function renderPricingPlaybookHtml(catalog, esc) {
    const e = esc || ((s) => String(s ?? ''));
    const solo = (catalog.retail_solo_includes || []).map((line) => `<li>${e(line)}</li>`).join('');
    const pro = (catalog.retail_pro_includes || []).map((line) => `<li>${e(line)}</li>`).join('');
    return `
        <section class="pricing-playbook" style="margin:16px 0; padding:16px; border:1px solid #e2e8f0; border-radius:12px; background:#f8fafc;">
            <h3 style="margin:0 0 8px 0;">Kenya pricing playbook (ops)</h3>
            <p style="margin:0 0 12px 0; color:#475569; font-size:0.9rem; line-height:1.45;">${e(catalog.positioning)}</p>
            <p style="margin:0 0 8px 0; font-size:0.88rem; color:#64748b;">${e(catalog.cloud_vs_desktop_note || '')}</p>
            <div style="display:grid; grid-template-columns: 1fr 1fr; gap:12px;">
                <div><h4 style="margin:0 0 6px;font-size:0.9rem;">Retail Solo (affordable)</h4><ul style="margin:0;padding-left:1.2rem;font-size:0.85rem;">${solo}</ul></div>
                <div><h4 style="margin:0 0 6px;font-size:0.9rem;">Retail Pro (full retail)</h4><ul style="margin:0;padding-left:1.2rem;font-size:0.85rem;">${pro}</ul></div>
            </div>
            <h4 style="margin:14px 0 6px;font-size:0.9rem;">Optional setup (once)</h4>
            ${renderPackageTable(catalog.setup_packages, e)}
            <h4 style="margin:14px 0 6px;font-size:0.9rem;">Optional training (once)</h4>
            ${renderPackageTable(catalog.training_packages, e)}
            ${renderSeatCreditTableHtml(catalog, e)}
            <details style="margin-top:12px;">
                <summary style="cursor:pointer; font-size:0.88rem; color:#475569;">Stripe metadata example (Retail Pro)</summary>
                <pre style="margin:8px 0 0; padding:10px; background:#fff; border:1px solid #e2e8f0; border-radius:8px; font-size:0.75rem; overflow:auto;">${e(JSON.stringify(
        (catalog.tiers || []).find((t) => t.slug === 'retail_pro')?.stripe_metadata || {},
        null,
        2,
    ))}</pre>
            </details>
        </section>`;
}

const _FALLBACK_CATALOG = {
    version: '2026-05-kenya',
    currency: 'KES',
    retail_anchor_kes_monthly: 1499,
    retail_pro_anchor_kes_monthly: 2999,
    extra_user_kes_monthly: 599,
    positioning: 'Cloud retail pharmacy; maintenance required.',
    seat_credits: {},
    retail_solo_includes: [],
    retail_pro_includes: [],
    setup_packages: [],
    training_packages: [],
    feature_matrix: [],
    tiers: [],
    legacy_tier_aliases: {},
};
