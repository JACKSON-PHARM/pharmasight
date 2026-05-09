;(function () {
  function esc(v) {
    const d = document.createElement('div');
    d.textContent = String(v ?? '');
    return d.innerHTML;
  }

  async function loadBillingInsurance() {
    const el = document.getElementById('module-coming-soon');
    if (!el) return;
    el.innerHTML = `
      <div class="card" style="padding:1rem;">
        <h2 style="margin-top:0;">Insurance Management</h2>
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:0.75rem;margin-bottom:1rem;">
          <input id="insName" class="form-input" placeholder="Provider name" />
          <input id="insCode" class="form-input" placeholder="Code" />
          <input id="insTerms" class="form-input" type="number" min="0" placeholder="Terms days (30)" />
          <button id="insCreateBtn" class="btn btn-primary">Add Provider</button>
        </div>
        <div id="insProvidersWrap"></div>
        <hr style="margin:1rem 0;" />
        <h3>Claims / Receivables</h3>
        <div id="insClaimsWrap"></div>
        <hr style="margin:1rem 0;" />
        <h3>Settlements</h3>
        <div id="insSettlementsWrap"></div>
        <hr style="margin:1rem 0;" />
        <h3>Aging</h3>
        <div id="insAgingWrap"></div>
      </div>
    `;

    async function refreshAll() {
      const [providers, claims, settlements, aging] = await Promise.all([
        API.insurance.listProviders(false),
        API.insurance.listClaims({}),
        API.insurance.listSettlements({}),
        API.insurance.getAging(),
      ]);
      document.getElementById('insProvidersWrap').innerHTML =
        (providers || []).length === 0 ? '<div class="text-muted">No providers yet.</div>' :
        `<table class="table"><thead><tr><th>Name</th><th>Code</th><th>Terms</th><th>Status</th></tr></thead><tbody>${
          providers.map((p) => `<tr><td>${esc(p.name)}</td><td>${esc(p.code)}</td><td>${esc(p.terms_days)}</td><td>${p.is_active ? 'Active' : 'Inactive'}</td></tr>`).join('')
        }</tbody></table>`;
      document.getElementById('insClaimsWrap').innerHTML =
        (claims || []).length === 0 ? '<div class="text-muted">No claims yet.</div>' :
        `<table class="table"><thead><tr><th>Claim #</th><th>Status</th><th>Billed</th><th>Outstanding</th></tr></thead><tbody>${
          claims.map((c) => `<tr><td>${esc(c.claim_number)}</td><td>${esc(c.status)}</td><td>${esc(c.billed_amount)}</td><td>${esc(c.outstanding_amount)}</td></tr>`).join('')
        }</tbody></table>`;
      document.getElementById('insSettlementsWrap').innerHTML =
        (settlements || []).length === 0 ? '<div class="text-muted">No settlements yet.</div>' :
        `<table class="table"><thead><tr><th>Settlement #</th><th>Date</th><th>Amount</th><th>Method</th></tr></thead><tbody>${
          settlements.map((s) => `<tr><td>${esc(s.settlement_number)}</td><td>${esc(s.settlement_date)}</td><td>${esc(s.amount)}</td><td>${esc(s.method)}</td></tr>`).join('')
        }</tbody></table>`;
      document.getElementById('insAgingWrap').innerHTML =
        (aging || []).length === 0 ? '<div class="text-muted">No aging balances.</div>' :
        `<table class="table"><thead><tr><th>Provider</th><th>Current</th><th>31-60</th><th>61-90</th><th>91+</th><th>Total</th></tr></thead><tbody>${
          aging.map((a) => `<tr><td>${esc(a.provider_name)}</td><td>${esc(a.current)}</td><td>${esc(a.days_31_60)}</td><td>${esc(a.days_61_90)}</td><td>${esc(a.days_91_plus)}</td><td>${esc(a.total)}</td></tr>`).join('')
        }</tbody></table>`;
    }

    document.getElementById('insCreateBtn')?.addEventListener('click', async () => {
      try {
        const name = (document.getElementById('insName')?.value || '').trim();
        const code = (document.getElementById('insCode')?.value || '').trim();
        const terms = Number(document.getElementById('insTerms')?.value || 30);
        if (!name || !code) throw new Error('Name and code are required');
        await API.insurance.createProvider({ name, code, terms_days: terms, is_active: true });
        if (typeof window.showToast === 'function') window.showToast('Insurance provider created', 'success');
        await refreshAll();
      } catch (e) {
        if (typeof window.showToast === 'function') window.showToast(e.message || 'Failed to create provider', 'error');
      }
    });

    try {
      await refreshAll();
    } catch (e) {
      if (typeof window.showToast === 'function') window.showToast(e.message || 'Failed to load insurance data', 'error');
    }
  }

  window.loadBillingInsurance = loadBillingInsurance;
})();
