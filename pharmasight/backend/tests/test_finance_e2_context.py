"""
E2/E2.5: FinanceAccessContext, classification lanes, and branch query scope.
"""
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.finance.governance.classification import (
    AUDIT,
    EXECUTIVE,
    MANAGEMENT,
    OPERATIONAL,
    classification_allows,
    effective_max_classification,
)
from app.finance.governance.access_context import FinanceAccessContext
from app.finance.governance.context import assert_access
from app.finance.governance.query_scope import BranchQueryMode, resolve_branch_query_scope
from app.finance.governance.scope import effective_scope, scope_rank
from app.finance.governance.report_context import ReportContext


def test_classification_allows_business_lanes():
    assert classification_allows(MANAGEMENT, OPERATIONAL)
    assert classification_allows(MANAGEMENT, MANAGEMENT)
    assert not classification_allows(OPERATIONAL, MANAGEMENT)


def test_audit_is_orthogonal_to_executive():
    assert not classification_allows(EXECUTIVE, AUDIT)
    assert classification_allows(AUDIT, AUDIT)
    assert classification_allows(AUDIT, EXECUTIVE)
    assert classification_allows(AUDIT, MANAGEMENT)


def test_effective_max_classification_prefers_audit_lane():
    assert effective_max_classification([EXECUTIVE, MANAGEMENT, AUDIT]) == AUDIT
    assert effective_max_classification([OPERATIONAL, MANAGEMENT]) == MANAGEMENT


def test_effective_scope_widest_wins():
    assert effective_scope(["BRANCH", "COMPANY"]) == "COMPANY"
    assert effective_scope(["SELF", "TILL"]) == "TILL"
    assert scope_rank("COMPANY") > scope_rank("BRANCH")


def test_branch_ids_for_query_company_scope():
    company_id = uuid4()
    all_branches = frozenset({uuid4(), uuid4()})
    ctx = FinanceAccessContext(
        user_id=uuid4(),
        company_id=company_id,
        visibility_scope="COMPANY",
        allowed_branch_ids=all_branches,
        allowed_department_ids=None,
        max_classification=MANAGEMENT,
    )
    assert ctx.branch_ids_for_query(None) is None
    bid = next(iter(all_branches))
    assert ctx.branch_ids_for_query(bid) == frozenset({bid})


def test_branch_ids_for_query_branch_scope():
    allowed = frozenset({uuid4()})
    ctx = FinanceAccessContext(
        user_id=uuid4(),
        company_id=uuid4(),
        visibility_scope="BRANCH",
        allowed_branch_ids=allowed,
        allowed_department_ids=None,
        max_classification=OPERATIONAL,
    )
    assert ctx.branch_ids_for_query(None) == allowed


def test_empty_allowed_branch_ids_denies_query():
    ctx = FinanceAccessContext(
        user_id=uuid4(),
        company_id=uuid4(),
        visibility_scope="BRANCH",
        allowed_branch_ids=frozenset(),
        allowed_department_ids=None,
        max_classification=MANAGEMENT,
    )
    scope = ctx.resolve_branch_query_scope(None)
    assert scope.mode == BranchQueryMode.DENY_EMPTY
    assert ctx.branch_ids_for_query(None) == frozenset()


def test_assert_access_denies_classification():
    ctx = FinanceAccessContext(
        user_id=uuid4(),
        company_id=uuid4(),
        visibility_scope="BRANCH",
        allowed_branch_ids=frozenset({uuid4()}),
        allowed_department_ids=None,
        max_classification=OPERATIONAL,
    )
    with pytest.raises(HTTPException) as exc:
        assert_access(ctx, MANAGEMENT, db=None)  # type: ignore[arg-type]
    assert exc.value.status_code == 403


def test_report_context_delegates_to_access():
    ctx = FinanceAccessContext(
        user_id=uuid4(),
        company_id=uuid4(),
        visibility_scope="BRANCH",
        allowed_branch_ids=frozenset({uuid4()}),
        allowed_department_ids=None,
        max_classification=MANAGEMENT,
    )
    rc = ReportContext.from_access(ctx)
    assert rc.company_id == ctx.company_id
    assert rc.visibility_scope == ctx.visibility_scope
    assert rc.branch_ids_for_query(None) == ctx.branch_ids_for_query(None)


def test_audit_read_company_unrestricted_scope():
    allowed = frozenset({uuid4(), uuid4()})
    scope = resolve_branch_query_scope(
        visibility_scope="AUDIT_READ",
        allowed_branch_ids=allowed,
        branch_id=None,
    )
    assert scope.mode == BranchQueryMode.UNRESTRICTED_COMPANY
