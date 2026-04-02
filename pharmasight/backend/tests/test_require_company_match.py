"""Unit tests for require_company_match (company_id isolation helper)."""
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.dependencies import require_company_match


def test_require_company_match_same_company_ok():
    cid = uuid4()
    require_company_match(cid, cid)


def test_require_company_match_different_company_403():
    with pytest.raises(HTTPException) as exc:
        require_company_match(uuid4(), uuid4())
    assert exc.value.status_code == 403


def test_require_company_match_none_user_company_403():
    with pytest.raises(HTTPException) as exc:
        require_company_match(uuid4(), None)
    assert exc.value.status_code == 403


def test_require_company_match_none_resource_403():
    with pytest.raises(HTTPException) as exc:
        require_company_match(None, uuid4())
    assert exc.value.status_code == 403
