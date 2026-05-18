"""
Financial governance: permissions, FinanceAccessContext, registry, telemetry (E2 / E2.5).
"""

from app.finance.governance.classification import (
    ALL_CLASSIFICATIONS,
    AUDIT,
    BRANCH_FINANCE,
    CONFIDENTIAL,
    EXECUTIVE,
    MANAGEMENT,
    OPERATIONAL,
    classification_allows,
    effective_max_classification,
)
from app.finance.governance.scope import (
    ALL_VISIBILITY_SCOPES,
    AUDIT_READ,
    BRANCH,
    COMPANY,
    DEPARTMENT,
    MULTI_BRANCH,
    SELF,
    TILL,
)
from app.finance.governance.permissions import (
    FINANCE_PERMISSION_NAMES,
    LEGACY_FINANCE_PERMISSION_ALIASES,
    resolves_finance_permission,
    resolves_finance_permission_with_source,
    user_has_finance_permission,
)
from app.finance.governance.access_context import FinanceAccessContext
from app.finance.governance.context import assert_access, resolve_finance_access_context
from app.finance.governance.enforcement import assert_finance_access
from app.finance.governance.registry import (
    FINANCE_GOVERNANCE_REGISTRY,
    FinanceEndpointGovernanceSpec,
    get_governance_spec,
    introspect_registry,
)
from app.finance.governance.report_context import ReportContext
from app.finance.governance.telemetry import (
    ALL_TELEMETRY_EVENTS,
    emit_finance_governance_event,
)
from app.finance.governance.query_scope import BranchQueryScope, BranchQueryMode
from app.finance.governance.branch_access import (
    assert_finance_branch_access,
    assert_finance_branch_access_optional,
)
from app.finance.governance.access import (
    deny_unless_finance_permission,
    guard_finance_branch_query_param,
    guard_finance_report_access,
    require_finance_branch,
    resolve_finance_branch_id,
)
from app.finance.governance.dependencies import require_finance_permission
from app.finance.governance.decorators import finance_guard

__all__ = [
    "ALL_CLASSIFICATIONS",
    "ALL_TELEMETRY_EVENTS",
    "ALL_VISIBILITY_SCOPES",
    "AUDIT",
    "AUDIT_READ",
    "BRANCH",
    "BRANCH_FINANCE",
    "BranchQueryMode",
    "BranchQueryScope",
    "COMPANY",
    "CONFIDENTIAL",
    "DEPARTMENT",
    "EXECUTIVE",
    "FINANCE_GOVERNANCE_REGISTRY",
    "FINANCE_PERMISSION_NAMES",
    "FinanceAccessContext",
    "FinanceEndpointGovernanceSpec",
    "LEGACY_FINANCE_PERMISSION_ALIASES",
    "MANAGEMENT",
    "MULTI_BRANCH",
    "OPERATIONAL",
    "ReportContext",
    "SELF",
    "TILL",
    "assert_access",
    "assert_finance_access",
    "assert_finance_branch_access",
    "assert_finance_branch_access_optional",
    "classification_allows",
    "deny_unless_finance_permission",
    "effective_max_classification",
    "emit_finance_governance_event",
    "finance_guard",
    "get_governance_spec",
    "guard_finance_branch_query_param",
    "guard_finance_report_access",
    "introspect_registry",
    "require_finance_branch",
    "require_finance_permission",
    "resolve_finance_access_context",
    "resolve_finance_branch_id",
    "resolves_finance_permission",
    "resolves_finance_permission_with_source",
    "user_has_finance_permission",
]
