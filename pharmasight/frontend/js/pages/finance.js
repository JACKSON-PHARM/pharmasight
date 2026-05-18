// Finance Operations — operational intelligence + governance tools

const FINANCE_INTEL_SUBPAGES = {
    confidence: { title: 'Financial Confidence', loader: 'renderFinanceConfidence' },
    treasury: { title: 'Treasury Intelligence', loader: 'renderFinanceReconciliation' },
    recovery: { title: 'Revenue Recovery & Exposure', loader: 'renderFinanceRecovery' },
};

const FINANCE_GOV_SUBPAGES = {
    events: { title: 'Event Explorer', loader: 'renderFinanceEvents' },
    projections: { title: 'Projection Explorer', loader: 'renderFinanceProjections' },
    proposals: { title: 'Accounting interpretations', loader: 'renderFinanceProposals' },
    integrity: { title: 'Replay & Integrity', loader: 'renderFinanceIntegrity' },
};

const FINANCE_OPS_SUBPAGES = { ...FINANCE_INTEL_SUBPAGES, ...FINANCE_GOV_SUBPAGES };

async function loadFinance(subPage) {
    const page = document.getElementById('finance');
    if (!page) return;

    const key = subPage && FINANCE_OPS_SUBPAGES[subPage] ? subPage : 'confidence';
    const meta = FINANCE_OPS_SUBPAGES[key];

    page.innerHTML = `
        <div id="financeContent" style="max-width:1200px;">
            <p style="opacity:0.7;">Loading ${meta.title}…</p>
        </div>`;

    const loader = typeof window[meta.loader] === 'function' ? window[meta.loader] : null;
    if (!loader) {
        const root = document.getElementById('financeContent');
        if (root) {
            root.innerHTML =
                '<div class="card"><div class="card-body"><p>Finance module failed to load. Refresh the page.</p></div></div>';
        }
        return;
    }
    await loader();
}

window.loadFinance = loadFinance;
window.FINANCE_INTEL_SUBPAGES = FINANCE_INTEL_SUBPAGES;
window.FINANCE_GOV_SUBPAGES = FINANCE_GOV_SUBPAGES;
