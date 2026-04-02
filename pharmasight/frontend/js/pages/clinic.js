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
                if (btn) btn.disabled = true;
                setButtonsDisabled(card, true);
                try {
                    await API.clinic.patients.create({ first_name, last_name, phone });
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
            const col = (title, arr) => {
                const body = (Array.isArray(arr) ? arr : [])
                    .map(
                        (x) =>
                            `<tr><td><code style="font-size:0.75rem;">${String(x.id).slice(0, 8)}…</code></td><td>${escapeHtml(x.status)}</td><td><button type="button" class="btn btn-sm btn-primary" data-eid="${x.id}">Open</button></td></tr>`
                    )
                    .join('');
                return `<div class="card" style="padding:0.75rem; flex:1; min-width:220px;"><h3 style="margin:0 0 0.5rem;">${title}</h3><table class="data-table" style="width:100%;"><tbody>${body || emptyRowForColumn(title)}</tbody></table></div>`;
            };
            el.innerHTML = `<div style="padding:0.5rem;"><h2>Encounter queue</h2><div style="display:flex; flex-wrap:wrap; gap:0.75rem;">${col('Waiting', waiting)}${col('In consultation', active)}${col('Completed', done)}</div></div>`;
            el.querySelectorAll('[data-eid]').forEach((btn) => {
                btn.addEventListener('click', () => {
                    const id = btn.getAttribute('data-eid');
                    window.location.hash = `#consultation?id=${encodeURIComponent(id)}`;
                    if (typeof window.loadPage === 'function') void window.loadPage('consultation');
                });
            });
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
    window.loadClinicConsultation = loadClinicConsultation;
})();
