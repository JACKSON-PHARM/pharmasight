/**
 * OPD UI: patients list/create, encounter queue, consultation (notes + orders).
 * Requires clinic module (backend 403 otherwise).
 */
(function () {
    function branchId() {
        return (typeof CONFIG !== 'undefined' && CONFIG.BRANCH_ID) || null;
    }

    function showErr(msg) {
        if (typeof window.showToast === 'function') window.showToast(msg, 'error');
        else alert(msg);
    }

    function setButtonsDisabled(container, disabled) {
        if (!container) return;
        container.querySelectorAll('button').forEach(function (b) {
            b.disabled = !!disabled;
        });
    }

    async function loadClinicPatients() {
        const el = document.getElementById('patients');
        if (!el) return;
        el.innerHTML = '<div class="card" style="padding:1rem;"><p>Loading patients…</p></div>';
        try {
            const list = await API.clinic.patients.list();
            const rows = (Array.isArray(list) ? list : [])
                .map(
                    (p) =>
                        `<tr><td>${escapeHtml(p.first_name || '')} ${escapeHtml(p.last_name || '')}</td><td>${escapeHtml(p.phone || '—')}</td><td><button type="button" class="btn btn-sm btn-outline" data-pid="${p.id}">Start visit</button></td></tr>`
                )
                .join('');
            el.innerHTML = `
                <div class="card" style="padding:1rem;">
                    <h2>Patients</h2>
                    <div style="display:flex; flex-wrap:wrap; gap:1rem; margin-bottom:1rem; align-items:flex-end;">
                        <div><label>First name</label><input type="text" id="clinicPtFirst" class="form-input" /></div>
                        <div><label>Last name</label><input type="text" id="clinicPtLast" class="form-input" /></div>
                        <div><label>Phone</label><input type="text" id="clinicPtPhone" class="form-input" /></div>
                        <div><label>Gender</label>
                            <select id="clinicPtGender" class="form-input">
                                <option value="">—</option>
                                <option value="female">Female</option>
                                <option value="male">Male</option>
                                <option value="other">Other</option>
                            </select>
                        </div>
                        <div><label>Date of birth</label><input type="date" id="clinicPtDob" class="form-input" /></div>
                        <button type="button" class="btn btn-primary" id="clinicPtSave">Save patient</button>
                    </div>
                    <table class="data-table" style="width:100%;"><thead><tr><th>Name</th><th>Phone</th><th></th></tr></thead><tbody>${rows || '<tr><td colspan="3">No patients</td></tr>'}</tbody></table>
                </div>`;
            const card = el.querySelector('.card');
            document.getElementById('clinicPtSave')?.addEventListener('click', async () => {
                const btn = document.getElementById('clinicPtSave');
                const first_name = (document.getElementById('clinicPtFirst')?.value || '').trim();
                const last_name = (document.getElementById('clinicPtLast')?.value || '').trim();
                const phone = (document.getElementById('clinicPtPhone')?.value || '').trim() || null;
                const gender = (document.getElementById('clinicPtGender')?.value || '').trim() || null;
                const date_of_birth = (document.getElementById('clinicPtDob')?.value || '').trim() || null;
                if (btn) btn.disabled = true;
                setButtonsDisabled(card, true);
                try {
                    await API.clinic.patients.create({ first_name, last_name, phone, gender, date_of_birth });
                    if (typeof window.showToast === 'function') window.showToast('Patient saved', 'success');
                    await loadClinicPatients();
                } catch (e) {
                    showErr(e.message || 'Failed to save patient');
                    setButtonsDisabled(card, false);
                    if (btn) btn.disabled = false;
                }
            });
            el.querySelectorAll('[data-pid]').forEach((btn) => {
                btn.addEventListener('click', async () => {
                    const pid = btn.getAttribute('data-pid');
                    const bid = branchId();
                    if (!bid) {
                        showErr('Select a branch first');
                        return;
                    }
                    if (btn.disabled) return;
                    btn.disabled = true;
                    try {
                        await API.clinic.encounters.create({ patient_id: pid, branch_id: bid });
                        if (typeof window.showToast === 'function') window.showToast('Visit started', 'success');
                        window.location.hash = '#encounters';
                        if (typeof window.loadPage === 'function') await window.loadPage('encounters');
                        else await loadClinicEncounters();
                    } catch (e) {
                        showErr(e.message || 'Could not start encounter');
                        btn.disabled = false;
                    }
                });
            });
        } catch (e) {
            el.innerHTML = `<div class="card" style="padding:1rem;"><p class="text-danger">Could not load patients. ${escapeHtml(e.message || '')}</p></div>`;
        }
    }

    function escapeHtml(s) {
        const d = document.createElement('div');
        d.textContent = s;
        return d.innerHTML;
    }

    function emptyRowForColumn(title) {
        if (title === 'Waiting') return '<tr><td colspan="3">No visits waiting</td></tr>';
        if (title === 'In consultation') return '<tr><td colspan="3">No active visits</td></tr>';
        if (title === 'Completed') return '<tr><td colspan="3">No completed visits</td></tr>';
        return '<tr><td colspan="3">None</td></tr>';
    }

    async function loadClinicEncounters() {
        const el = document.getElementById('encounters');
        if (!el) return;
        el.innerHTML = '<div class="card" style="padding:1rem;"><p>Loading queue…</p></div>';
        try {
            const [waiting, active, done] = await Promise.all([
                API.clinic.encounters.list('waiting'),
                API.clinic.encounters.list('in_consultation'),
                API.clinic.encounters.list('completed'),
            ]);
            let filter = '';
            const normalize = (s) => String(s || '').toLowerCase();
            const matches = (enc) => {
                if (!filter) return true;
                const p = enc && enc.patient ? enc.patient : {};
                const hay = [
                    enc?.id,
                    enc?.status,
                    p?.first_name,
                    p?.last_name,
                    p?.phone,
                ]
                    .map(normalize)
                    .join(' ');
                return hay.includes(filter);
            };
            const render = () => {
                const col = (title, arr) => {
                    const body = (Array.isArray(arr) ? arr : [])
                        .filter(matches)
                        .map((x) => {
                            const p = x.patient || {};
                            const pname = `${p.first_name || ''} ${p.last_name || ''}`.trim() || '—';
                            const pphone = p.phone || '—';
                            const openTarget = x.status === 'waiting' ? 'triage' : 'consultation';
                            return `<tr>
                                <td><strong>${escapeHtml(pname)}</strong><div style="font-size:0.8rem; color:var(--text-secondary);">${escapeHtml(pphone)}</div></td>
                                <td><span class="badge badge-info" style="font-size:0.75rem;">${escapeHtml(x.status)}</span></td>
                                <td><button type="button" class="btn btn-sm btn-primary" data-eid="${x.id}" data-open="${openTarget}">Open</button></td>
                            </tr>`;
                        })
                        .join('');
                    return `<div class="card" style="padding:0.75rem; flex:1; min-width:260px;"><h3 style="margin:0 0 0.5rem;">${title}</h3><table class="data-table" style="width:100%;"><tbody>${body || emptyRowForColumn(title)}</tbody></table></div>`;
                };
                el.innerHTML = `
                    <div style="padding:0.5rem;">
                        <h2>Encounter queue</h2>
                        <div style="display:flex; gap:0.75rem; align-items:flex-end; flex-wrap:wrap; margin-bottom:0.75rem;">
                            <div style="flex:1; min-width:260px;">
                                <label>Search patient (name / phone)</label>
                                <input type="text" id="clinicQueueSearch" class="form-input" placeholder="Type to filter…" value="${escapeHtml(filter)}" />
                            </div>
                        </div>
                        <div style="display:flex; flex-wrap:wrap; gap:0.75rem;">
                            ${col('Waiting', waiting)}
                            ${col('In consultation', active)}
                            ${col('Completed', done)}
                        </div>
                    </div>`;
                document.getElementById('clinicQueueSearch')?.addEventListener('input', (e) => {
                    filter = normalize(e.target.value || '').trim();
                    render();
                });
                el.querySelectorAll('[data-eid]').forEach((btn) => {
                    btn.addEventListener('click', () => {
                        const id = btn.getAttribute('data-eid');
                        const openTarget = btn.getAttribute('data-open') || 'consultation';
                        window.location.hash = `#${openTarget}?id=${encodeURIComponent(id)}`;
                        if (typeof window.loadPage === 'function') void window.loadPage(openTarget);
                    });
                });
            };
            render();
        } catch (e) {
            el.innerHTML = `<div class="card" style="padding:1rem;"><p class="text-danger">Could not load encounters. ${escapeHtml(e.message || '')}</p></div>`;
        }
    }

    function newServiceLineItem(orderTypeLabel) {
        var uuid =
            typeof crypto !== 'undefined' && crypto.randomUUID
                ? crypto.randomUUID()
                : 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (c) {
                      var r = (Math.random() * 16) | 0;
                      var v = c === 'x' ? r : (r & 0x3) | 0x8;
                      return v.toString(16);
                  });
        return {
            reference_type: 'service',
            reference_id: uuid,
            quantity: 1,
            notes: orderTypeLabel,
        };
    }

    async function loadClinicConsultation() {
        const el = document.getElementById('consultation');
        if (!el) return;
        const params = new URLSearchParams(window.location.hash.split('?')[1] || '');
        const eid = params.get('id');
        if (!eid) {
            el.innerHTML = '<div class="card" style="padding:1rem;"><p>Missing encounter id. Open from Patients or Queue.</p></div>';
            return;
        }
        el.innerHTML = '<div class="card" style="padding:1rem;"><p>Loading…</p></div>';
        try {
            const enc = await API.clinic.encounters.get(eid);
            const patient = await API.clinic.patients.get(enc.patient_id);
            const notes = await API.clinic.encounters.notes.list(eid);
            const orders = await API.clinic.encounters.orders.list(eid);
            const completed = enc.status === 'completed';
            const statusActions =
                completed
                    ? '<p class="text-secondary" style="margin:0;">This encounter is completed — notes, orders, and status cannot be changed.</p>'
                    : enc.status === 'waiting'
                      ? '<button type="button" class="btn btn-primary btn-sm" id="clinicStProg">Start consultation</button>'
                      : '<button type="button" class="btn btn-primary btn-sm" id="clinicStDone">Complete visit</button>';
            const editorBlock = completed
                ? ''
                : `<h3>Clinical note</h3>
                    <textarea id="clinicNoteText" class="form-input" rows="3" style="width:100%;" placeholder="Notes"></textarea>
                    <textarea id="clinicDxText" class="form-input" rows="2" style="width:100%; margin-top:0.5rem;" placeholder="Diagnosis"></textarea>
                    <button type="button" class="btn btn-primary" id="clinicNoteSave" style="margin-top:0.5rem;">Save note</button>
                    <h3 style="margin-top:1rem;">Orders</h3>
                    <div style="display:flex; gap:0.5rem; flex-wrap:wrap;">
                        <button type="button" class="btn btn-secondary btn-sm" data-ot="prescription">+ Prescription</button>
                        <button type="button" class="btn btn-secondary btn-sm" data-ot="lab">+ Lab</button>
                        <button type="button" class="btn btn-secondary btn-sm" data-ot="procedure">+ Procedure</button>
                    </div>`;

            el.innerHTML = `
                <div class="card" style="padding:1rem;" id="clinicConsultCard">
                    <h2>Consultation</h2>
                    <p><strong>Patient:</strong> ${escapeHtml(patient.first_name || '')} ${escapeHtml(patient.last_name || '')} · ${escapeHtml(patient.phone || '—')}</p>
                    <p><strong>Status:</strong> ${escapeHtml(enc.status)} · <strong>Draft invoice:</strong> ${enc.sales_invoice_id ? `<code>${String(enc.sales_invoice_id).slice(0, 8)}…</code>` : '—'}</p>
                    <div style="margin:1rem 0; display:flex; gap:0.5rem; flex-wrap:wrap;">${statusActions}</div>
                    ${editorBlock}
                    <ul id="clinicOrderList" style="margin-top:0.5rem;">${formatOrderList(orders)}</ul>
                    <h3 style="margin-top:1rem;">Previous notes</h3>
                    <div style="font-size:0.9rem; color:var(--text-secondary);">${(notes || []).map((n) => `<p><em>${escapeHtml(n.created_at || '')}</em><br>${escapeHtml(n.notes || '')}<br><strong>Dx:</strong> ${escapeHtml(n.diagnosis || '')}</p>`).join('') || '<p>None</p>'}</div>
                </div>`;

            const card = document.getElementById('clinicConsultCard');

            const runBusy = async function (fn) {
                setButtonsDisabled(card, true);
                try {
                    await fn();
                } finally {
                    setButtonsDisabled(card, false);
                }
            };

            const saveStatus = async function (st) {
                try {
                    await runBusy(async function () {
                        await API.clinic.encounters.patchStatus(eid, st);
                        if (typeof window.showToast === 'function') window.showToast('Status updated', 'success');
                        await loadClinicConsultation();
                    });
                } catch (err) {
                    showErr(err.message || 'Failed');
                }
            };

            document.getElementById('clinicStProg')?.addEventListener('click', function () {
                void saveStatus('in_consultation');
            });
            document.getElementById('clinicStDone')?.addEventListener('click', function () {
                void saveStatus('completed');
            });

            document.getElementById('clinicNoteSave')?.addEventListener('click', async function () {
                const notesTxt = document.getElementById('clinicNoteText')?.value || '';
                const dx = document.getElementById('clinicDxText')?.value || '';
                try {
                    await runBusy(async function () {
                        await API.clinic.encounters.notes.add(eid, { notes: notesTxt, diagnosis: dx });
                        if (typeof window.showToast === 'function') window.showToast('Note saved', 'success');
                        await loadClinicConsultation();
                    });
                } catch (err) {
                    showErr(err.message || 'Failed to save note');
                }
            });

            el.querySelectorAll('[data-ot]').forEach(function (b) {
                b.addEventListener('click', async function () {
                    const ot = b.getAttribute('data-ot');
                    try {
                        await runBusy(async function () {
                            await API.clinic.encounters.orders.create(eid, {
                                order_type: ot,
                                items: [newServiceLineItem(ot)],
                            });
                            if (typeof window.showToast === 'function') window.showToast('Order added', 'success');
                            await loadClinicConsultation();
                        });
                    } catch (err) {
                        showErr(err.message || 'Failed');
                    }
                });
            });
        } catch (e) {
            el.innerHTML = `<div class="card" style="padding:1rem;"><p class="text-danger">Could not load encounter. ${escapeHtml(e.message || '')}</p></div>`;
        }
    }

    async function loadClinicTriage() {
        const el = document.getElementById('triage');
        if (!el) return;
        const params = new URLSearchParams(window.location.hash.split('?')[1] || '');
        const eid = params.get('id');
        if (!eid) {
            el.innerHTML = '<div class="card" style="padding:1rem;"><p>Missing encounter id. Open from Queue.</p></div>';
            return;
        }
        el.innerHTML = '<div class="card" style="padding:1rem;"><p>Loading…</p></div>';
        try {
            const enc = await API.clinic.encounters.get(eid);
            const patient = enc.patient ? enc.patient : await API.clinic.patients.get(enc.patient_id);
            const triage = await API.clinic.encounters.triage.get(eid);
            const orders = await API.clinic.encounters.orders.list(eid);
            const completed = enc.status === 'completed';
            const t = triage || {};
            const vit = t.vitals || {};
            const pname = `${patient.first_name || ''} ${patient.last_name || ''}`.trim();
            const gender = patient.gender || '—';
            const dob = patient.date_of_birth || null;
            el.innerHTML = `
                <div class="card" style="padding:1rem;" id="clinicTriageCard">
                    <h2>Triage</h2>
                    <p><strong>Patient:</strong> ${escapeHtml(pname || '—')} · ${escapeHtml(patient.phone || '—')}</p>
                    <p style="color:var(--text-secondary); margin-top:-0.5rem;">
                        <strong>Gender:</strong> ${escapeHtml(gender)}${dob ? ` · <strong>DOB:</strong> ${escapeHtml(String(dob))}` : ''}
                    </p>
                    <p><strong>Encounter:</strong> <code>${String(enc.id).slice(0, 8)}…</code> · <strong>Status:</strong> ${escapeHtml(enc.status)}</p>

                    ${completed ? `<div class="alert alert-warning" style="margin:0.75rem 0;">This encounter is completed — triage cannot be edited.</div>` : ''}

                    <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap:0.75rem; margin-top:1rem;">
                        <div>
                            <label>Payment mode</label>
                            <select id="triagePayMode" class="form-input" ${completed ? 'disabled' : ''}>
                                <option value="">—</option>
                                <option value="cash" ${t.payment_mode === 'cash' ? 'selected' : ''}>Cash</option>
                                <option value="insurance" ${t.payment_mode === 'insurance' ? 'selected' : ''}>Insurance</option>
                                <option value="other" ${t.payment_mode === 'other' ? 'selected' : ''}>Other</option>
                            </select>
                        </div>
                        <div>
                            <label>Insurance scheme</label>
                            <input id="triageInsurance" class="form-input" placeholder="e.g. NHIF, Jubilee…" value="${escapeHtml(t.insurance_scheme || '')}" ${completed ? 'disabled' : ''} />
                        </div>
                    </div>

                    <div style="margin-top:1rem;">
                        <label>Chief complaint</label>
                        <input id="triageChief" class="form-input" placeholder="e.g. Fever, headache…" value="${escapeHtml(t.chief_complaint || '')}" ${completed ? 'disabled' : ''} />
                    </div>
                    <div style="margin-top:0.75rem;">
                        <label>Symptoms</label>
                        <textarea id="triageSymptoms" class="form-input" rows="3" placeholder="Key symptoms…" ${completed ? 'disabled' : ''}>${escapeHtml(t.symptoms || '')}</textarea>
                    </div>

                    <h3 style="margin-top:1rem;">Vitals</h3>
                    <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap:0.75rem;">
                        <div><label>Temperature (°C)</label><input id="vTemp" class="form-input" inputmode="decimal" value="${escapeHtml(vit.temp_c || '')}" ${completed ? 'disabled' : ''} /></div>
                        <div><label>Pulse (bpm)</label><input id="vPulse" class="form-input" inputmode="numeric" value="${escapeHtml(vit.pulse_bpm || '')}" ${completed ? 'disabled' : ''} /></div>
                        <div><label>BP</label><input id="vBp" class="form-input" placeholder="120/80" value="${escapeHtml(vit.bp || '')}" ${completed ? 'disabled' : ''} /></div>
                        <div><label>Resp rate</label><input id="vResp" class="form-input" inputmode="numeric" value="${escapeHtml(vit.resp_rate || '')}" ${completed ? 'disabled' : ''} /></div>
                        <div><label>SpO₂ (%)</label><input id="vSpo2" class="form-input" inputmode="numeric" value="${escapeHtml(vit.spo2_pct || '')}" ${completed ? 'disabled' : ''} /></div>
                        <div><label>Weight (kg)</label><input id="vWt" class="form-input" inputmode="decimal" value="${escapeHtml(vit.weight_kg || '')}" ${completed ? 'disabled' : ''} /></div>
                        <div><label>Height (cm)</label><input id="vHt" class="form-input" inputmode="decimal" value="${escapeHtml(vit.height_cm || '')}" ${completed ? 'disabled' : ''} /></div>
                    </div>

                    <div style="margin-top:0.75rem;">
                        <label>Triage notes</label>
                        <textarea id="triageNotes" class="form-input" rows="3" placeholder="Extra notes…" ${completed ? 'disabled' : ''}>${escapeHtml(t.triage_notes || '')}</textarea>
                    </div>

                    <h3 style="margin-top:1rem;">Quick charges / orders</h3>
                    <p style="color:var(--text-secondary); font-size:0.875rem; margin-top:-0.25rem;">
                        Add a service line (procedure/lab/prescription) now, or leave for consultation.
                    </p>
                    <div style="display:flex; gap:0.5rem; flex-wrap:wrap; margin-bottom:0.5rem;">
                        <button type="button" class="btn btn-secondary btn-sm" data-ot="procedure" ${completed ? 'disabled' : ''}>+ Procedure</button>
                        <button type="button" class="btn btn-secondary btn-sm" data-ot="lab" ${completed ? 'disabled' : ''}>+ Lab</button>
                        <button type="button" class="btn btn-secondary btn-sm" data-ot="prescription" ${completed ? 'disabled' : ''}>+ Prescription</button>
                    </div>
                    <ul id="clinicTriageOrderList">${formatOrderList(orders)}</ul>

                    <div style="margin-top:1rem; display:flex; gap:0.5rem; flex-wrap:wrap; align-items:center;">
                        <button type="button" class="btn btn-primary" id="triageSave" ${completed ? 'disabled' : ''}>Save triage</button>
                        <button type="button" class="btn btn-outline" id="triageToConsult" ${completed ? 'disabled' : ''}>Send to consultation</button>
                        <button type="button" class="btn btn-secondary" id="triageBack">Back to queue</button>
                    </div>
                </div>
            `;

            const card = document.getElementById('clinicTriageCard');
            const runBusy = async function (fn) {
                setButtonsDisabled(card, true);
                try {
                    await fn();
                } finally {
                    setButtonsDisabled(card, false);
                }
            };

            const collectVitals = () => {
                const v = {
                    temp_c: (document.getElementById('vTemp')?.value || '').trim() || null,
                    pulse_bpm: (document.getElementById('vPulse')?.value || '').trim() || null,
                    bp: (document.getElementById('vBp')?.value || '').trim() || null,
                    resp_rate: (document.getElementById('vResp')?.value || '').trim() || null,
                    spo2_pct: (document.getElementById('vSpo2')?.value || '').trim() || null,
                    weight_kg: (document.getElementById('vWt')?.value || '').trim() || null,
                    height_cm: (document.getElementById('vHt')?.value || '').trim() || null,
                };
                // Remove empty keys for cleaner payload
                Object.keys(v).forEach((k) => {
                    if (v[k] === null) delete v[k];
                });
                return v;
            };

            const save = async () => {
                const payment_mode = (document.getElementById('triagePayMode')?.value || '').trim() || null;
                const insurance_scheme = (document.getElementById('triageInsurance')?.value || '').trim() || null;
                const chief_complaint = (document.getElementById('triageChief')?.value || '').trim() || null;
                const symptoms = (document.getElementById('triageSymptoms')?.value || '').trim() || null;
                const triage_notes = (document.getElementById('triageNotes')?.value || '').trim() || null;
                const vitals = collectVitals();
                await API.clinic.encounters.triage.upsert(eid, {
                    payment_mode,
                    insurance_scheme,
                    chief_complaint,
                    symptoms,
                    triage_notes,
                    vitals,
                });
            };

            document.getElementById('triageSave')?.addEventListener('click', async () => {
                try {
                    await runBusy(async () => {
                        await save();
                        if (typeof window.showToast === 'function') window.showToast('Triage saved', 'success');
                        await loadClinicTriage();
                    });
                } catch (e) {
                    showErr(e.message || 'Failed to save triage');
                }
            });
            document.getElementById('triageToConsult')?.addEventListener('click', async () => {
                try {
                    await runBusy(async () => {
                        await save();
                        await API.clinic.encounters.patchStatus(eid, 'in_consultation');
                        window.location.hash = `#consultation?id=${encodeURIComponent(eid)}`;
                        if (typeof window.loadPage === 'function') await window.loadPage('consultation');
                    });
                } catch (e) {
                    showErr(e.message || 'Failed');
                }
            });
            document.getElementById('triageBack')?.addEventListener('click', () => {
                window.location.hash = '#encounters';
                if (typeof window.loadPage === 'function') void window.loadPage('encounters');
            });

            el.querySelectorAll('[data-ot]').forEach(function (b) {
                b.addEventListener('click', async function () {
                    const ot = b.getAttribute('data-ot');
                    try {
                        await runBusy(async function () {
                            await API.clinic.encounters.orders.create(eid, {
                                order_type: ot,
                                items: [newServiceLineItem(ot)],
                            });
                            if (typeof window.showToast === 'function') window.showToast('Order added', 'success');
                            await loadClinicTriage();
                        });
                    } catch (err) {
                        showErr(err.message || 'Failed');
                    }
                });
            });
        } catch (e) {
            el.innerHTML = `<div class="card" style="padding:1rem;"><p class="text-danger">Could not load triage. ${escapeHtml(e.message || '')}</p></div>`;
        }
    }

    function formatOrderList(orders) {
        if (!orders || !orders.length) return '<li>No orders</li>';
        return orders
            .map(function (o) {
                var parts = (o.items || []).map(function (it) {
                    return escapeHtml(String(it.reference_type)) + ' ×' + escapeHtml(String(it.quantity));
                });
                var detail = parts.length ? ' (' + parts.join(', ') + ')' : '';
                return '<li>' + escapeHtml(o.order_type) + ' — ' + escapeHtml(o.status) + detail + '</li>';
            })
            .join('');
    }

    window.loadClinicPatients = loadClinicPatients;
    window.loadClinicEncounters = loadClinicEncounters;
    window.loadClinicTriage = loadClinicTriage;
    window.loadClinicConsultation = loadClinicConsultation;
})();
