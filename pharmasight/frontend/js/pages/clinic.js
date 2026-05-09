/**
 * OPD UI: patients list/create, encounter queue, consultation (notes + orders).
 * Requires clinic module (backend 403 otherwise).
 */
(function () {
    const clinicUiState = {
        reception: {
            selectedPatientId: null,
            searchQuery: '',
            searchDebounceTimer: null,
            patients: [],
            encounterPriority: {},
            showCreateForm: false,
            loadingPatients: false,
            loadError: null,
            datePreset: 'today',
            dateFrom: '',
            dateTo: '',
            editPatientId: null,
        },
        queue: {
            filters: {
                search: '',
                status: 'all',
                date: '',
            },
        },
        triage: {
            activeTab: 'attend_patient',
            showLookup: false,
            complaintsLoaded: false,
            complaints: [],
            serviceSearchQuery: '',
            serviceSearchResults: [],
            selectedServiceId: null,
            deptSupplyDraftLines: [],
            deptSupplyItemSearch: '',
            deptSupplySearchResults: [],
            deptSupplySearchTimer: null,
            deptSupplySelectedStoreId: null,
        },
        registerLookup: {
            query: '',
            loading: false,
            error: null,
            patients: [],
            encounters: [],
            showAll: false,
            lastFetchedAt: 0,
        },
    };

    /** Triage “Raise stock request” uses TransactionItemsTable; persist lines here across re-renders. */
    let triageDeptSupplyOrderTable = null;
    /** Dedupe concurrent register API bursts (multiple clinic screens share the same cache). */
    let registerLookupInFlight = null;

    /** Optional caption; omit or pass '' for ring-only (matches global #pageLoadOverlay). */
    function renderClinicPageSpinner(message) {
        var raw = message != null ? String(message) : '';
        var hasMsg = raw.trim() !== '';
        var msgHtml = hasMsg
            ? '<p style="margin:0.75rem 0 0 0; color:var(--text-secondary); font-size:0.9rem;">' + escapeHtml(raw) + '</p>'
            : '';
        return (
            '<div class="card" style="padding:2rem; text-align:center;" role="status" aria-live="polite">' +
            '<div class="ps-page-load-ring" aria-hidden="true"></div>' +
            msgHtml +
            '</div>'
        );
    }

    function normalizeClinicStation(station) {
        var s = String(station || '').trim().toLowerCase();
        if (s === 'patients') return 'reception';
        if (s === 'encounters') return 'queue';
        if (s === 'reception' || s === 'queue' || s === 'triage' || s === 'consultation') return s;
        return 'queue';
    }

    function stationToRoute(station) {
        // Keep current app route compatibility (app.js currently handles patients/encounters).
        var s = normalizeClinicStation(station);
        if (s === 'reception') return 'patients';
        if (s === 'queue') return 'encounters';
        return s;
    }

    function readEncounterIdFromHash() {
        var raw = String(window.location.hash || '');
        var qIndex = raw.indexOf('?');
        var query = qIndex >= 0 ? raw.slice(qIndex + 1) : '';
        var params = new URLSearchParams(query);
        return params.get('id');
    }

    function parseDeptStoreHashPath() {
        var path = String(window.location.hash || '')
            .replace(/^#/, '')
            .split('?')[0];
        var m = /^deptstore-([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})-(attend-patient|raise-order|transfer|manage-assets)$/i.exec(
            path
        );
        return m ? { storeId: m[1], view: m[2] } : null;
    }

    function isClinicDeptStoreWorkstation() {
        return !!(typeof window !== 'undefined' && window.__clinicDeptStoreId);
    }

    function deptStoreNavTitle() {
        if (!isClinicDeptStoreWorkstation()) return '';
        var mid = String(window.__clinicDeptStoreId || '');
        var meta = window.__clinicDeptNavMeta && window.__clinicDeptNavMeta[mid];
        return meta && meta.name ? String(meta.name) : '';
    }

    function getCurrentClinicStation() {
        var ds = parseDeptStoreHashPath();
        if (ds) return 'triage';
        var raw = String(window.location.hash || '').replace(/^#/, '');
        var path = raw.split('?')[0];
        var base = path.split('-')[0];
        return normalizeClinicStation(base);
    }

    function getClinicStationSubRoute(station, fallback) {
        if (normalizeClinicStation(station) === 'triage') {
            var ds = parseDeptStoreHashPath();
            if (ds) return ds.view || fallback;
        }
        var raw = String(window.location.hash || '').replace(/^#/, '');
        var path = raw.split('?')[0];
        var first = path.split('-')[0];
        if (normalizeClinicStation(first) !== normalizeClinicStation(station)) return fallback;
        var sub = path.split('-').slice(1).join('-');
        return sub || fallback;
    }

    function shouldApplyClinicRender(station, encounterId) {
        var currentStation = getCurrentClinicStation();
        if (normalizeClinicStation(station) !== currentStation) return false;
        if (!encounterId) return true;
        return String(readEncounterIdFromHash() || '') === String(encounterId || '');
    }

    function navigateToEncounterStation(station, encounterId) {
        var route = stationToRoute(station);
        if (station === 'triage') {
            var ds = parseDeptStoreHashPath();
            if (ds && ds.storeId && ds.view) {
                route = 'deptstore-' + ds.storeId + '-' + ds.view;
            }
        }
        var hash = '#' + route;
        if (encounterId) hash += '?id=' + encodeURIComponent(encounterId);
        // Single navigation authority: hash routing drives page loading.
        // Fallback to direct load only when hash is unchanged (no hashchange event).
        if (String(window.location.hash || '') !== hash) {
            window.location.hash = hash;
        } else if (typeof window.loadPage === 'function') {
            void window.loadPage(route);
        }
    }

    async function startEncounterVisit(patientId) {
        var bid = branchId();
        if (!bid) {
            throw new Error('Select a branch first');
        }
        await API.clinic.encounters.create({ patient_id: patientId, branch_id: bid });
        navigateToEncounterStation('queue');
        if (typeof window.loadPage !== 'function') {
            await loadClinicEncounters();
        }
    }

    function openEncounterStation(encounter) {
        var target = encounter && encounter.status === 'waiting' ? 'triage' : 'consultation';
        navigateToEncounterStation(target, encounter && encounter.id);
    }

    async function requestEncounterStatusTransition(encounterId, status, options) {
        var opts = options || {};
        await API.clinic.encounters.patchStatus(encounterId, status);
        if (opts.successMessage && typeof window.showToast === 'function') {
            window.showToast(opts.successMessage, 'success');
        }
        if (typeof opts.onSuccess === 'function') {
            await opts.onSuccess();
        }
    }

    async function completeEncounter(encounterId, options) {
        return requestEncounterStatusTransition(encounterId, 'completed', options || {});
    }

    async function sendEncounterToConsultation(encounterId, triagePayload) {
        await API.clinic.encounters.triage.upsert(encounterId, triagePayload || {});
        await requestEncounterStatusTransition(encounterId, 'in_consultation');
        navigateToEncounterStation('consultation', encounterId);
        if (typeof window.loadPage !== 'function') {
            await loadClinicConsultation();
        }
    }

    function branchId() {
        return (typeof CONFIG !== 'undefined' && CONFIG.BRANCH_ID) || null;
    }

    function showErr(msg) {
        if (typeof window.showToast === 'function') window.showToast(msg, 'error');
        else alert(msg);
    }

    function filterPatientsByQuery(list, query) {
        var q = String(query || '').trim().toLowerCase();
        var arr = Array.isArray(list) ? list : [];
        if (!q) return arr;
        return arr.filter(function (p) {
            var hay = [
                p && p.first_name,
                p && p.last_name,
                p && p.phone,
            ]
                .map(function (x) { return String(x || '').toLowerCase(); })
                .join(' ');
            return hay.includes(q);
        });
    }

    function getDateRangeForPreset(preset) {
        const now = new Date();
        const y = now.getFullYear(), m = now.getMonth(), d = now.getDate();
        const fmt = (dt) => [dt.getFullYear(), String(dt.getMonth() + 1).padStart(2, '0'), String(dt.getDate()).padStart(2, '0')].join('-');
        switch (preset) {
            case 'today': { const t = new Date(y, m, d); return { from: fmt(t), to: fmt(t) }; }
            case 'yesterday': { const t = new Date(y, m, d - 1); return { from: fmt(t), to: fmt(t) }; }
            case 'this_week': {
                const day = now.getDay();
                const mon = new Date(y, m, d - (day === 0 ? 6 : day - 1));
                return { from: fmt(mon), to: fmt(new Date(y, m, d)) };
            }
            case 'last_week': {
                const day = now.getDay();
                const mon = new Date(y, m, d - (day === 0 ? 6 : day - 1) - 7);
                const sun = new Date(mon); sun.setDate(mon.getDate() + 6);
                return { from: fmt(mon), to: fmt(sun) };
            }
            case 'this_month': return { from: [y, String(m + 1).padStart(2, '0'), '01'].join('-'), to: fmt(new Date(y, m, d)) };
            case 'last_month': {
                const first = new Date(y, m - 1, 1);
                const last = new Date(y, m, 0);
                return { from: fmt(first), to: fmt(last) };
            }
            case 'this_year': return { from: [y, '01', '01'].join('-'), to: [y, '12', '31'].join('-') };
            case 'last_year': return { from: [y - 1, '01', '01'].join('-'), to: [y - 1, '12', '31'].join('-') };
            default: return null;
        }
    }

    function inSelectedDateRange(ts) {
        const preset = clinicUiState.reception.datePreset || 'today';
        if (preset === 'all') return true;
        let from = '', to = '';
        if (preset === 'custom') {
            from = clinicUiState.reception.dateFrom || '';
            to = clinicUiState.reception.dateTo || '';
        } else {
            const r = getDateRangeForPreset(preset);
            from = r?.from || '';
            to = r?.to || '';
        }
        const d = String(ts || '').slice(0, 10);
        if (!d) return false;
        if (from && d < from) return false;
        if (to && d > to) return false;
        return true;
    }

    function getSelectedPatient(list) {
        var selectedId = clinicUiState.reception.selectedPatientId;
        if (!selectedId) return null;
        var arr = Array.isArray(list) ? list : [];
        return arr.find(function (p) { return String(p.id) === String(selectedId); }) || null;
    }

    function buildReceptionPatientPriority(encounters) {
        var map = {};
        (Array.isArray(encounters) ? encounters : []).forEach(function (enc) {
            if (!inSelectedDateRange(enc?.created_at)) return;
            var pid = String(enc && enc.patient_id || '');
            if (!pid) return;
            var created = String(enc && enc.created_at || '');
            var score = enc && enc.status === 'waiting' ? 3 : enc && enc.status === 'in_consultation' ? 2 : 1;
            if (!map[pid]) {
                map[pid] = { score: score, created_at: created, encounter: enc };
                return;
            }
            var prev = map[pid];
            if (score > prev.score || (score === prev.score && created > String(prev.created_at || ''))) {
                map[pid] = { score: score, created_at: created, encounter: enc };
            }
        });
        return map;
    }

    function getReceptionPatientsSorted() {
        var patients = filterPatientsByQuery(clinicUiState.reception.patients || [], clinicUiState.reception.searchQuery || '');
        var priority = clinicUiState.reception.encounterPriority || {};
        return patients.sort(function (a, b) {
            var pa = priority[String(a && a.id || '')];
            var pb = priority[String(b && b.id || '')];
            var sa = pa ? pa.score : 0;
            var sb = pb ? pb.score : 0;
            if (sb !== sa) return sb - sa;
            var ca = pa ? String(pa.created_at || '') : '';
            var cb = pb ? String(pb.created_at || '') : '';
            if (cb !== ca) return cb.localeCompare(ca);
            var na = ((a && a.first_name) || '') + ' ' + ((a && a.last_name) || '');
            var nb = ((b && b.first_name) || '') + ' ' + ((b && b.last_name) || '');
            return na.localeCompare(nb);
        });
    }

    function renderReceptionSearchDropdownRows() {
        if (clinicUiState.reception.loadingPatients) {
            return '<div class="text-secondary" style="padding:0.5rem;">Loading today patients...</div>';
        }
        if (clinicUiState.reception.loadError) {
            return '<div class="text-danger" style="padding:0.5rem;">Could not load patients. Please retry.</div>';
        }
        var prioritized = getReceptionPatientsSorted()
            .map(function (p) {
                var pri = clinicUiState.reception.encounterPriority[String(p.id)];
                var status = String(pri?.encounter?.status || '');
                var isActive = status === 'waiting' || status === 'in_consultation';
                return { patient: p, pri: pri, isActive: isActive };
            })
            .sort(function (a, b) {
                if (a.isActive !== b.isActive) return a.isActive ? -1 : 1;
                return 0;
            });
        var rows = prioritized
            .slice(0, 25)
            .map(function (row) {
                var p = row.patient;
                var selected = String(clinicUiState.reception.selectedPatientId || '') === String(p.id);
                var pri = row.pri;
                var badge = '';
                if (pri && pri.encounter && pri.encounter.status) {
                    badge = '<span class="badge badge-info" style="font-size:0.7rem;">' + escapeHtml(pri.encounter.status) + '</span>';
                }
                var activeBadge = row.isActive ? '<span class="badge badge-success" style="font-size:0.7rem;">Active</span>' : '';
                return (
                    '<button type="button" class="btn btn-outline" data-select-pid="' + p.id + '" style="display:flex; width:100%; justify-content:space-between; align-items:center; text-align:left; margin-bottom:0.25rem;">' +
                    '<span><strong>' + escapeHtml((p.first_name || '') + ' ' + (p.last_name || '')) + '</strong><br><small style="color:var(--text-secondary);">' + escapeHtml(p.phone || '—') + '</small></span>' +
                    '<span style="display:flex; gap:0.35rem; align-items:center;">' + activeBadge + badge + (selected ? '<span class="badge badge-success" style="font-size:0.7rem;">Selected</span>' : '') + '</span>' +
                    '</button>'
                );
            })
            .join('');
        return rows || '<div class="text-secondary" style="padding:0.5rem;">No matching patients.</div>';
    }

    function getSelectedPatientRecentEncounter() {
        var selectedId = clinicUiState.reception.selectedPatientId;
        if (!selectedId) return null;
        var p = clinicUiState.reception.encounterPriority[String(selectedId)];
        return p ? p.encounter : null;
    }

    function renderReceptionSelectedSummary() {
        var patient = getSelectedPatient(clinicUiState.reception.patients || []);
        var recentEncounter = getSelectedPatientRecentEncounter();
        if (!patient) {
            return `
                <div class="card" style="padding:1rem;">
                    <h3 style="margin-top:0;">Selected Patient</h3>
                    <p class="text-secondary" style="margin:0;">Search and select a patient to continue, or create a new profile if not found.</p>
                </div>
            `;
        }
        return `
            <div class="card" style="padding:1rem;">
                <h3 style="margin-top:0;">Selected Patient</h3>
                <p style="margin:0 0 0.35rem 0;"><strong>${escapeHtml(patient.first_name || '')} ${escapeHtml(patient.last_name || '')}</strong></p>
                <p style="margin:0 0 0.35rem 0; color:var(--text-secondary);">${escapeHtml(patient.phone || '—')} · ${escapeHtml(patient.gender || '—')}</p>
                <p style="margin:0 0 0.75rem 0; color:var(--text-secondary);">DOB: ${escapeHtml(patient.date_of_birth || '—')}</p>
                <p style="margin:0 0 0.75rem 0;"><strong>Recent encounter:</strong> ${recentEncounter ? `<code>${escapeHtml(String(recentEncounter.id).slice(0, 8))}…</code> · ${escapeHtml(recentEncounter.status || '—')}` : 'None found'}</p>
                <div style="display:flex; gap:0.5rem; flex-wrap:wrap;">
                    <button type="button" class="btn btn-primary" id="clinicStartVisitFromProfile" data-pid="${patient.id}">Start Visit</button>
                    <button type="button" class="btn btn-outline" id="clinicEditPatientBtn" data-pid="${patient.id}">Edit</button>
                </div>
                <div id="clinicEditPatientWrap" style="display:${clinicUiState.reception.editPatientId && String(clinicUiState.reception.editPatientId) === String(patient.id) ? 'block' : 'none'}; margin-top:0.75rem; border-top:1px solid var(--border-color); padding-top:0.75rem;">
                    <div style="display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:0.5rem;">
                        <div><label>First name</label><input id="editPtFirst" class="form-input" value="${escapeHtml(patient.first_name || '')}" /></div>
                        <div><label>Last name</label><input id="editPtLast" class="form-input" value="${escapeHtml(patient.last_name || '')}" /></div>
                        <div><label>Phone</label><input id="editPtPhone" class="form-input" value="${escapeHtml(patient.phone || '')}" /></div>
                        <div><label>Gender</label><input id="editPtGender" class="form-input" value="${escapeHtml(patient.gender || '')}" /></div>
                        <div><label>ID number</label><input id="editPtIdNumber" class="form-input" value="${escapeHtml(patient.id_number || '')}" /></div>
                        <div><label>Residence</label><input id="editPtResidence" class="form-input" value="${escapeHtml(patient.residence || '')}" /></div>
                    </div>
                    <div style="margin-top:0.6rem; display:flex; gap:0.5rem;">
                        <button class="btn btn-primary" id="clinicSaveEditPatient" data-pid="${patient.id}">Save changes</button>
                        <button class="btn btn-outline" id="clinicCancelEditPatient">Cancel</button>
                    </div>
                </div>
            </div>
        `;
    }

    function renderReceptionCreatePanel() {
        return `
            <div class="card" style="padding:1rem;">
                <h3 style="margin:0 0 0.5rem 0;">Create New Patient</h3>
                <p class="text-secondary" style="margin:0 0 0.75rem 0;">
                    Open the dedicated register form to capture full intake details and optionally schedule where the patient goes first.
                </p>
                <div>
                    <button type="button" class="btn btn-primary" id="clinicOpenRegisterCreate">Create New Patient</button>
                </div>
            </div>
        `;
    }

    function renderReceptionWorkflowSurface() {
        const preset = clinicUiState.reception.datePreset || 'today';
        return `
            <div style="padding:0.5rem;" id="clinicReceptionWorkflow">
                <h2>Register</h2>
                <div class="card" style="padding:1rem; margin-bottom:0.75rem;">
                    <div style="display:flex; gap:0.5rem; flex-wrap:wrap; margin-bottom:0.6rem; align-items:end;">
                        <div>
                            <label>Date range</label>
                            <select id="regDatePreset" class="form-input">
                                <option value="today" ${preset === 'today' ? 'selected' : ''}>Today</option>
                                <option value="yesterday" ${preset === 'yesterday' ? 'selected' : ''}>Yesterday</option>
                                <option value="this_week" ${preset === 'this_week' ? 'selected' : ''}>This Week</option>
                                <option value="last_week" ${preset === 'last_week' ? 'selected' : ''}>Last Week</option>
                                <option value="this_month" ${preset === 'this_month' ? 'selected' : ''}>This Month</option>
                                <option value="last_month" ${preset === 'last_month' ? 'selected' : ''}>Last Month</option>
                                <option value="this_year" ${preset === 'this_year' ? 'selected' : ''}>This Year</option>
                                <option value="last_year" ${preset === 'last_year' ? 'selected' : ''}>Last Year</option>
                                <option value="custom" ${preset === 'custom' ? 'selected' : ''}>Custom</option>
                                <option value="all" ${preset === 'all' ? 'selected' : ''}>All</option>
                            </select>
                        </div>
                        <div id="regCustomDates" style="display:${preset === 'custom' ? 'flex' : 'none'}; gap:0.4rem;">
                            <div><label>From</label><input type="date" id="regDateFrom" class="form-input" value="${escapeHtml(clinicUiState.reception.dateFrom || '')}" /></div>
                            <div><label>To</label><input type="date" id="regDateTo" class="form-input" value="${escapeHtml(clinicUiState.reception.dateTo || '')}" /></div>
                        </div>
                    </div>
                    <label>Search patient (name / phone)</label>
                    <div style="display:flex; gap:0.5rem; margin-top:0.35rem;">
                        <input type="text" id="clinicPtSearch" class="form-input" placeholder="Start typing patient name or phone..." value="${escapeHtml(clinicUiState.reception.searchQuery || '')}" />
                        <button type="button" class="btn btn-sm btn-outline" id="clinicPtSearchClear">Clear</button>
                    </div>
                    <div id="clinicPtSearchDropdown" style="margin-top:0.6rem; max-height:300px; overflow:auto; border:1px solid var(--border-color); border-radius:0.45rem; padding:0.45rem; background:var(--card-bg);">
                        ${renderReceptionSearchDropdownRows()}
                    </div>
                </div>
                <div style="display:grid; grid-template-columns:1fr 1fr; gap:0.75rem; align-items:start;">
                    <div id="clinicSelectedPatientPanel">${renderReceptionSelectedSummary()}</div>
                    <div id="clinicCreatePatientPanel">${renderReceptionCreatePanel()}</div>
                </div>
            </div>
        `;
    }

    function updateReceptionLocalizedView() {
        var dropdown = document.getElementById('clinicPtSearchDropdown');
        if (dropdown) dropdown.innerHTML = renderReceptionSearchDropdownRows();
        var selectedPanel = document.getElementById('clinicSelectedPatientPanel');
        if (selectedPanel) selectedPanel.innerHTML = renderReceptionSelectedSummary();
        var createPanel = document.getElementById('clinicCreatePatientPanel');
        if (createPanel) createPanel.innerHTML = renderReceptionCreatePanel();
    }

    function renderReceptionSearchList(list) {
        var query = clinicUiState.reception.searchQuery || '';
        var rows = filterPatientsByQuery(list, query)
            .map(function (p) {
                var selected = String(clinicUiState.reception.selectedPatientId || '') === String(p.id);
                return (
                    '<tr>' +
                    '<td>' + escapeHtml((p.first_name || '') + ' ' + (p.last_name || '')) + '</td>' +
                    '<td>' + escapeHtml(p.phone || '—') + '</td>' +
                    '<td style="display:flex; gap:0.5rem; justify-content:flex-end;">' +
                    '<button type="button" class="btn btn-sm ' + (selected ? 'btn-primary' : 'btn-outline') + '" data-select-pid="' + p.id + '">' + (selected ? 'Selected' : 'Select') + '</button>' +
                    '</td>' +
                    '</tr>'
                );
            })
            .join('');
        return `
            <div class="card" style="padding:1rem;">
                <h3 style="margin-top:0;">Section A — Patient Search/List</h3>
                <div style="display:flex; gap:0.5rem; align-items:flex-end; margin-bottom:0.75rem; flex-wrap:wrap;">
                    <div style="flex:1; min-width:220px;">
                    <label>Search patient (name / phone)</label>
                    <input type="text" id="clinicPtSearch" class="form-input" placeholder="Type to filter…" value="${escapeHtml(query)}" />
                    </div>
                    <button type="button" class="btn btn-sm btn-outline" id="clinicPtSearchClear">Clear</button>
                </div>
                <table class="data-table" style="width:100%;">
                    <thead><tr><th>Name</th><th>Phone</th><th style="text-align:right;">Actions</th></tr></thead>
                    <tbody>${rows || '<tr><td colspan="3">No patients</td></tr>'}</tbody>
                </table>
            </div>
        `;
    }

    function renderClinicStationNav() {
        var current = getCurrentClinicStation();
        function link(station, label) {
            var active = current === station;
            var cls = active ? 'btn btn-sm btn-primary' : 'btn btn-sm btn-outline';
            var route = stationToRoute(station);
            return '<a class="' + cls + '" href="#' + route + '">' + label + '</a>';
        }
        return `
            <div style="display:flex; gap:0.5rem; flex-wrap:wrap; margin-bottom:0.75rem;">
                ${link('reception', 'Register')}
                ${link('triage', 'Triage')}
                ${link('consultation', 'Consultation')}
            </div>
        `;
    }

    function getComplaintStorageKey() {
        return 'clinic_chief_complaints_' + String((typeof CONFIG !== 'undefined' && CONFIG.COMPANY_ID) || 'default');
    }

    async function ensureChiefComplaintDictionary() {
        if (clinicUiState.triage.complaintsLoaded) return;
        clinicUiState.triage.complaintsLoaded = true;
        var local = [];
        try {
            local = JSON.parse(localStorage.getItem(getComplaintStorageKey()) || '[]');
            if (!Array.isArray(local)) local = [];
        } catch (_) { local = []; }
        var merged = new Set(local.map(function (x) { return String(x || '').trim(); }).filter(Boolean));
        try {
            var companyId = (typeof CONFIG !== 'undefined' && CONFIG.COMPANY_ID) || null;
            if (companyId) {
                var res = await API.company.getSettings(companyId, 'clinic_chief_complaints');
                var remote = Array.isArray(res?.value) ? res.value : [];
                remote.forEach(function (x) {
                    var s = String(x || '').trim();
                    if (s) merged.add(s);
                });
            }
        } catch (_) {}
        clinicUiState.triage.complaints = Array.from(merged).slice(0, 500);
    }

    async function persistChiefComplaintTerm(term) {
        var t = String(term || '').trim();
        if (t.length < 3) return;
        var list = Array.isArray(clinicUiState.triage.complaints) ? clinicUiState.triage.complaints.slice() : [];
        if (!list.some(function (x) { return String(x || '').toLowerCase() === t.toLowerCase(); })) list.unshift(t);
        clinicUiState.triage.complaints = list.slice(0, 500);
        try {
            localStorage.setItem(getComplaintStorageKey(), JSON.stringify(clinicUiState.triage.complaints));
        } catch (_) {}
        try {
            var companyId = (typeof CONFIG !== 'undefined' && CONFIG.COMPANY_ID) || null;
            if (companyId) {
                await API.company.updateSetting(companyId, {
                    key: 'clinic_chief_complaints',
                    value: clinicUiState.triage.complaints,
                });
            }
        } catch (_) {}
    }

    async function searchTriageServices(query) {
        var q = String(query || '').trim();
        clinicUiState.triage.serviceSearchQuery = q;
        if (q.length < 2) {
            clinicUiState.triage.serviceSearchResults = [];
            return;
        }
        try {
            var rows = await API.clinic.services.list({ q: q, include_inactive: false });
            clinicUiState.triage.serviceSearchResults = Array.isArray(rows) ? rows.slice(0, 15) : [];
        } catch (_) {
            clinicUiState.triage.serviceSearchResults = [];
        }
    }

    var REGISTER_LOOKUP_TTL_MS = 25000;

    async function ensureRegisterLookupData(opts) {
        opts = opts || {};
        var force = opts.force === true;
        var now = Date.now();
        var last = clinicUiState.registerLookup.lastFetchedAt || 0;
        if (
            !force &&
            last > 0 &&
            now - last < REGISTER_LOOKUP_TTL_MS &&
            !clinicUiState.registerLookup.error &&
            Array.isArray(clinicUiState.registerLookup.patients)
        ) {
            return;
        }
        if (!force && registerLookupInFlight) {
            return registerLookupInFlight;
        }

        clinicUiState.registerLookup.loading = true;
        clinicUiState.registerLookup.error = null;

        var task = (async function () {
            try {
                const [patients, waiting, active, done] = await Promise.all([
                    API.clinic.patients.list(),
                    API.clinic.encounters.list('waiting'),
                    API.clinic.encounters.list('in_consultation'),
                    API.clinic.encounters.list('completed'),
                ]);
                clinicUiState.registerLookup.patients = Array.isArray(patients) ? patients : [];
                clinicUiState.registerLookup.encounters = []
                    .concat(Array.isArray(waiting) ? waiting : [])
                    .concat(Array.isArray(active) ? active : [])
                    .concat(Array.isArray(done) ? done : []);
                clinicUiState.registerLookup.lastFetchedAt = Date.now();
            } catch (e) {
                clinicUiState.registerLookup.error = e?.message || 'Could not load register';
                clinicUiState.registerLookup.lastFetchedAt = 0;
            } finally {
                clinicUiState.registerLookup.loading = false;
            }
        })();

        registerLookupInFlight = task;
        try {
            await task;
        } finally {
            if (registerLookupInFlight === task) registerLookupInFlight = null;
        }
    }

    function getRegisterLookupRows() {
        const q = String(clinicUiState.registerLookup.query || '').trim().toLowerCase();
        const patients = Array.isArray(clinicUiState.registerLookup.patients) ? clinicUiState.registerLookup.patients : [];
        const encounters = Array.isArray(clinicUiState.registerLookup.encounters) ? clinicUiState.registerLookup.encounters : [];
        const showAll = !!clinicUiState.registerLookup.showAll;
        const byPatient = {};
        encounters.forEach((enc) => {
            const pid = String(enc?.patient_id || '');
            if (!pid) return;
            const prev = byPatient[pid];
            if (!prev || String(enc.created_at || '') > String(prev.created_at || '')) byPatient[pid] = enc;
        });
        return patients
            .filter((p) => {
                if (!q) return true;
                const hay = [p?.first_name, p?.last_name, p?.phone].map((x) => String(x || '').toLowerCase()).join(' ');
                return hay.includes(q);
            })
            .map((p) => {
                const encounter = byPatient[String(p.id)] || null;
                const status = String(encounter?.status || '');
                const isActive = status === 'waiting' || status === 'in_consultation';
                const hasEncounter = !!encounter?.id;
                const isReadOnly = !hasEncounter || !isActive;
                return { patient: p, encounter: encounter, isActive: isActive, isReadOnly: isReadOnly };
            })
            .filter((row) => showAll || row.isActive)
            .sort((a, b) => {
                const sa = String(a?.encounter?.status || '');
                const sb = String(b?.encounter?.status || '');
                const rank = (s) => (s === 'waiting' ? 3 : s === 'in_consultation' ? 2 : s === 'completed' ? 1 : 0);
                if (rank(sb) !== rank(sa)) return rank(sb) - rank(sa);
                return String(b?.encounter?.created_at || '').localeCompare(String(a?.encounter?.created_at || ''));
            })
            .slice(0, 12);
    }

    function renderEmbeddedRegisterLookup(station, currentEncounterId) {
        const loading = clinicUiState.registerLookup.loading;
        const err = clinicUiState.registerLookup.error;
        const rows = getRegisterLookupRows().sort(function (a, b) {
            if (a.isActive !== b.isActive) return a.isActive ? -1 : 1;
            return 0;
        });
        const rowsHtml = loading
            ? '<div class="text-secondary" style="padding:1rem; text-align:center;"><i class="fas fa-spinner fa-spin" aria-hidden="true"></i> Loading register…</div>'
            : err
                ? '<div class="text-danger" style="padding:0.5rem;">' + escapeHtml(err) + '</div>'
                : rows.length === 0
                    ? '<div class="text-secondary" style="padding:0.5rem;">No matching patients for current mode.</div>'
                    : rows.map((r) => {
                        const p = r.patient || {};
                        const e = r.encounter || {};
                        const isReadOnly = !!r.isReadOnly;
                        const current = currentEncounterId && String(e.id || '') === String(currentEncounterId) ? '<span class="badge badge-success" style="font-size:0.7rem;">Current</span>' : '';
                        const readOnlyBadge = isReadOnly ? '<span class="badge" style="font-size:0.7rem; background:#eee; color:#666;">Read-only</span>' : '';
                        const rowStyle = isReadOnly ? 'opacity:0.72;' : '';
                        const actionAttrs = isReadOnly ? 'disabled aria-disabled="true" title="Only active encounters are actionable"' : '';
                        return (
                            '<button type="button" class="btn btn-outline" data-register-open="' + escapeHtml(String(e.id || '')) + '" data-register-station="' + escapeHtml(station) + '" ' + actionAttrs + ' style="display:flex; width:100%; justify-content:space-between; align-items:center; text-align:left; margin-bottom:0.25rem; ' + rowStyle + '">' +
                            '<span><strong>' + escapeHtml((p.first_name || '') + ' ' + (p.last_name || '')) + '</strong><br><small style="color:var(--text-secondary);">' + escapeHtml(p.phone || '—') + '</small></span>' +
                            '<span style="display:flex; gap:0.35rem; align-items:center;">' +
                            (e.status ? '<span class="badge badge-info" style="font-size:0.7rem;">' + escapeHtml(String(e.status)) + '</span>' : '') +
                            readOnlyBadge +
                            current +
                            '</span></button>'
                        );
                    }).join('');
        return `
            <div class="card" style="padding:0.75rem; margin-bottom:0.75rem;" id="clinicEmbeddedRegister">
                <h3 style="margin:0 0 0.5rem 0; font-size:0.95rem;">Register Lookup</h3>
                <div style="display:flex; gap:0.5rem; margin-bottom:0.5rem;">
                    <input type="text" id="clinicEmbeddedRegisterSearch" class="form-input" placeholder="Search patients from register..." value="${escapeHtml(clinicUiState.registerLookup.query || '')}" />
                    <button type="button" class="btn btn-sm btn-outline" id="clinicEmbeddedRegisterRefresh">Refresh</button>
                </div>
                <label style="display:inline-flex; align-items:center; gap:0.35rem; margin:0 0 0.5rem 0; font-size:0.85rem; color:var(--text-secondary);">
                    <input type="checkbox" id="clinicEmbeddedRegisterShowAll" ${clinicUiState.registerLookup.showAll ? 'checked' : ''} />
                    Show all (non-active are read-only)
                </label>
                <div id="clinicEmbeddedRegisterRows" style="max-height:220px; overflow:auto; border:1px solid var(--border-color); border-radius:0.45rem; padding:0.45rem;">
                    ${rowsHtml}
                </div>
            </div>
        `;
    }

    function renderReceptionCreateSection() {
        return `
            <div class="card" style="padding:1rem;">
                <h3 style="margin-top:0;">Section B — Create Patient Profile</h3>
                <div style="display:flex; flex-wrap:wrap; gap:1rem; align-items:flex-end;">
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
            </div>
        `;
    }

    function renderReceptionProfileSection(selectedPatient, recentEncounter) {
        if (!selectedPatient) {
            return `
                <div class="card" style="padding:1rem;">
                    <h3 style="margin-top:0;">Section C — Patient Profile</h3>
                    <p class="text-secondary" style="margin:0;">Select a patient from Section A to view profile details and start visit.</p>
                </div>
            `;
        }
        return `
            <div class="card" style="padding:1rem;">
                <h3 style="margin-top:0;">Section C — Patient Profile</h3>
                <p style="margin:0 0 0.5rem 0;"><strong>Name:</strong> ${escapeHtml(selectedPatient.first_name || '')} ${escapeHtml(selectedPatient.last_name || '')}</p>
                <p style="margin:0 0 0.5rem 0;"><strong>Phone:</strong> ${escapeHtml(selectedPatient.phone || '—')}</p>
                <p style="margin:0 0 0.5rem 0;"><strong>Gender:</strong> ${escapeHtml(selectedPatient.gender || '—')}</p>
                <p style="margin:0 0 0.75rem 0;"><strong>Date of birth:</strong> ${escapeHtml(selectedPatient.date_of_birth || '—')}</p>
                <p style="margin:0;"><strong>Recent encounter:</strong> ${recentEncounter ? `<code>${escapeHtml(String(recentEncounter.id).slice(0, 8))}…</code> · ${escapeHtml(recentEncounter.status || '—')}` : 'None found'}</p>
                <p class="text-secondary" style="margin:0.35rem 0 0 0; font-size:0.85rem;">Read-only summary in Phase 1.</p>
                <div style="margin-top:0.75rem;">
                    <button type="button" class="btn btn-primary" id="clinicStartVisitFromProfile" data-pid="${selectedPatient.id}">Start Visit</button>
                </div>
            </div>
        `;
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
        clinicUiState.reception.loadingPatients = true;
        clinicUiState.reception.loadError = null;
        if (!shouldApplyClinicRender('reception')) return;
        el.innerHTML = renderReceptionWorkflowSurface();
        const card = el;
            var debouncedReceptionSearch = (window.WorkstationUX && typeof window.WorkstationUX.debounce === 'function')
                ? window.WorkstationUX.debounce(function (nextQuery) {
                    clinicUiState.reception.searchQuery = nextQuery;
                    updateReceptionLocalizedView();
                }, 250)
                : function (nextQuery) {
                    clinicUiState.reception.searchQuery = nextQuery;
                    updateReceptionLocalizedView();
                };
            document.getElementById('clinicPtSearch')?.addEventListener('input', (event) => {
                debouncedReceptionSearch(event.target?.value || '');
            });
        document.getElementById('regDatePreset')?.addEventListener('change', (event) => {
            clinicUiState.reception.datePreset = event.target?.value || 'today';
            if (clinicUiState.reception.datePreset !== 'custom') {
                clinicUiState.reception.dateFrom = '';
                clinicUiState.reception.dateTo = '';
            }
            void loadClinicPatients();
        });
        document.getElementById('regDateFrom')?.addEventListener('change', (event) => {
            clinicUiState.reception.dateFrom = event.target?.value || '';
            void loadClinicPatients();
        });
        document.getElementById('regDateTo')?.addEventListener('change', (event) => {
            clinicUiState.reception.dateTo = event.target?.value || '';
            void loadClinicPatients();
        });
        document.getElementById('clinicPtSearchClear')?.addEventListener('click', () => {
            clinicUiState.reception.searchQuery = '';
            var searchInput = document.getElementById('clinicPtSearch');
            if (searchInput) searchInput.value = '';
            updateReceptionLocalizedView();
        });
        el.onclick = async (event) => {
            const selectBtn = event.target?.closest?.('[data-select-pid]');
            if (selectBtn) {
                clinicUiState.reception.selectedPatientId = selectBtn.getAttribute('data-select-pid');
                updateReceptionLocalizedView();
                return;
            }
            const editBtn = event.target?.closest?.('#clinicEditPatientBtn');
            if (editBtn) {
                clinicUiState.reception.editPatientId = editBtn.getAttribute('data-pid');
                updateReceptionLocalizedView();
                return;
            }
            const cancelEditBtn = event.target?.closest?.('#clinicCancelEditPatient');
            if (cancelEditBtn) {
                clinicUiState.reception.editPatientId = null;
                updateReceptionLocalizedView();
                return;
            }
                const openCreateBtn = event.target?.closest?.('#clinicOpenRegisterCreate');
                if (openCreateBtn) {
                    if (typeof window.loadPage === 'function') {
                        window.location.hash = '#register-new';
                        void window.loadPage('register-new');
                    } else {
                        window.location.hash = '#register-new';
                    }
                return;
            }
            const startBtn = event.target?.closest?.('#clinicStartVisitFromProfile');
            if (startBtn) {
                const btn = startBtn;
                const pid = btn?.getAttribute('data-pid');
                if (!pid) return;
                clinicUiState.reception.selectedPatientId = pid || null;
                if (btn.disabled) return;
                btn.disabled = true;
                try {
                    await startEncounterVisit(pid);
                    if (typeof window.showToast === 'function') window.showToast('Visit started', 'success');
                } catch (e) {
                    showErr(e.message || 'Could not start encounter');
                    btn.disabled = false;
                }
            }
            const saveEditBtn = event.target?.closest?.('#clinicSaveEditPatient');
            if (saveEditBtn) {
                const pid = saveEditBtn.getAttribute('data-pid');
                if (!pid) return;
                saveEditBtn.disabled = true;
                try {
                    await API.clinic.patients.update(pid, {
                        first_name: (document.getElementById('editPtFirst')?.value || '').trim(),
                        last_name: (document.getElementById('editPtLast')?.value || '').trim(),
                        phone: (document.getElementById('editPtPhone')?.value || '').trim() || null,
                        gender: (document.getElementById('editPtGender')?.value || '').trim() || null,
                        id_number: (document.getElementById('editPtIdNumber')?.value || '').trim() || null,
                        residence: (document.getElementById('editPtResidence')?.value || '').trim() || null,
                    });
                    clinicUiState.reception.editPatientId = null;
                    if (typeof window.showToast === 'function') window.showToast('Patient updated', 'success');
                    await loadClinicPatients();
                } catch (e) {
                    showErr(e.message || 'Failed to update patient');
                } finally {
                    saveEditBtn.disabled = false;
                }
                return;
            }
        };
        updateReceptionLocalizedView();
        try {
            const [list, waiting, active, done] = await Promise.all([
                API.clinic.patients.list(),
                API.clinic.encounters.list('waiting'),
                API.clinic.encounters.list('in_consultation'),
                API.clinic.encounters.list('completed'),
            ]);
            const allEncounters = []
                .concat(Array.isArray(waiting) ? waiting : [])
                .concat(Array.isArray(active) ? active : [])
                .concat(Array.isArray(done) ? done : []);
            clinicUiState.reception.patients = Array.isArray(list) ? list : [];
            clinicUiState.reception.encounterPriority = buildReceptionPatientPriority(allEncounters);
            if (!getSelectedPatient(clinicUiState.reception.patients)) {
                clinicUiState.reception.selectedPatientId = null;
            }
            clinicUiState.reception.loadingPatients = false;
            clinicUiState.reception.loadError = null;
            if (!shouldApplyClinicRender('reception')) return;
            updateReceptionLocalizedView();
        } catch (e) {
            clinicUiState.reception.loadingPatients = false;
            clinicUiState.reception.loadError = e?.message || 'Could not load patients';
            if (!shouldApplyClinicRender('reception')) return;
            updateReceptionLocalizedView();
        }
    }

    async function loadClinicRegisterCreate() {
        const el = document.getElementById('register-new') || document.getElementById('patients');
        if (!el) return;
        el.innerHTML = `
            <div style="padding:0.5rem;">
                <h2>Register New Patient</h2>
                <div class="card" style="padding:1rem;">
                    <div style="display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); gap:0.6rem;">
                        <div><label>First name *</label><input type="text" id="regFirstName" class="form-input" /></div>
                        <div><label>Last name *</label><input type="text" id="regLastName" class="form-input" /></div>
                        <div><label>Gender</label>
                            <select id="regGender" class="form-input">
                                <option value="">—</option><option value="female">Female</option><option value="male">Male</option><option value="other">Other</option>
                            </select>
                        </div>
                        <div><label>Phone</label><input type="text" id="regPhone" class="form-input" /></div>
                        <div><label>Date of birth</label><input type="date" id="regDob" class="form-input" /></div>
                        <div><label>ID number</label><input type="text" id="regIdNumber" class="form-input" /></div>
                        <div style="grid-column:span 2;"><label>Residence</label><input type="text" id="regResidence" class="form-input" /></div>
                    </div>
                    <hr style="margin:0.9rem 0;" />
                    <h3 style="margin:0 0 0.6rem 0;">Intake / Scheduling</h3>
                    <div style="display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); gap:0.6rem;">
                        <div><label>Payment mode</label>
                            <select id="regPaymentMode" class="form-input">
                                <option value="">—</option><option value="cash">Cash</option><option value="insurance">Insurance</option><option value="other">Other</option>
                            </select>
                        </div>
                        <div><label>Insurance type</label><input type="text" id="regInsurance" class="form-input" placeholder="NHIF, Jubilee, ..." /></div>
                        <div><label>Schedule date/time</label><input type="datetime-local" id="regSchedule" class="form-input" /></div>
                        <div><label>Initial destination</label>
                            <select id="regDestination" class="form-input">
                                <option value="triage">Triage</option>
                                <option value="consultation">Consultation</option>
                                <option value="pharmacy">Pharmacy</option>
                                <option value="lab">Lab</option>
                                <option value="radiology">Radiology</option>
                                <option value="procedure">Procedure</option>
                                <option value="referral">Referral</option>
                            </select>
                        </div>
                    </div>
                    <div style="margin-top:0.75rem; display:flex; gap:0.6rem; align-items:center;">
                        <label style="display:inline-flex; gap:0.35rem; align-items:center;"><input type="checkbox" id="regStartVisit" checked /> Start visit now</label>
                    </div>
                    <div style="margin-top:1rem; display:flex; gap:0.5rem;">
                        <button type="button" class="btn btn-primary" id="regSaveBtn">Save patient</button>
                        <button type="button" class="btn btn-outline" id="regCancelBtn">Back to register</button>
                    </div>
                </div>
            </div>
        `;

        document.getElementById('regCancelBtn')?.addEventListener('click', () => {
            window.location.hash = '#patients';
            if (typeof window.loadPage === 'function') void window.loadPage('patients');
        });

        document.getElementById('regSaveBtn')?.addEventListener('click', async () => {
            const btn = document.getElementById('regSaveBtn');
            if (!btn) return;
            if (btn.dataset.loading === '1') return;
            const cancelBtn = document.getElementById('regCancelBtn');
            const originalLabel = btn.textContent || 'Save patient';
            btn.dataset.loading = '1';
            btn.disabled = true;
            if (cancelBtn) cancelBtn.disabled = true;
            btn.innerHTML = '<i class="fas fa-spinner fa-spin" aria-hidden="true" style="margin-right:0.35rem;"></i>Saving...';
            try {
                const first_name = (document.getElementById('regFirstName')?.value || '').trim();
                const last_name = (document.getElementById('regLastName')?.value || '').trim();
                const gender = (document.getElementById('regGender')?.value || '').trim() || null;
                const phone = (document.getElementById('regPhone')?.value || '').trim() || null;
                const date_of_birth = (document.getElementById('regDob')?.value || '').trim() || null;
                const id_number = (document.getElementById('regIdNumber')?.value || '').trim() || null;
                const residence = (document.getElementById('regResidence')?.value || '').trim() || null;

                const maybeDup = (clinicUiState.reception.patients || []).find((p) => {
                    const samePhone = String(p?.phone || '').trim() && String(p?.phone || '').trim() === String(phone || '').trim();
                    const sameName =
                        String(p?.first_name || '').trim().toLowerCase() === String(first_name || '').trim().toLowerCase() &&
                        String(p?.last_name || '').trim().toLowerCase() === String(last_name || '').trim().toLowerCase();
                    return samePhone && sameName;
                });
                if (maybeDup) {
                    throw new Error('Patient already exists with same name and phone. Use Register search and edit.');
                }
                const payment_mode = (document.getElementById('regPaymentMode')?.value || '').trim() || null;
                const insurance_scheme = (document.getElementById('regInsurance')?.value || '').trim() || null;
                const scheduledRaw = (document.getElementById('regSchedule')?.value || '').trim();
                const initial_destination = (document.getElementById('regDestination')?.value || '').trim() || 'triage';
                const start_visit = !!document.getElementById('regStartVisit')?.checked;

                const patient = await API.clinic.patients.create({
                    first_name,
                    last_name,
                    phone,
                    gender,
                    date_of_birth,
                    id_number,
                    residence,
                });

                if (start_visit) {
                    const bid = branchId();
                    if (!bid) throw new Error('Select a branch first');
                    const encounter = await API.clinic.encounters.create({
                        patient_id: patient.id,
                        branch_id: bid,
                        scheduled_for: scheduledRaw ? new Date(scheduledRaw).toISOString() : null,
                        initial_destination,
                        payment_mode,
                        insurance_scheme,
                    });
                    if (initial_destination === 'consultation') {
                        navigateToEncounterStation('consultation', encounter.id);
                    } else if (initial_destination === 'triage') {
                        navigateToEncounterStation('triage', encounter.id);
                    } else {
                        navigateToEncounterStation('queue');
                    }
                } else {
                    window.location.hash = '#patients';
                    if (typeof window.loadPage === 'function') await window.loadPage('patients');
                }
                if (typeof window.showToast === 'function') window.showToast('Patient registered successfully', 'success');
            } catch (e) {
                showErr(e.message || 'Failed to register patient');
            } finally {
                btn.dataset.loading = '0';
                btn.disabled = false;
                if (cancelBtn) cancelBtn.disabled = false;
                btn.textContent = originalLabel;
            }
        });
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

    function toIsoDateKey(value) {
        if (!value) return '';
        var d = new Date(value);
        if (Number.isNaN(d.getTime())) return '';
        var y = d.getFullYear();
        var m = String(d.getMonth() + 1).padStart(2, '0');
        var day = String(d.getDate()).padStart(2, '0');
        return y + '-' + m + '-' + day;
    }

    function nowIsoDateKey() {
        return toIsoDateKey(new Date().toISOString());
    }

    function formatDateTime(value) {
        if (!value) return '—';
        var d = new Date(value);
        if (Number.isNaN(d.getTime())) return '—';
        return d.toLocaleString();
    }

    function formatWaitingDuration(fromTs) {
        if (!fromTs) return '—';
        var start = new Date(fromTs);
        var now = new Date();
        if (Number.isNaN(start.getTime())) return '—';
        var diffMs = Math.max(0, now.getTime() - start.getTime());
        var mins = Math.floor(diffMs / 60000);
        if (mins < 1) return '<1m';
        if (mins < 60) return mins + 'm';
        var hours = Math.floor(mins / 60);
        var rem = mins % 60;
        if (hours < 24) return hours + 'h ' + rem + 'm';
        var days = Math.floor(hours / 24);
        var remHours = hours % 24;
        return days + 'd ' + remHours + 'h';
    }

    function buildQueueWorklistRows(encounters) {
        var filters = clinicUiState.queue.filters || {};
        var search = String(filters.search || '').trim().toLowerCase();
        var statusFilter = String(filters.status || 'all');
        var dateFilter = String(filters.date || '');
        return (Array.isArray(encounters) ? encounters : [])
            .filter(function (enc) {
                if (statusFilter !== 'all' && String(enc.status || '') !== statusFilter) return false;
                if (dateFilter) {
                    var key = toIsoDateKey(enc.created_at);
                    if (key !== dateFilter) return false;
                }
                if (!search) return true;
                var p = enc && enc.patient ? enc.patient : {};
                var hay = [
                    enc && enc.id,
                    enc && enc.status,
                    p && p.first_name,
                    p && p.last_name,
                    p && p.phone,
                ]
                    .map(function (x) { return String(x || '').toLowerCase(); })
                    .join(' ');
                return hay.includes(search);
            })
            .sort(function (a, b) {
                return String(b && b.created_at || '').localeCompare(String(a && a.created_at || ''));
            })
            .map(function (enc) {
                var p = enc && enc.patient ? enc.patient : {};
                var name = ((p.first_name || '') + ' ' + (p.last_name || '')).trim() || '—';
                return `
                    <tr>
                        <td><strong>${escapeHtml(name)}</strong><div style="font-size:0.8rem; color:var(--text-secondary);">${escapeHtml(p.phone || '—')}</div></td>
                        <td><span class="badge badge-info" style="font-size:0.75rem;">${escapeHtml(enc.status || '—')}</span></td>
                        <td>${escapeHtml(formatDateTime(enc.created_at))}</td>
                        <td>${escapeHtml(formatWaitingDuration(enc.created_at))}</td>
                        <td style="text-align:right;"><button type="button" class="btn btn-sm btn-primary" data-eid="${enc.id}">Open</button></td>
                    </tr>
                `;
            })
            .join('');
    }

    async function loadClinicEncounters() {
        const el = document.getElementById('encounters');
        if (!el) return;
        try {
            const [waiting, active, done] = await Promise.all([
                API.clinic.encounters.list('waiting'),
                API.clinic.encounters.list('in_consultation'),
                API.clinic.encounters.list('completed'),
            ]);
            if (!shouldApplyClinicRender('queue')) return;
            const allEncounters = []
                .concat(Array.isArray(waiting) ? waiting : [])
                .concat(Array.isArray(active) ? active : [])
                .concat(Array.isArray(done) ? done : []);
            if (!clinicUiState.queue.filters.date) {
                clinicUiState.queue.filters.date = nowIsoDateKey();
            }
            el.innerHTML = `
                <div style="padding:0.5rem;" id="clinicQueueWorklist">
                    ${renderClinicStationNav()}
                    <h2>Encounter queue</h2>
                    <div class="card" style="padding:0.75rem; margin-bottom:0.75rem;">
                        <div style="display:grid; grid-template-columns:2fr 1fr 1fr; gap:0.6rem; align-items:end;">
                            <div>
                                <label>Search patient (name / phone)</label>
                                <input type="text" id="clinicQueueSearch" class="form-input" placeholder="Type to filter…" value="${escapeHtml(clinicUiState.queue.filters.search || '')}" />
                            </div>
                            <div>
                                <label>Stage</label>
                                <select id="clinicQueueStatusFilter" class="form-input">
                                    <option value="all" ${clinicUiState.queue.filters.status === 'all' ? 'selected' : ''}>All</option>
                                    <option value="waiting" ${clinicUiState.queue.filters.status === 'waiting' ? 'selected' : ''}>Waiting</option>
                                    <option value="in_consultation" ${clinicUiState.queue.filters.status === 'in_consultation' ? 'selected' : ''}>In consultation</option>
                                    <option value="completed" ${clinicUiState.queue.filters.status === 'completed' ? 'selected' : ''}>Completed</option>
                                </select>
                            </div>
                            <div>
                                <label>Date</label>
                                <input type="date" id="clinicQueueDateFilter" class="form-input" value="${escapeHtml(clinicUiState.queue.filters.date || '')}" />
                            </div>
                        </div>
                    </div>
                    <div class="card" style="padding:0.5rem;">
                        <table class="data-table" style="width:100%;">
                            <thead>
                                <tr>
                                    <th>Patient</th>
                                    <th>Stage</th>
                                    <th>Visit time</th>
                                    <th>Waiting</th>
                                    <th style="text-align:right;">Action</th>
                                </tr>
                            </thead>
                            <tbody id="clinicQueueRows"></tbody>
                        </table>
                    </div>
                </div>`;
            var renderQueueRows = function () {
                var rowsEl = document.getElementById('clinicQueueRows');
                if (!rowsEl) return;
                var rows = buildQueueWorklistRows(allEncounters);
                rowsEl.innerHTML = rows || '<tr><td colspan="5">No encounters found for current filters.</td></tr>';
            };
            renderQueueRows();
            document.getElementById('clinicQueueSearch')?.addEventListener('input', (e) => {
                clinicUiState.queue.filters.search = String(e.target?.value || '');
                renderQueueRows();
            });
            document.getElementById('clinicQueueStatusFilter')?.addEventListener('change', (e) => {
                clinicUiState.queue.filters.status = String(e.target?.value || 'all');
                renderQueueRows();
            });
            document.getElementById('clinicQueueDateFilter')?.addEventListener('change', (e) => {
                clinicUiState.queue.filters.date = String(e.target?.value || '');
                renderQueueRows();
            });
            el.onclick = (event) => {
                const btn = event.target?.closest?.('[data-eid]');
                if (!btn) return;
                const id = btn.getAttribute('data-eid');
                const encounter = allEncounters.find((x) => String(x.id) === String(id)) || { id: id, status: 'in_consultation' };
                openEncounterStation(encounter);
            };
        } catch (e) {
            if (!shouldApplyClinicRender('queue')) return;
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
        const eid = readEncounterIdFromHash();
        if (!eid) {
            await ensureRegisterLookupData();
            if (!shouldApplyClinicRender('consultation')) return;
            el.innerHTML = `
                <div class="card" style="padding:1rem;" id="clinicConsultCard">
                    ${renderClinicStationNav()}
                    ${renderEmbeddedRegisterLookup('consultation', null)}
                    <div class="alert alert-info" style="margin-top:0.6rem;">Missing encounter id. Pick an active patient from Register Lookup.</div>
                </div>
            `;
            const card = document.getElementById('clinicConsultCard');
            card?.addEventListener('click', (event) => {
                const btn = event.target?.closest?.('[data-register-open]');
                if (!btn) return;
                const encounterId = btn.getAttribute('data-register-open');
                const station = btn.getAttribute('data-register-station') || 'consultation';
                if (!encounterId) return;
                navigateToEncounterStation(station, encounterId);
            });
            return;
        }
        try {
            await ensureRegisterLookupData();
            const enc = await API.clinic.encounters.get(eid);
            const patient = await API.clinic.patients.get(enc.patient_id);
            const notes = await API.clinic.encounters.notes.list(eid);
            const orders = await API.clinic.encounters.orders.list(eid);
            if (!shouldApplyClinicRender('consultation', eid)) return;
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
                    ${renderClinicStationNav()}
                    ${renderEmbeddedRegisterLookup('consultation', eid)}
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
            document.getElementById('clinicEmbeddedRegisterSearch')?.addEventListener('input', (event) => {
                clinicUiState.registerLookup.query = event.target?.value || '';
                const rowsHost = document.getElementById('clinicEmbeddedRegisterRows');
                if (rowsHost) {
                    const html = renderEmbeddedRegisterLookup('consultation', eid);
                    const holder = document.createElement('div');
                    holder.innerHTML = html;
                    const nextRows = holder.querySelector('#clinicEmbeddedRegisterRows');
                    if (nextRows) rowsHost.innerHTML = nextRows.innerHTML;
                }
            });
            document.getElementById('clinicEmbeddedRegisterShowAll')?.addEventListener('change', (event) => {
                clinicUiState.registerLookup.showAll = !!event.target?.checked;
                const rowsHost = document.getElementById('clinicEmbeddedRegisterRows');
                if (rowsHost) {
                    const html = renderEmbeddedRegisterLookup('consultation', eid);
                    const holder = document.createElement('div');
                    holder.innerHTML = html;
                    const nextRows = holder.querySelector('#clinicEmbeddedRegisterRows');
                    if (nextRows) rowsHost.innerHTML = nextRows.innerHTML;
                }
            });
            document.getElementById('clinicEmbeddedRegisterRefresh')?.addEventListener('click', async () => {
                await ensureRegisterLookupData({ force: true });
                await loadClinicConsultation();
            });
            card?.addEventListener('click', (event) => {
                const btn = event.target?.closest?.('[data-register-open]');
                if (!btn) return;
                const encounterId = btn.getAttribute('data-register-open');
                const station = btn.getAttribute('data-register-station') || 'consultation';
                if (!encounterId) return;
                navigateToEncounterStation(station, encounterId);
            });

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
                        await requestEncounterStatusTransition(eid, st, {
                            successMessage: 'Status updated',
                            onSuccess: loadClinicConsultation,
                        });
                    });
                } catch (err) {
                    showErr(err.message || 'Failed');
                }
            };

            document.getElementById('clinicStProg')?.addEventListener('click', function () {
                void saveStatus('in_consultation');
            });
            document.getElementById('clinicStDone')?.addEventListener('click', function () {
                void (async function () {
                    try {
                        await runBusy(async function () {
                            await completeEncounter(eid, {
                                successMessage: 'Status updated',
                                onSuccess: loadClinicConsultation,
                            });
                        });
                    } catch (err) {
                        showErr(err.message || 'Failed');
                    }
                })();
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
            if (!shouldApplyClinicRender('consultation', eid)) return;
            el.innerHTML = `<div class="card" style="padding:1rem;"><p class="text-danger">Could not load encounter. ${escapeHtml(e.message || '')}</p></div>`;
        }
    }

    async function renderTriageDepartmentSupplyWorkstation(el, tabKey) {
        var bid = branchId();
        if (!bid) {
            el.innerHTML =
                '<div class="card" style="padding:1rem;"><p class="text-danger">Branch context required for department supply.</p></div>';
            return;
        }
        if (!API.departmentSupply) {
            el.innerHTML =
                '<div class="card" style="padding:1rem;"><p class="text-danger">Department supply API missing — refresh the application.</p></div>';
            return;
        }
        var isRaise = tabKey === 'raise_order';
        var stores = [];
        try {
            stores = (await API.clinic.departmentStores.list({ branch_id: bid })) || [];
        } catch (err) {
            el.innerHTML = `<div class="card" style="padding:1rem;"><p class="text-danger">${escapeHtml(err.message || 'Could not load department stores')}</p></div>`;
            return;
        }
        var lockStoreId =
            typeof window !== 'undefined' && window.__clinicDeptStoreId ? String(window.__clinicDeptStoreId) : '';
        if (lockStoreId && (stores || []).some(function (s) { return String(s.id) === lockStoreId; })) {
            clinicUiState.triage.deptSupplySelectedStoreId = lockStoreId;
        } else if (isRaise) {
            var selectedStoreId = clinicUiState.triage.deptSupplySelectedStoreId
                ? String(clinicUiState.triage.deptSupplySelectedStoreId)
                : '';
            var selectedExists =
                selectedStoreId &&
                (stores || []).some(function (s) {
                    return String(s.id) === selectedStoreId;
                });
            if (!selectedExists) {
                var triageStore = (stores || []).find(function (s) {
                    return String(s.code || '').trim().toUpperCase() === 'TRIAGE';
                });
                if (triageStore && triageStore.id) {
                    clinicUiState.triage.deptSupplySelectedStoreId = String(triageStore.id);
                }
            }
        }
        if (triageDeptSupplyOrderTable && typeof triageDeptSupplyOrderTable.getItems === 'function') {
            try {
                var gi0 = triageDeptSupplyOrderTable.getItems();
                clinicUiState.triage.deptSupplyDraftLines = gi0.map(function (i) {
                    return {
                        item_id: i.item_id,
                        item_name: i.item_name || String(i.item_id),
                        item_code: i.item_code,
                        item_sku: i.item_sku,
                        unit_name: i.unit_name || 'piece',
                        quantity: i.quantity != null ? i.quantity : 1,
                    };
                });
            } catch (_) {}
        }
        triageDeptSupplyOrderTable = null;

        var lines = clinicUiState.triage.deptSupplyDraftLines || [];
        var storeOpts = (stores || [])
            .map(function (s) {
                var sel =
                    clinicUiState.triage.deptSupplySelectedStoreId &&
                    String(clinicUiState.triage.deptSupplySelectedStoreId) === String(s.id)
                        ? ' selected'
                        : '';
                return `<option value="${escapeHtml(String(s.id))}"${sel}>${escapeHtml(s.name || s.code)} (${escapeHtml(s.code || '')})</option>`;
            })
            .join('');
        if (!storeOpts) {
            storeOpts = '<option value="">No mini-stores for this branch</option>';
        }

        var deptTitle = deptStoreNavTitle();
        var storeSelectDisabled = lockStoreId ? ' disabled' : '';

        el.innerHTML = `
            <div class="card" style="padding:1rem;" id="clinicDeptSupplyCard">
              <h2 style="margin-top:0;">${escapeHtml(deptTitle ? deptTitle + ' · ' : '')}${isRaise ? 'Raise stock request' : 'Receive department transfers'}</h2>
              <p class="text-secondary" style="margin-top:0;">${
                  isRaise
                      ? 'Same-branch workflow — no patient encounter. Choose the department mini-store (e.g. triage), add lines, then submit. Pharmacy converts the order in <strong>Inventory → Department transfers</strong>, picks FEFO, batches, prints a packing list, and sends stock here.'
                      : 'Triage (or another office) raises an order → pharmacy turns it into a transfer draft, adjusts quantities, batches it, and prints a packing list. Pharmacy stock is deducted when the transfer is completed. When the physical package arrives with that list, load pending receipts, check quantities against the list, then confirm so stock is booked into the correct mini-store.'
              }</p>
              ${
                  isRaise
                      ? `
              <div style="margin-top:0.75rem;">
                <label>Department mini-store</label>
                <select id="deptSupplyStoreSelect" class="form-input"${storeSelectDisabled}>${storeOpts}</select>
              </div>
              ${
                  (stores || []).length
                      ? ''
                      : `<p class="text-secondary" style="margin-top:0.5rem; font-size:0.85rem;">No mini-stores for this branch yet. Ask an administrator to open <a href="#" onclick="event.preventDefault();(function(){var b=(typeof CONFIG!=='undefined'&&CONFIG.BRANCH_ID)?String(CONFIG.BRANCH_ID):'';if(b){window.location.hash='#settings-department-stores?branch='+encodeURIComponent(b);if(window.loadPage)window.loadPage('settings-department-stores');}else{window.location.hash='#settings-branches';if(window.loadPage)window.loadPage('settings-branches');}})();return false;">Settings → Branches → Dept stores</a> to create defaults (Triage, Lab, …) or custom stores.</p>`
              }
              <div style="margin-top:0.75rem;">
                <label>Add items</label>
                <p style="margin:0.15rem 0 0.35rem 0; font-size:0.8rem; color:var(--text-secondary);">Search the full item catalog (same as pharmacy). Set quantity and unit, then <strong>Add item</strong>. If pharmacy stock is insufficient, use <strong>Add to order book</strong> on a search result or from the item menu after selection — pharmacy will see it like a sales shortfall.</p>
                <div id="deptSupplyOrderTableMount" style="margin-top:0.35rem;"></div>
              </div>
              <div style="display:flex; gap:0.5rem; flex-wrap:wrap; margin-top:0.75rem;">
                <button type="button" class="btn btn-secondary" id="deptSupplySaveDraftBtn">Save draft</button>
                <button type="button" class="btn btn-primary" id="deptSupplySubmitBtn">Submit to pharmacy</button>
              </div>`
                      : `
              <div style="display:flex; gap:0.5rem; flex-wrap:wrap; align-items:center; margin-top:0.75rem;">
                <button type="button" class="btn btn-primary" id="deptSupplyLoadPendingBtn">Show pending receipts</button>
                <button type="button" class="btn btn-outline btn-sm" id="deptSupplyRefreshPendingBtn" style="display:none;">Refresh list</button>
              </div>
              <div id="deptSupplyRecvFilterWrap" style="margin-top:0.75rem; display:none;">
                <label for="deptSupplyRecvStoreFilter">Filter by destination mini-store</label>
                <select id="deptSupplyRecvStoreFilter" class="form-input"><option value="">All destinations</option></select>
              </div>
              <div id="deptSupplyPendingReceiptsMount" style="margin-top:0.75rem;"><p class="text-secondary">Click <strong>Show pending receipts</strong> to list transfers completed at pharmacy that are waiting for physical confirmation at this branch.</p></div>
              ${
                  (stores || []).length
                      ? ''
                      : '<p class="text-secondary" style="margin-top:0.75rem; font-size:0.85rem;">No department mini-stores for this branch yet. An administrator can open <a href="#" onclick="event.preventDefault();(function(){var b=(typeof CONFIG!==\'undefined\'&&CONFIG.BRANCH_ID)?String(CONFIG.BRANCH_ID):\'\';if(b){window.location.hash=\'#settings-department-stores?branch=\'+encodeURIComponent(b);if(window.loadPage)window.loadPage(\'settings-department-stores\');}else{window.location.hash=\'#settings-branches\';if(window.loadPage)window.loadPage(\'settings-branches\');}})();return false;">Settings → Branches → Dept stores</a> to add defaults or custom stores. <strong>Raise order</strong> needs a store; pending receipts can still appear if pharmacy already completed a transfer.</p>'
              }
              `
              }
            </div>`;

        var card = document.getElementById('clinicDeptSupplyCard');
        if (!card) return;

        var pendingReceiptsCache = null;

        function renderPendingReceiptsTableIntoMount(mount, list) {
            if (!mount) return;
            if (!list.length) {
                mount.innerHTML =
                    '<p class="text-secondary">No pending receipts for this branch. When pharmacy completes a department transfer for this location, it will show here for you to match against the packing list and confirm.</p>';
                return;
            }
            var rows = list
                .map(function (r) {
                    var rn = r.receipt_number || String(r.id).slice(0, 8);
                    var tn = r.transfer_number || '—';
                    var dest = r.department_store_name || '—';
                    var lineItems = (r.lines || [])
                        .map(function (ln) {
                            var nm = ln.item_name || String(ln.item_id || '');
                            var batch = ln.batch_number ? ' · batch ' + escapeHtml(String(ln.batch_number)) : '';
                            return (
                                '<li>' +
                                escapeHtml(nm) +
                                ' · qty ' +
                                escapeHtml(String(ln.quantity)) +
                                batch +
                                '</li>'
                            );
                        })
                        .join('');
                    return (
                        '<tr>' +
                        '<td style="padding:0.35rem; border-bottom:1px solid var(--border-color); vertical-align:top;">' +
                        escapeHtml(rn) +
                        '</td>' +
                        '<td style="padding:0.35rem; border-bottom:1px solid var(--border-color); vertical-align:top;">' +
                        escapeHtml(tn) +
                        '</td>' +
                        '<td style="padding:0.35rem; border-bottom:1px solid var(--border-color); vertical-align:top;">' +
                        escapeHtml(dest) +
                        '</td>' +
                        '<td style="padding:0.35rem; border-bottom:1px solid var(--border-color); vertical-align:top;">' +
                        (r.lines || []).length +
                        '</td>' +
                        '<td style="padding:0.35rem; border-bottom:1px solid var(--border-color); vertical-align:top;">' +
                        '<details style="font-size:0.85rem; max-width:22rem;"><summary style="cursor:pointer;">Line detail</summary><ul style="margin:0.35rem 0 0 1rem;padding:0;">' +
                        (lineItems || '<li>—</li>') +
                        '</ul></details>' +
                        '<button type="button" class="btn btn-sm btn-primary dept-sup-confirm-recv" style="margin-top:0.5rem;" data-receipt-id="' +
                        escapeHtml(String(r.id)) +
                        '">Confirm receipt</button>' +
                        '</td>' +
                        '</tr>'
                    );
                })
                .join('');
            mount.innerHTML =
                '<table style="width:100%; border-collapse:collapse;"><thead><tr>' +
                '<th style="text-align:left;padding:0.35rem;">Receipt</th>' +
                '<th style="text-align:left;padding:0.35rem;">Transfer</th>' +
                '<th style="text-align:left;padding:0.35rem;">Destination</th>' +
                '<th style="text-align:left;padding:0.35rem;">Lines</th>' +
                '<th style="text-align:left;padding:0.35rem;">Actions</th>' +
                '</tr></thead><tbody>' +
                rows +
                '</tbody></table>';
        }

        function applyPendingReceiptFilter() {
            var mount = document.getElementById('deptSupplyPendingReceiptsMount');
            var sel = document.getElementById('deptSupplyRecvStoreFilter');
            if (!mount || !pendingReceiptsCache) return;
            var fid = sel && sel.value ? String(sel.value) : '';
            var filtered = pendingReceiptsCache.filter(function (r) {
                return !fid || String(r.department_store_id || '') === fid;
            });
            renderPendingReceiptsTableIntoMount(mount, filtered);
        }

        function syncPendingRecvStoreFilterOptions() {
            var wrap = document.getElementById('deptSupplyRecvFilterWrap');
            var sel = document.getElementById('deptSupplyRecvStoreFilter');
            if (!wrap || !sel || !pendingReceiptsCache) return;
            var uniq = new Map();
            pendingReceiptsCache.forEach(function (r) {
                if (r.department_store_id) {
                    uniq.set(
                        String(r.department_store_id),
                        r.department_store_name || String(r.department_store_id).slice(0, 8)
                    );
                }
            });
            var prev = sel.value;
            sel.innerHTML = '<option value="">All destinations</option>';
            uniq.forEach(function (name, id) {
                var o = document.createElement('option');
                o.value = id;
                o.textContent = name;
                sel.appendChild(o);
            });
            if (prev && uniq.has(prev)) sel.value = prev;
            else sel.value = '';
            if (uniq.size > 1) {
                wrap.style.display = 'block';
            } else {
                wrap.style.display = 'none';
            }
            sel.onchange = function () {
                applyPendingReceiptFilter();
            };
        }

        async function loadAllPendingDepartmentReceipts() {
            var mount = document.getElementById('deptSupplyPendingReceiptsMount');
            var refreshBtn = document.getElementById('deptSupplyRefreshPendingBtn');
            if (!mount) return;
            mount.innerHTML = '<p class="text-secondary">Loading…</p>';
            try {
                var rows = await API.departmentSupply.listReceipts({
                    branch_id: bid,
                    status: 'PENDING',
                });
                pendingReceiptsCache = Array.isArray(rows) ? rows : [];
                if (refreshBtn) refreshBtn.style.display = 'inline-block';
                syncPendingRecvStoreFilterOptions();
                applyPendingReceiptFilter();
            } catch (err) {
                pendingReceiptsCache = null;
                mount.innerHTML = `<p class="text-danger">${escapeHtml(err.message || 'Failed to load receipts')}</p>`;
            }
        }

        if (!isRaise) {
            document.getElementById('deptSupplyLoadPendingBtn')?.addEventListener('click', function () {
                void loadAllPendingDepartmentReceipts();
            });
            document.getElementById('deptSupplyRefreshPendingBtn')?.addEventListener('click', function () {
                void loadAllPendingDepartmentReceipts();
            });
            card.addEventListener('click', async function (ev) {
                var b = ev.target && ev.target.closest && ev.target.closest('.dept-sup-confirm-recv');
                if (!b) return;
                var rid = b.getAttribute('data-receipt-id');
                if (!rid) return;
                var row = (pendingReceiptsCache || []).find(function (x) {
                    return String(x.id) === String(rid);
                });
                var destHint =
                    row && row.department_store_name
                        ? '\n\nDestination mini-store: ' + row.department_store_name + '.'
                        : '';
                if (
                    !confirm(
                        'Confirm physical receipt against the packing list? Stock will be booked into the destination mini-store.' +
                            destHint
                    )
                ) {
                    return;
                }
                try {
                    await API.departmentSupply.receiveReceipt(rid);
                    if (typeof window.showToast === 'function') window.showToast('Receipt confirmed', 'success');
                    void loadAllPendingDepartmentReceipts();
                } catch (err) {
                    showErr(err.message || 'Confirm failed');
                }
            });
            return;
        }

        var storeSel = document.getElementById('deptSupplyStoreSelect');
        storeSel?.addEventListener('change', function () {
            clinicUiState.triage.deptSupplySelectedStoreId = storeSel.value || null;
        });

        function getDeptSupplyOrderLinesForPayload() {
            var src =
                triageDeptSupplyOrderTable && typeof triageDeptSupplyOrderTable.getItems === 'function'
                    ? triageDeptSupplyOrderTable.getItems()
                    : clinicUiState.triage.deptSupplyDraftLines || [];
            return (src || []).map(function (r) {
                return {
                    item_id: r.item_id,
                    unit_name: (r.unit_name || 'piece').trim() || 'piece',
                    quantity: Number(r.quantity) || 0,
                };
            });
        }

        var mountOrder = document.getElementById('deptSupplyOrderTableMount');
        if (mountOrder && typeof window.TransactionItemsTable === 'function') {
            mountOrder.innerHTML = '';
            var seedItems = lines.map(function (r) {
                return {
                    item_id: r.item_id,
                    item_name: r.item_name || String(r.item_id),
                    item_code: r.item_code || r.item_sku || '',
                    item_sku: r.item_sku || r.item_code || '',
                    unit_name: (r.unit_name || 'piece').trim() || 'piece',
                    quantity: parseFloat(r.quantity) || 1,
                    unit_price: 0,
                    total: 0,
                    is_empty: false,
                };
            });
            triageDeptSupplyOrderTable = new window.TransactionItemsTable({
                mountEl: mountOrder,
                mode: 'department_supply',
                useAddRow: true,
                canEdit: true,
                mergeAddRowDuplicates: true,
                items: seedItems,
                onItemsChange: function (validItems) {
                    clinicUiState.triage.deptSupplyDraftLines = (validItems || []).map(function (i) {
                        return {
                            item_id: i.item_id,
                            item_name: i.item_name || String(i.item_id),
                            item_code: i.item_code,
                            item_sku: i.item_sku,
                            unit_name: i.unit_name || 'piece',
                            quantity: i.quantity != null ? i.quantity : 1,
                        };
                    });
                },
                onAddItem: function (item) {
                    if (!triageDeptSupplyOrderTable) return;
                    var items = triageDeptSupplyOrderTable.getItems().slice();
                    var merged = false;
                    for (var i = 0; i < items.length; i++) {
                        if (
                            String(items[i].item_id) === String(item.item_id) &&
                            (items[i].unit_name || '').trim() === (item.unit_name || '').trim()
                        ) {
                            items[i].quantity =
                                (parseFloat(items[i].quantity) || 0) + (parseFloat(item.quantity) || 1);
                            merged = true;
                            break;
                        }
                    }
                    if (!merged) {
                        items.push({
                            item_id: item.item_id,
                            item_name: item.item_name,
                            item_code: item.item_code || item.item_sku || '',
                            item_sku: item.item_sku || item.item_code || '',
                            unit_name: (item.unit_name || 'piece').trim() || 'piece',
                            quantity: item.quantity || 1,
                            unit_price: 0,
                            total: 0,
                            is_empty: false,
                        });
                    }
                    triageDeptSupplyOrderTable.setItems(items, { focusNewRowQty: true });
                    triageDeptSupplyOrderTable.addRowItem = null;
                    triageDeptSupplyOrderTable.editingRowIndex = null;
                    triageDeptSupplyOrderTable.render();
                    triageDeptSupplyOrderTable.attachEventListeners();
                },
            });
        } else if (mountOrder) {
            mountOrder.innerHTML =
                '<p class="text-danger" style="margin:0;">Items table is unavailable. Refresh the page.</p>';
        }

        document.getElementById('deptSupplySaveDraftBtn')?.addEventListener('click', async function () {
            var sid = document.getElementById('deptSupplyStoreSelect')?.value;
            if (!sid) {
                showErr('Select a department mini-store');
                return;
            }
            var payloadLines = getDeptSupplyOrderLinesForPayload();
            if (!payloadLines.length) {
                showErr('Add at least one line');
                return;
            }
            var payload = {
                department_store_id: sid,
                notes: null,
                lines: payloadLines,
            };
            if (payload.lines.some(function (l) { return l.quantity <= 0; })) {
                showErr('Quantities must be greater than zero');
                return;
            }
            try {
                await API.departmentSupply.createOrder(payload);
                if (typeof window.showToast === 'function') window.showToast('Draft order saved', 'success');
                triageDeptSupplyOrderTable = null;
                clinicUiState.triage.deptSupplyDraftLines = [];
                void renderTriageDepartmentSupplyWorkstation(el, tabKey);
            } catch (err) {
                showErr(err.message || 'Save failed');
            }
        });

        document.getElementById('deptSupplySubmitBtn')?.addEventListener('click', async function () {
            var sid = document.getElementById('deptSupplyStoreSelect')?.value;
            if (!sid) {
                showErr('Select a department mini-store');
                return;
            }
            var payloadLines = getDeptSupplyOrderLinesForPayload();
            if (!payloadLines.length) {
                showErr('Add at least one line');
                return;
            }
            var payload = {
                department_store_id: sid,
                notes: null,
                lines: payloadLines,
            };
            if (payload.lines.some(function (l) { return l.quantity <= 0; })) {
                showErr('Quantities must be greater than zero');
                return;
            }
            try {
                var created = await API.departmentSupply.createOrder(payload);
                var oid = created && created.id ? created.id : null;
                if (!oid) throw new Error('No order id returned');
                await API.departmentSupply.submitOrder(oid);
                if (typeof window.showToast === 'function') window.showToast('Order submitted to pharmacy', 'success');
                triageDeptSupplyOrderTable = null;
                clinicUiState.triage.deptSupplyDraftLines = [];
                void renderTriageDepartmentSupplyWorkstation(el, tabKey);
            } catch (err) {
                showErr(err.message || 'Submit failed');
            }
        });
    }

    async function loadClinicTriage() {
        const el = document.getElementById('triage');
        if (!el) return;
        var subFromRouter =
            typeof window !== 'undefined' && window.__clinicTriageSubPage
                ? String(window.__clinicTriageSubPage)
                : '';
        const tabFromRoute = String(
            subFromRouter
                ? subFromRouter.replace(/-/g, '_')
                : (getClinicStationSubRoute('triage', 'attend-patient') || 'attend-patient').replace(/-/g, '_')
        );
        clinicUiState.triage.activeTab = tabFromRoute;
        const triageTabEarly = String(clinicUiState.triage.activeTab || 'attend_patient');
        if (triageTabEarly === 'raise_order' || triageTabEarly === 'transfer') {
            if (!shouldApplyClinicRender('triage')) return;
            await renderTriageDepartmentSupplyWorkstation(el, triageTabEarly);
            return;
        }
        const eid = readEncounterIdFromHash();
        if (!eid) {
            await ensureRegisterLookupData();
            if (!shouldApplyClinicRender('triage')) return;
            const triageTab = String(clinicUiState.triage.activeTab || 'attend_patient');
            el.innerHTML = `
                <div class="card" style="padding:1rem;" id="clinicTriageCard">
                    ${renderEmbeddedRegisterLookup('triage', null)}
                    <div class="alert alert-info" style="margin-top:0.6rem;">
                        ${
                            triageTab === 'attend_patient'
                                ? 'Missing encounter id. Pick an active patient from Register Lookup.'
                                : 'You are in office workflow mode. These tasks can run without selecting a patient.'
                        }
                    </div>
                    <div class="card" style="padding:0.75rem; margin-top:0.6rem;">
                        ${
                            triageTab === 'attend_patient'
                                ? '<strong>Attend Patient</strong><p style="margin:0.35rem 0 0 0; color:var(--text-secondary);">Select a patient to capture triage, give service, record history, and refer.</p>'
                                : triageTab === 'raise_order'
                                    ? '<strong>Raise Order</strong><p style="margin:0.35rem 0 0 0; color:var(--text-secondary);">Create department stock/service requests and route insufficiency to order book from here.</p>'
                                    : triageTab === 'transfer'
                                        ? '<strong>Transfer</strong><p style="margin:0.35rem 0 0 0; color:var(--text-secondary);">Manage inter-office handoffs and movement requests as part of triage office workflow.</p>'
                                        : '<strong>Manage Assets</strong><p style="margin:0.35rem 0 0 0; color:var(--text-secondary);">Handle mini-store assets/consumables, refills, returns, and reconciliation controls.</p>'
                        }
                    </div>
                </div>
            `;
            const card = document.getElementById('clinicTriageCard');
            card?.addEventListener('click', (event) => {
                const btn = event.target?.closest?.('[data-register-open]');
                if (!btn) return;
                const encounterId = btn.getAttribute('data-register-open');
                const station = btn.getAttribute('data-register-station') || 'triage';
                if (!encounterId) return;
                navigateToEncounterStation(station, encounterId);
            });
            return;
        }
        try {
            await ensureRegisterLookupData();
            await ensureChiefComplaintDictionary();
            const enc = await API.clinic.encounters.get(eid);
            const patient = enc.patient ? enc.patient : await API.clinic.patients.get(enc.patient_id);
            const triage = await API.clinic.encounters.triage.get(eid);
            const orders = await API.clinic.encounters.orders.list(eid);
            if (!shouldApplyClinicRender('triage', eid)) return;
            const completed = enc.status === 'completed';
            const t = triage || {};
            const vit = t.vitals || {};
            const triageTab = String(clinicUiState.triage.activeTab || 'attend_patient');
            const complaintsOptions = (clinicUiState.triage.complaints || [])
                .map(function (c) { return `<option value="${escapeHtml(c)}"></option>`; })
                .join('');
            const pname = `${patient.first_name || ''} ${patient.last_name || ''}`.trim();
            const gender = patient.gender || '—';
            const dob = patient.date_of_birth || null;
            const intakePm = (enc.intake_payment_mode || '').trim();
            const intakeScheme = (enc.intake_insurance_scheme || '').trim();
            const registerPaymentNote =
                intakePm
                    ? `<p style="font-size:0.875rem; color:var(--text-secondary); margin:-0.35rem 0 0 0;"><strong>Payment (register):</strong> ${escapeHtml(intakePm)}${
                          intakeScheme ? ` · ${escapeHtml(intakeScheme)}` : ''
                      }</p>`
                    : '';
            el.innerHTML = `
                <div class="card" style="padding:1rem;" id="clinicTriageCard">
                    ${triageTab === 'attend_patient' ? `
                        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.5rem;">
                            <h3 style="margin:0;">Attend Patient</h3>
                            <button type="button" class="btn btn-sm btn-outline" id="triageToggleLookup">${clinicUiState.triage.showLookup ? 'Hide patient lookup' : 'Change patient'}</button>
                        </div>
                        <div id="triageLookupWrap" style="display:${clinicUiState.triage.showLookup ? 'block' : 'none'};">
                            ${renderEmbeddedRegisterLookup('triage', eid)}
                        </div>
                    ` : `
                        ${renderEmbeddedRegisterLookup('triage', eid)}
                    `}
                    <h2>${escapeHtml(deptStoreNavTitle() || 'Triage')}</h2>
                    <p><strong>Patient:</strong> ${escapeHtml(pname || '—')} · ${escapeHtml(patient.phone || '—')}</p>
                    <p style="color:var(--text-secondary); margin-top:-0.5rem;">
                        <strong>Gender:</strong> ${escapeHtml(gender)}${dob ? ` · <strong>DOB:</strong> ${escapeHtml(String(dob))}` : ''}
                    </p>
                    <p><strong>Encounter:</strong> <code>${String(enc.id).slice(0, 8)}…</code> · <strong>Status:</strong> ${escapeHtml(enc.status)}</p>
                    ${registerPaymentNote}

                    ${completed ? `<div class="alert alert-warning" style="margin:0.75rem 0;">This encounter is completed — triage cannot be edited.</div>` : ''}

                    <div style="display:${triageTab === 'attend_patient' ? 'block' : 'none'};">
                    <div style="margin-top:1rem;">
                            <label>Insurance scheme</label>
                            <input id="triageInsurance" class="form-input" placeholder="e.g. NHIF, Jubilee…" value="${escapeHtml(t.insurance_scheme || '')}" ${completed ? 'disabled' : ''} />
                    </div>

                    <div style="margin-top:1rem;">
                        <label>Chief complaint</label>
                        <input id="triageChief" list="triageChiefList" class="form-input" placeholder="e.g. Fever, headache…" value="${escapeHtml(t.chief_complaint || '')}" ${completed ? 'disabled' : ''} />
                        <datalist id="triageChiefList">${complaintsOptions}</datalist>
                    </div>
                    <div style="margin-top:0.75rem;">
                        <label>Allergies</label>
                        <input id="triageAllergies" class="form-input" placeholder="e.g. Penicillin, latex, food allergies…" value="${escapeHtml(t.allergies || '')}" ${completed ? 'disabled' : ''} />
                    </div>
                    <div style="margin-top:0.75rem;">
                        <label>Symptoms</label>
                        <textarea id="triageSymptoms" class="form-input" rows="3" placeholder="Key symptoms…" ${completed ? 'disabled' : ''}>${escapeHtml(t.symptoms || '')}</textarea>
                    </div>

                    ${
                        isClinicDeptStoreWorkstation()
                            ? `<p class="text-secondary" style="margin-top:1rem;">Vitals are recorded at <strong>Triage</strong>. This desk reuses the same encounter for orders and notes.</p>`
                            : `<h3 style="margin-top:1rem;">Vitals</h3>
                    <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap:0.75rem;">
                        <div><label>Temperature (°C)</label><input id="vTemp" class="form-input" inputmode="decimal" value="${escapeHtml(vit.temp_c || '')}" ${completed ? 'disabled' : ''} /></div>
                        <div><label>Pulse (bpm)</label><input id="vPulse" class="form-input" inputmode="numeric" value="${escapeHtml(vit.pulse_bpm || '')}" ${completed ? 'disabled' : ''} /></div>
                        <div><label>BP</label><input id="vBp" class="form-input" placeholder="120/80" value="${escapeHtml(vit.bp || '')}" ${completed ? 'disabled' : ''} /></div>
                        <div><label>Resp rate</label><input id="vResp" class="form-input" inputmode="numeric" value="${escapeHtml(vit.resp_rate || '')}" ${completed ? 'disabled' : ''} /></div>
                        <div><label>SpO₂ (%)</label><input id="vSpo2" class="form-input" inputmode="numeric" value="${escapeHtml(vit.spo2_pct || '')}" ${completed ? 'disabled' : ''} /></div>
                        <div><label>Weight (kg)</label><input id="vWt" class="form-input" inputmode="decimal" value="${escapeHtml(vit.weight_kg || '')}" ${completed ? 'disabled' : ''} /></div>
                        <div><label>Height (cm)</label><input id="vHt" class="form-input" inputmode="decimal" value="${escapeHtml(vit.height_cm || '')}" ${completed ? 'disabled' : ''} /></div>
                    </div>`
                    }

                    <div style="margin-top:0.75rem;">
                        <label>Triage notes</label>
                        <textarea id="triageNotes" class="form-input" rows="3" placeholder="Extra notes…" ${completed ? 'disabled' : ''}>${escapeHtml(t.triage_notes || '')}</textarea>
                    </div>

                    <h3 style="margin-top:1rem;">Services rendered (billing)</h3>
                    <p style="color:var(--text-secondary); font-size:0.875rem; margin-top:-0.25rem;">
                        Search and add clinical services (e.g. dressing, injection, nebulization, cannulation, vitals check, first aid).
                    </p>
                    <div style="display:flex; gap:0.5rem; flex-wrap:wrap; margin-bottom:0.5rem; align-items:flex-end;">
                        <div style="min-width:260px; flex:1;">
                            <label style="font-size:0.8rem; color:var(--text-secondary);">Search service</label>
                            <input type="text" id="triageServiceSearch" class="form-input" placeholder="Type service name..." value="${escapeHtml(clinicUiState.triage.serviceSearchQuery || '')}" ${completed ? 'disabled' : ''} />
                        </div>
                        <button type="button" class="btn btn-secondary btn-sm" id="triageAddServiceBtn" ${completed ? 'disabled' : ''}>Add selected service</button>
                    </div>
                    <div id="triageServiceResults" style="max-height:140px; overflow:auto; border:1px solid var(--border-color); border-radius:0.4rem; padding:0.35rem; margin-bottom:0.5rem;">
                        ${(clinicUiState.triage.serviceSearchResults || []).map(function (s) {
                            var sid = String(s.id || '');
                            var selected = String(clinicUiState.triage.selectedServiceId || '') === sid;
                            return '<button type="button" class="btn btn-sm ' + (selected ? 'btn-primary' : 'btn-outline') + '" data-triage-service-id="' + sid + '" style="margin:0.2rem;">' +
                                escapeHtml(s.name || 'Service') + ' · ' + escapeHtml(String(s.fee || 0)) +
                                '</button>';
                        }).join('') || '<div class="text-secondary" style="padding:0.25rem;">Type at least 2 letters to search services.</div>'}
                    </div>
                    <ul id="clinicTriageOrderList">${formatOrderList(orders)}</ul>

                    <div style="margin-top:1rem; display:flex; gap:0.5rem; flex-wrap:wrap; align-items:center;">
                        <button type="button" class="btn btn-primary" id="triageSave" ${completed ? 'disabled' : ''}>Save triage</button>
                        <button type="button" class="btn btn-outline" id="triageToConsult" ${completed ? 'disabled' : ''}>Send to consultation</button>
                        <button type="button" class="btn btn-secondary" id="triageBack">Back to queue</button>
                    </div>
                    </div>

                    <div style="display:${triageTab === 'manage_assets' ? 'block' : 'none'}; margin-top:0.75rem;">
                        <h3 style="margin-top:0;">Manage Assets</h3>
                        <p class="text-secondary" style="margin-top:0;">Department store and asset controls are being connected here next (refill, returns, reconciliation).</p>
                    </div>
                </div>
            `;

            const card = document.getElementById('clinicTriageCard');
            document.getElementById('clinicEmbeddedRegisterSearch')?.addEventListener('input', (event) => {
                clinicUiState.registerLookup.query = event.target?.value || '';
                const rowsHost = document.getElementById('clinicEmbeddedRegisterRows');
                if (rowsHost) {
                    const html = renderEmbeddedRegisterLookup('triage', eid);
                    const holder = document.createElement('div');
                    holder.innerHTML = html;
                    const nextRows = holder.querySelector('#clinicEmbeddedRegisterRows');
                    if (nextRows) rowsHost.innerHTML = nextRows.innerHTML;
                }
            });
            document.getElementById('triageToggleLookup')?.addEventListener('click', () => {
                clinicUiState.triage.showLookup = !clinicUiState.triage.showLookup;
                void loadClinicTriage();
            });
            document.getElementById('triageServiceSearch')?.addEventListener('input', async (event) => {
                await searchTriageServices(event.target?.value || '');
                await loadClinicTriage();
            });
            document.getElementById('clinicEmbeddedRegisterShowAll')?.addEventListener('change', (event) => {
                clinicUiState.registerLookup.showAll = !!event.target?.checked;
                const rowsHost = document.getElementById('clinicEmbeddedRegisterRows');
                if (rowsHost) {
                    const html = renderEmbeddedRegisterLookup('triage', eid);
                    const holder = document.createElement('div');
                    holder.innerHTML = html;
                    const nextRows = holder.querySelector('#clinicEmbeddedRegisterRows');
                    if (nextRows) rowsHost.innerHTML = nextRows.innerHTML;
                }
            });
            document.getElementById('clinicEmbeddedRegisterRefresh')?.addEventListener('click', async () => {
                await ensureRegisterLookupData({ force: true });
                await loadClinicTriage();
            });
            card?.addEventListener('click', (event) => {
                const btn = event.target?.closest?.('[data-register-open]');
                if (!btn) return;
                const encounterId = btn.getAttribute('data-register-open');
                const station = btn.getAttribute('data-register-station') || 'triage';
                if (!encounterId) return;
                navigateToEncounterStation(station, encounterId);
            });
            const runBusy = async function (fn) {
                setButtonsDisabled(card, true);
                try {
                    await fn();
                } finally {
                    setButtonsDisabled(card, false);
                }
            };

            const collectVitals = () => {
                if (isClinicDeptStoreWorkstation()) return t.vitals || {};
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
                const payment_mode = (t.payment_mode || '').trim() || null;
                const insurance_scheme = (document.getElementById('triageInsurance')?.value || '').trim() || null;
                const chief_complaint = (document.getElementById('triageChief')?.value || '').trim() || null;
                const allergies = (document.getElementById('triageAllergies')?.value || '').trim() || null;
                const symptoms = (document.getElementById('triageSymptoms')?.value || '').trim() || null;
                const triage_notes = (document.getElementById('triageNotes')?.value || '').trim() || null;
                const vitals = collectVitals();
                if (chief_complaint) {
                    void persistChiefComplaintTerm(chief_complaint);
                }
                return {
                    payment_mode,
                    insurance_scheme,
                    chief_complaint,
                    allergies,
                    symptoms,
                    triage_notes,
                    vitals,
                };
            };

            document.getElementById('triageSave')?.addEventListener('click', async () => {
                try {
                    await runBusy(async () => {
                        await API.clinic.encounters.triage.upsert(eid, await save());
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
                        await sendEncounterToConsultation(eid, await save());
                    });
                } catch (e) {
                    showErr(e.message || 'Failed');
                }
            });
            document.getElementById('triageBack')?.addEventListener('click', () => {
                navigateToEncounterStation('queue');
            });

            el.querySelectorAll('[data-triage-service-id]').forEach(function (b) {
                b.addEventListener('click', function () {
                    clinicUiState.triage.selectedServiceId = b.getAttribute('data-triage-service-id');
                    void loadClinicTriage();
                });
            });
            document.getElementById('triageAddServiceBtn')?.addEventListener('click', async function () {
                const sid = clinicUiState.triage.selectedServiceId;
                if (!sid) {
                    showErr('Select a service first');
                    return;
                }
                try {
                    await runBusy(async function () {
                        await API.clinic.encounters.orders.create(eid, {
                            order_type: 'procedure',
                            items: [{ reference_type: 'service', reference_id: sid, quantity: 1 }],
                        });
                        if (typeof window.showToast === 'function') window.showToast('Service added', 'success');
                        await loadClinicTriage();
                    });
                } catch (err) {
                    showErr(err.message || 'Failed to add service');
                }
            });
        } catch (e) {
            if (!shouldApplyClinicRender('triage', eid)) return;
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
    window.loadClinicRegisterCreate = loadClinicRegisterCreate;
    window.loadClinicEncounters = loadClinicEncounters;
    window.loadClinicTriage = loadClinicTriage;
    window.loadClinicConsultation = loadClinicConsultation;
    window.renderClinicPageSpinner = renderClinicPageSpinner;
})();
