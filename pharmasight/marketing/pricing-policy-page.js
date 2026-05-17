import { loadPricingCatalog, formatKes } from '/js/pricing/sightops_pricing_catalog.js?v=2026-05-kenya';

function esc(s) {
    const d = document.createElement('div');
    d.textContent = s == null ? '' : String(s);
    return d.innerHTML;
}

async function init() {
    const catalog = await loadPricingCatalog();
    const ver = document.getElementById('policy-version');
    if (ver && catalog.version) ver.textContent = catalog.version;

    const tierBody = document.querySelector('#policy-tier-table tbody');
    if (tierBody) {
        const rows = (catalog.tiers || [])
            .filter((t) => t.tier_kind === 'maintenance' && t.kes_monthly != null)
            .map(
                (t) =>
                    `<tr><td>${esc(t.title)}</td><td>${esc(t.price_display)}</td><td>${esc(t.subtitle)}</td></tr>`,
            )
            .join('');
        tierBody.innerHTML = rows || '<tr><td colspan="3">See pricing page</td></tr>';
    }

    const setupBody = document.querySelector('#policy-setup-table tbody');
    if (setupBody) {
        setupBody.innerHTML = (catalog.setup_packages || [])
            .map((p) => `<tr><td>${esc(p.title)}</td><td>${p.kes_once ? esc(formatKes(p.kes_once)) : 'Free'}</td></tr>`)
            .join('');
    }

    const trainBody = document.querySelector('#policy-training-table tbody');
    if (trainBody) {
        trainBody.innerHTML = (catalog.training_packages || [])
            .map((p) => `<tr><td>${esc(p.title)}</td><td>${esc(formatKes(p.kes_once))}</td></tr>`)
            .join('');
    }
}

init().catch(console.error);
