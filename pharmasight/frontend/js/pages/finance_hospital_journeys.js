/**
 * Hospital Economic Kernel UI — Patient Financial Journey workspace (E2E testing).
 */
async function renderFinanceHospitalJourneys() {
    const FO = window.FinanceOps;
    const root = document.getElementById('financeContent');
    if (!root || !FO) return;
    let selectedPatientId = null;

    root.innerHTML = `
        <div class="fcc-scope">
            <div class="fcc-hero">
                <h2><i class="fas fa-heartbeat"></i> Patient Financial Journeys</h2>
                <p>Longitudinal hospital economics: care charges → liability split → authorization → recognition → claims. Not invoice-centric.</p>
            </div>
            <div class="card" style="padding:1rem;margin-bottom:1rem;">
                <label class="form-label">Find patient</label>
                <div style="display:flex;gap:0.5rem;flex-wrap:wrap;">
                    <input type="text" id="hejPatientSearch" class="form-input" placeholder="Name or phone…" style="flex:1;min-width:200px;">
                    <button type="button" class="btn btn-primary" id="hejSearchBtn"><i class="fas fa-search"></i> Search</button>
                </div>
                <div id="hejPatientResults" style="margin-top:0.75rem;"></div>
            </div>
            <div id="hejWorkspace"><p style="opacity:0.7;">Search and select a patient to open their financial journey.</p></div>
        </div>`;

    const searchBtn = document.getElementById('hejSearchBtn');
    const searchInput = document.getElementById('hejPatientSearch');
    searchBtn?.addEventListener('click', () => searchPatients());
    searchInput?.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') searchPatients();
    });

    const hashRaw = (window.location.hash || '').replace('#', '');
    const hashQuery = hashRaw.includes('?') ? hashRaw.split('?').slice(1).join('?') : '';
    const params = new URLSearchParams(hashQuery);
    const patientId = params.get('patient_id');
    if (patientId) {
        selectedPatientId = patientId;
        loadWorkspace(patientId);
    }

    async function searchPatients() {
        const out = document.getElementById('hejPatientResults');
        const q = (searchInput?.value || '').trim();
        if (!out || !q) return;
        out.innerHTML = '<p style="opacity:0.7;">Searching…</p>';
        try {
            const rows = await API.clinic.patients.list(q);
            if (!rows?.length) {
                out.innerHTML = '<p style="opacity:0.7;">No patients found.</p>';
                return;
            }
            out.innerHTML = rows
                .slice(0, 20)
                .map(
                    (p) => `<button type="button" class="btn btn-outline btn-sm" style="margin:0.25rem;" data-pid="${FO.escapeHtml(p.id)}">
                        ${FO.escapeHtml((p.first_name || '') + ' ' + (p.last_name || ''))} ${p.phone ? '· ' + FO.escapeHtml(p.phone) : ''}
                    </button>`
                )
                .join('');
            out.querySelectorAll('[data-pid]').forEach((btn) => {
                btn.addEventListener('click', () => {
                    selectedPatientId = btn.getAttribute('data-pid');
                    loadWorkspace(selectedPatientId);
                    if (selectedPatientId) {
                        window.location.hash = `finance-patient-journeys?patient_id=${encodeURIComponent(selectedPatientId)}`;
                    }
                });
            });
        } catch (err) {
            FO.showError(out, err);
        }
    }

    async function loadWorkspace(patientId) {
        const ws = document.getElementById('hejWorkspace');
        if (!ws || !API?.hospitalEconomic) return;
        ws.innerHTML = '<p style="opacity:0.7;">Loading workspace…</p>';
        try {
            const data = await API.hospitalEconomic.patientWorkspace(patientId);
            renderWorkspace(ws, data, patientId);
        } catch (err) {
            FO.showError(ws, err);
        }
    }

    function renderWorkspace(ws, data, patientId) {
        const p = data.patient;
        const pfj = data.pfj;
        if (!pfj) {
            ws.innerHTML = `<p>No financial journey for <strong>${FO.escapeHtml(p.first_name)} ${FO.escapeHtml(p.last_name)}</strong>. Create an OPD encounter first (Reception / Clinic).</p>`;
            return;
        }
        const pfjId = pfj.id;
        const cov = data.coverage || {};
        const sum = data.liability_summary || {};
        const timeline = data.timeline || [];

        ws.innerHTML = `
            <div class="card" style="padding:1rem;margin-bottom:1rem;">
                <h3 style="margin:0 0 0.5rem;">${FO.escapeHtml(p.first_name)} ${FO.escapeHtml(p.last_name)}</h3>
                <p style="margin:0;color:var(--text-secondary);font-size:0.875rem;">
                    PFJ <code>${FO.escapeHtml(pfjId)}</code> · status <strong>${FO.escapeHtml(pfj.status)}</strong>
                    · opened ${FO.fmtDateTime(pfj.opened_at)}
                </p>
                <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:0.75rem;margin-top:1rem;">
                    <div class="fcc-metric"><span class="fcc-metric-label">Patient</span><span class="fcc-metric-value">${FO.fmtMoney(sum.patient)}</span></div>
                    <div class="fcc-metric"><span class="fcc-metric-label">Insurer</span><span class="fcc-metric-value">${FO.fmtMoney(sum.insurer)}</span></div>
                    <div class="fcc-metric"><span class="fcc-metric-label">Pending auth</span><span class="fcc-metric-value">${FO.fmtMoney(data.pending_authorization)}</span></div>
                    <div class="fcc-metric"><span class="fcc-metric-label">Recognitions</span><span class="fcc-metric-value">${data.recognitions_count || 0}</span></div>
                </div>
            </div>

            <div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin-bottom:1rem;">
                <div class="card" style="padding:1rem;">
                    <h4>Coverage</h4>
                    <select id="hejObligorRoute" class="form-input" style="margin-bottom:0.5rem;">
                        <option value="self_pay" ${cov.obligor_route === 'self_pay' ? 'selected' : ''}>Self pay</option>
                        <option value="insurance" ${cov.obligor_route === 'insurance' ? 'selected' : ''}>Insurance</option>
                        <option value="employer" ${cov.obligor_route === 'employer' ? 'selected' : ''}>Employer</option>
                    </select>
                    <input id="hejInsurerPct" class="form-input" type="number" placeholder="Insurer %" value="${cov.insurer_coverage_percent || '80'}" style="margin-bottom:0.5rem;">
                    <select id="hejProviderId" class="form-input" style="margin-bottom:0.5rem;"><option value="">Insurance provider…</option></select>
                    <button type="button" class="btn btn-outline btn-sm" id="hejSaveCoverage">Save coverage</button>
                </div>
                <div class="card" style="padding:1rem;">
                    <h4>Actions</h4>
                    <div style="display:flex;flex-wrap:wrap;gap:0.5rem;">
                        <button type="button" class="btn btn-outline btn-sm" id="hejReqAuth">Request authorization</button>
                        <button type="button" class="btn btn-outline btn-sm" id="hejRecPatient">Recognize patient AR</button>
                        <button type="button" class="btn btn-outline btn-sm" id="hejRecInsurer">Recognize insurer AR</button>
                        <button type="button" class="btn btn-outline btn-sm" id="hejBuildClaim">Build insurance claim</button>
                        <button type="button" class="btn btn-secondary btn-sm" id="hejDischarge">Discharge / close PFJ</button>
                    </div>
                </div>
            </div>

            <div class="card" style="padding:1rem;margin-bottom:1rem;">
                <h4>PFJ timeline</h4>
                <div id="hejTimeline">${renderTimeline(timeline)}</div>
            </div>

            <div class="card" style="padding:1rem;margin-bottom:1rem;">
                <h4>Care charges & liability</h4>
                ${renderCharges(data.charges || [])}
            </div>

            <div class="card" style="padding:1rem;">
                <h4>Authorizations</h4>
                ${renderAuths(data.authorizations || [])}
            </div>`;

        loadProviders(cov.insurance_provider_id);
        bindActions(pfjId, sum, patientId);
    }

    function renderTimeline(events) {
        if (!events.length) return '<p style="opacity:0.7;">No events yet.</p>';
        return `<ul style="list-style:none;padding:0;margin:0;border-left:2px solid var(--border-color);">
            ${events
                .map(
                    (e) => `<li style="padding:0.5rem 0 0.5rem 1rem;position:relative;">
                <span style="position:absolute;left:-5px;top:0.75rem;width:8px;height:8px;border-radius:50%;background:var(--primary);"></span>
                <div style="font-size:0.8rem;color:var(--text-secondary);">${FO.fmtDateTime(e.at)} · ${FO.escapeHtml(e.kind)}</div>
                <div>${FO.escapeHtml(e.summary || '')} ${e.amount_inclusive ? '<strong>' + FO.fmtMoney(e.amount_inclusive) + '</strong>' : ''}</div>
            </li>`
                )
                .join('')}
        </ul>`;
    }

    function renderCharges(charges) {
        if (!charges.length) return '<p style="opacity:0.7;">No care charges — create an encounter and services in Clinic.</p>';
        return `<table class="fcc-table"><thead><tr><th>When</th><th>Kind</th><th>Description</th><th class="num">Amount</th><th>Liability</th></tr></thead><tbody>
            ${charges
                .map(
                    (c) => `<tr>
                <td>${FO.fmtDateTime(c.accrued_at)}</td>
                <td>${FO.escapeHtml(c.charge_kind)}</td>
                <td>${FO.escapeHtml(c.description)}</td>
                <td class="num">${FO.fmtMoney(c.amount_inclusive)}</td>
                <td>${(c.liability || []).map((l) => `${FO.escapeHtml(l.obligor_type)} ${FO.fmtMoney(l.amount_inclusive)} <em>(${FO.escapeHtml(l.line_kind)})</em>`).join('<br>') || '—'}</td>
            </tr>`
                )
                .join('')}
        </tbody></table>`;
    }

    function renderAuths(auths) {
        if (!auths.length) return '<p style="opacity:0.7;">No authorizations.</p>';
        return `<table class="fcc-table"><thead><tr><th>When</th><th>Status</th><th class="num">Requested</th><th class="num">Approved</th><th></th></tr></thead><tbody>
            ${auths
                .map(
                    (a) => `<tr>
                <td>${FO.fmtDateTime(a.created_at)}</td>
                <td>${FO.escapeHtml(a.status)}</td>
                <td class="num">${FO.fmtMoney(a.requested_amount)}</td>
                <td class="num">${FO.fmtMoney(a.approved_amount)}</td>
                <td>${a.status === 'requested' ? `<button type="button" class="btn btn-outline btn-sm hej-approve" data-aid="${FO.escapeHtml(a.id)}">Approve</button>` : ''}</td>
            </tr>`
                )
                .join('')}
        </tbody></table>`;
    }

    async function loadProviders(selectedId) {
        const sel = document.getElementById('hejProviderId');
        if (!sel || !API?.insurance?.listProviders) return;
        try {
            const providers = await API.insurance.listProviders(true);
            sel.innerHTML =
                '<option value="">Insurance provider…</option>' +
                (providers || [])
                    .map(
                        (pr) =>
                            `<option value="${FO.escapeHtml(pr.id)}" ${pr.id === selectedId ? 'selected' : ''}>${FO.escapeHtml(pr.name)}</option>`
                    )
                    .join('');
        } catch (_) {
            /* optional */
        }
    }

    function bindActions(pfjId, sum, patientId) {
        document.getElementById('hejSaveCoverage')?.addEventListener('click', async () => {
            try {
                await API.hospitalEconomic.upsertCoverage(pfjId, {
                    obligor_route: document.getElementById('hejObligorRoute')?.value,
                    insurer_coverage_percent: parseFloat(document.getElementById('hejInsurerPct')?.value || '80'),
                    insurance_provider_id: document.getElementById('hejProviderId')?.value || null,
                });
                showToast('Coverage saved — re-allocating liability…', 'success');
                if (patientId) loadWorkspace(patientId);
            } catch (e) {
                showToast(e.message || 'Failed', 'error');
            }
        });

        const pid = () => patientId || selectedPatientId;

        document.getElementById('hejReqAuth')?.addEventListener('click', async () => {
            try {
                await API.hospitalEconomic.requestAuthorization(pfjId, {
                    requested_amount: parseFloat(sum.insurer || sum.total || 0) || 1000,
                    insurance_provider_id: document.getElementById('hejProviderId')?.value || null,
                });
                showToast('Authorization requested', 'success');
                const p = pid();
                if (p) loadWorkspace(p);
            } catch (e) {
                showToast(e.message || 'Failed', 'error');
            }
        });

        document.querySelectorAll('.hej-approve').forEach((btn) => {
            btn.addEventListener('click', async () => {
                try {
                    await API.hospitalEconomic.decideAuthorization(btn.getAttribute('data-aid'), {
                        status: 'approved',
                    });
                    showToast('Approved', 'success');
                    const p = pid();
                    if (p) loadWorkspace(p);
                } catch (e) {
                    showToast(e.message || 'Failed', 'error');
                }
            });
        });

        document.getElementById('hejRecPatient')?.addEventListener('click', async () => {
            try {
                const r = await API.hospitalEconomic.recognizePatient(pfjId);
                showToast(`Recognized ${r.recognized_count} patient slice(s)`, 'success');
                const p = pid();
                if (p) loadWorkspace(p);
            } catch (e) {
                showToast(e.message || 'Failed', 'error');
            }
        });

        document.getElementById('hejRecInsurer')?.addEventListener('click', async () => {
            try {
                const r = await API.hospitalEconomic.recognizeInsurer(pfjId);
                showToast(`Recognized ${r.recognized_count} insurer slice(s)`, 'success');
                const p = pid();
                if (p) loadWorkspace(p);
            } catch (e) {
                showToast(e.message || 'Failed', 'error');
            }
        });

        document.getElementById('hejBuildClaim')?.addEventListener('click', async () => {
            try {
                const r = await API.hospitalEconomic.buildClaim(pfjId, {
                    insurance_provider_id: document.getElementById('hejProviderId')?.value || null,
                });
                showToast(`Claim ${r.claim_number} created`, 'success');
            } catch (e) {
                showToast(e.message || 'Failed', 'error');
            }
        });

        document.getElementById('hejDischarge')?.addEventListener('click', async () => {
            if (!confirm('Close this patient financial journey?')) return;
            try {
                const r = await API.hospitalEconomic.discharge(pfjId, {});
                showToast(`PFJ closed. Patient residual: ${r.patient_residual}`, 'success');
                const p = pid();
                if (p) loadWorkspace(p);
            } catch (e) {
                showToast(e.message || 'Failed', 'error');
            }
        });

    }
}

window.renderFinanceHospitalJourneys = renderFinanceHospitalJourneys;
