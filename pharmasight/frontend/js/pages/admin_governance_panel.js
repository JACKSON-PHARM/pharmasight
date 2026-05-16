/**
 * Governance mission control UI for admin.html platform licensing.
 */

export const OPERATING_MODEL_META = {
    PHARMACY_RETAIL: { title: 'Pharmacy retail', hint: 'Retail counter fiscal spine' },
    OUTPATIENT_CLINIC: { title: 'Outpatient clinic', hint: 'Encounter-first billing' },
    HYBRID_HOSPITAL: { title: 'Hybrid hospital', hint: 'Per-branch doctrine' },
    ENTERPRISE_NETWORK: { title: 'Enterprise network', hint: 'Broad capabilities' },
};

function doctrineLabel(v) {
    return v === 'ENCOUNTER_CONSOLIDATED' ? 'Encounter consolidated' : 'Retail counter';
}

export function renderGovernanceProblems(problems, esc) {
    if (!problems || !problems.length) {
        return '<p class="gov-alert gov-alert--ok">No governance problems detected.</p>';
    }
    return problems
        .map((p) => {
            const sev = (p.severity || 'info').toLowerCase();
            const cls = `gov-alert gov-alert--${esc(sev)}`;
            const msg = esc(p.message || p.code || '');
            return '<div class="' + cls + '">' + msg + '</div>';
        })
        .join('');
}

export function renderGovernanceOverview(gov, esc) {
    const access = gov.commercial_access || {};
    const toneColors = {
        success: '#16a34a',
        info: '#2563eb',
        warning: '#b45309',
        danger: '#dc2626',
        secondary: '#64748b',
    };
    const badgeColor = toneColors[access.tone] || toneColors.secondary;
    const model = gov.organization_operating_model || '-';
    const modelLabel = gov.operating_model_label || model;
    const modules = gov.module_entitlements?.effective || {};
    const enabledMods = Object.keys(modules).filter((k) => modules[k]);
    const constObs = gov.constitutional_observability || {};
    const txCount = constObs.commercial_transaction_count ?? 0;
    const legacy = access.uses_legacy_fallback ? ' - legacy' : '';
    const modSummary = enabledMods.slice(0, 6).join(', ') || 'none';
    const modEllipsis = enabledMods.length > 6 ? '-' : '';

    const parts = [];
    parts.push('<section class="gov-mission-control">');
    parts.push('<div class="gov-mc-header">');
    parts.push('<div><h2 class="gov-mc-title">' + esc(gov.company_name || 'Company') + '</h2>');
    parts.push('<p class="gov-mc-sub"><code>' + esc(gov.company_id) + '</code></p></div>');
    parts.push(
        '<span class="gov-access-badge" style="border-color:' +
            badgeColor +
            ';color:' +
            badgeColor +
            '">' +
            esc(access.label || '-') +
            legacy +
            '</span>'
    );
    parts.push('</div>');
    parts.push('<div class="gov-mc-grid">');
    parts.push('<div class="gov-card"><div class="gov-card-label">Operating model</div>');
    parts.push('<div class="gov-card-value">' + esc(modelLabel) + '</div>');
    parts.push('<div class="gov-card-meta">' + esc(model) + '</div></div>');
    parts.push('<div class="gov-card"><div class="gov-card-label">Commercial</div>');
    parts.push('<div class="gov-card-value">' + esc(gov.subscription_status || '-') + '</div>');
    parts.push('<div class="gov-card-meta">Plan ' + esc(gov.subscription_plan || '-') + '</div></div>');
    parts.push('<div class="gov-card"><div class="gov-card-label">Capabilities</div>');
    parts.push('<div class="gov-card-value">' + String(enabledMods.length) + '</div>');
    parts.push('<div class="gov-card-meta">' + esc(modSummary) + modEllipsis + '</div></div>');
    parts.push('<div class="gov-card"><div class="gov-card-label">Constitutional spine</div>');
    parts.push('<div class="gov-card-value">' + esc(String(txCount)) + '</div>');
    parts.push('<div class="gov-card-meta">commercial transactions</div></div>');
    parts.push('</div>');
    parts.push('<div class="gov-problems-wrap">' + renderGovernanceProblems(gov.governance_problems, esc) + '</div>');
    parts.push('</section>');
    return parts.join('');
}

export function renderOperatingModelPresets(gov, esc) {
    const current = (gov.organization_operating_model || '').toUpperCase();
    const models = gov.available_operating_models || [];
    const cards = models
        .map((m) => {
            const meta = OPERATING_MODEL_META[m.value] || { title: m.label, hint: m.description };
            const on = current === m.value;
            const active = on ? ' gov-preset-card--active' : '';
            const cur = on ? '<span class="gov-preset-current">Active</span>' : '';
            return (
                '<button type="button" class="gov-preset-card' +
                active +
                '" data-gov-preset="' +
                esc(m.value) +
                '">' +
                '<div class="gov-preset-title">' +
                esc(meta.title || m.label) +
                '</div>' +
                '<div class="gov-preset-hint">' +
                esc(meta.hint || m.description || '') +
                '</div>' +
                cur +
                '</button>'
            );
        })
        .join('');
    return (
        '<section class="gov-section">' +
        '<h3 class="gov-section-title">Operating model</h3>' +
        '<p class="gov-section-desc">Parent organizational doctrine. Applying a preset compiles licensed modules and HQ branch fiscal doctrine.</p>' +
        '<div class="gov-preset-grid">' +
        cards +
        '</div>' +
        '<label class="gov-check" style="margin-top:10px;">' +
        '<input type="checkbox" id="gov-apply-modules" checked /> Compile modules + HQ doctrine when applying preset' +
        '</label></section>'
    );
}

export function renderBranchGovernanceTable(gov, esc) {
    const branches = gov.branch_governance || [];
    if (!branches.length) {
        return '<p class="gov-section-desc">No branches.</p>';
    }
    const rows = branches
        .map((b) => {
            const warn =
                b.governance_warnings && b.governance_warnings.length
                    ? '<div class="gov-branch-warn">' + esc(b.governance_warnings.join(' ')) + '</div>'
                    : '';
            const hq = b.is_hq ? ' <span class="gov-tag">HQ</span>' : '';
            return (
                '<tr data-gov-branch="' +
                esc(b.branch_id) +
                '">' +
                '<td>' +
                esc(b.name) +
                hq +
                '<br><code>' +
                esc(b.code) +
                '</code></td>' +
                '<td><select class="gov-branch-doctrine" data-branch-id="' +
                esc(b.branch_id) +
                '">' +
                '<option value="RETAIL_COUNTER"' +
                (b.invoice_workflow_type === 'RETAIL_COUNTER' ? ' selected' : '') +
                '>Retail counter</option>' +
                '<option value="ENCOUNTER_CONSOLIDATED"' +
                (b.invoice_workflow_type === 'ENCOUNTER_CONSOLIDATED' ? ' selected' : '') +
                '>Encounter consolidated</option>' +
                '</select>' +
                warn +
                '</td>' +
                '<td><button type="button" class="btn btn-secondary btn-sm gov-save-doctrine" data-branch-id="' +
                esc(b.branch_id) +
                '">Save</button></td>' +
                '</tr>'
            );
        })
        .join('');
    return (
        '<section class="gov-section">' +
        '<h3 class="gov-section-title">Branch governance</h3>' +
        '<p class="gov-section-desc">Fiscal doctrine per branch (capabilities do not imply doctrine).</p>' +
        '<table class="gov-branch-table"><thead><tr><th>Branch</th><th>Fiscal doctrine</th><th></th></tr></thead><tbody>' +
        rows +
        '</tbody></table></section>'
    );
}

export function wireGovernancePanel(mount, api, companyId, toast, reload) {
    mount.querySelectorAll('[data-gov-preset]').forEach((btn) => {
        btn.addEventListener('click', async () => {
            const model = btn.getAttribute('data-gov-preset');
            const apply = !!document.getElementById('gov-apply-modules')?.checked;
            try {
                if (apply && typeof api.applyGovernancePreset === 'function') {
                    await api.applyGovernancePreset(companyId, {
                        operating_model: model,
                        apply_modules: true,
                        apply_hq_doctrine: true,
                    });
                } else if (typeof api.patchOperatingModel === 'function') {
                    await api.patchOperatingModel(companyId, {
                        organization_operating_model: model,
                        apply_preset: apply,
                    });
                } else {
                    throw new Error('Governance API not available');
                }
                toast('Operating model updated', 'success');
                await reload();
            } catch (e) {
                toast(e.message || 'Failed', 'error');
            }
        });
    });

    mount.querySelectorAll('.gov-save-doctrine').forEach((btn) => {
        btn.addEventListener('click', async () => {
            const branchId = btn.getAttribute('data-branch-id');
            const row = mount.querySelector(`tr[data-gov-branch="${branchId}"]`);
            const sel = row?.querySelector('.gov-branch-doctrine');
            const doctrine = sel?.value;
            if (!branchId || !doctrine) return;
            try {
                if (typeof api.patchBranchFiscalDoctrine !== 'function') {
                    throw new Error('Branch doctrine API not available');
                }
                await api.patchBranchFiscalDoctrine(branchId, { invoice_workflow_type: doctrine });
                toast('Branch doctrine saved', 'success');
                await reload();
            } catch (e) {
                toast(e.message || 'Failed', 'error');
            }
        });
    });
}
