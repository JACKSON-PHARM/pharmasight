/**
 * Human-readable labels for governed finance (doctrine stays internal).
 */
(function (global) {
    const EVENT_LABELS = {
        receivable_accrued: 'Invoice recognized',
        receivable_accrued_reversal: 'Invoice recognition reversed',
        cash_received: 'Customer payment received',
        cash_received_reversal: 'Customer payment reversed',
        payable_recognized: 'Supplier invoice recognized',
        payable_recognized_reversal: 'Supplier invoice reversed',
        cash_paid: 'Supplier payment sent',
        cash_paid_reversal: 'Supplier payment reversed',
        insurance_claim_recognized: 'Insurance claim recognized',
        insurance_claim_recognized_reversal: 'Insurance claim reversed',
        retail_cash_collected: 'Retail sale collected',
        retail_cash_collected_reversal: 'Retail collection reversed',
        insurance_settlement_received: 'Insurance settlement received',
        insurance_settlement_received_reversal: 'Insurance settlement reversed',
        expense_recognized: 'Expense recognized',
        expense_recognized_reversal: 'Expense reversed',
    };

    const DOMAIN_LABELS = {
        wholesale: 'Sales & wholesale',
        procurement: 'Purchases',
        hospital: 'Insurance & hospital',
        operations: 'Operations',
    };

    const SOURCE_ENTITY_LABELS = {
        sales_invoice: 'Sales invoice',
        customer_payment: 'Customer payment',
        supplier_invoice: 'Supplier invoice',
        supplier_payment: 'Supplier payment',
        insurance_claim: 'Insurance claim',
        insurance_settlement: 'Insurance settlement',
        expense: 'Expense',
    };

    const DIRECTION_LABELS = {
        inflow: 'Money in',
        outflow: 'Money out',
        accrual: 'Amount recognized',
        reduction: 'Reduction',
        adjustment: 'Adjustment',
    };

    const SETTLEMENT_SEMANTIC_LABELS = {
        payment_applied: 'Applied payment',
        settlement: 'Settlement',
        allocation: 'Allocation',
        write_off: 'Write-off',
    };

    const PROPOSAL_STATUS_LABELS = {
        draft: 'Draft',
        approved: 'Approved',
        posted: 'Posted',
        superseded: 'Superseded',
    };

    const LEGITIMACY_LABELS = {
        historical_legacy_record: 'Historical legacy',
        backfill_eligible: 'Backfill eligible',
        active_operational_bypass: 'Active bypass',
        replay_pending: 'Replay pending',
        unsupported_workflow: 'Unsupported workflow',
        manual_adjustment: 'Manual adjustment',
        semantic_mismatch: 'Semantic mismatch',
        matched_governed: 'Governed match',
        lineage_ahead_of_cashbook: 'Lineage ahead of cashbook',
    };

    const DRIFT_LABELS = {
        matched: 'Matched',
        timing_drift: 'Timing difference',
        classification_mismatch: 'Classification mismatch',
        amount_mismatch: 'Amount mismatch',
        missing_event_emission: 'Missing lineage event',
        orphan_lineage_record: 'Lineage without cashbook',
        replay_inconsistency: 'Replay inconsistency',
        settlement_timing_variance: 'Settlement timing variance',
        totals_mismatch: 'Period totals differ',
    };

    const PROJECTION_LABELS = {
        branch_cash_movement: 'Branch cash movement',
        ar_recognized_vs_collected: 'Receivables: recognized vs collected',
        insurance_claim_exposure: 'Insurance claim exposure',
        lineage_integrity_summary: 'Lineage integrity summary',
        treasury_routing_snapshot: 'Treasury routing movement',
        settlement_graph_health: 'Settlement graph health',
    };

    function eventLabel(eventType) {
        if (!eventType) return '—';
        return EVENT_LABELS[eventType] || eventType.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
    }

    function domainLabel(domain) {
        return DOMAIN_LABELS[domain] || domain || '—';
    }

    function sourceEntityLabel(t) {
        return SOURCE_ENTITY_LABELS[t] || (t || '—').replace(/_/g, ' ');
    }

    function directionLabel(d) {
        return DIRECTION_LABELS[d] || d || '—';
    }

    function settlementSemanticLabel(s) {
        return SETTLEMENT_SEMANTIC_LABELS[s] || (s || 'Settlement').replace(/_/g, ' ');
    }

    function proposalStatusLabel(s) {
        return PROPOSAL_STATUS_LABELS[s] || s || '—';
    }

    function projectionLabel(id) {
        return PROJECTION_LABELS[id] || id || '—';
    }

    function driftLabel(driftType) {
        return DRIFT_LABELS[driftType] || (driftType || '—').replace(/_/g, ' ');
    }

    function legitimacyLabel(category) {
        return LEGITIMACY_LABELS[category] || (category || '—').replace(/_/g, ' ');
    }

    global.FinanceOpsLabels = {
        eventLabel,
        domainLabel,
        sourceEntityLabel,
        directionLabel,
        settlementSemanticLabel,
        proposalStatusLabel,
        projectionLabel,
        driftLabel,
        legitimacyLabel,
        LEGITIMACY_LABELS,
        EVENT_LABELS,
        PROJECTION_LABELS,
        DRIFT_LABELS,
    };
})(typeof window !== 'undefined' ? window : global);
