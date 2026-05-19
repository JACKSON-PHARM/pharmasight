"""Tests for organization slug / company resolution."""
from types import SimpleNamespace

from app.services.company_context import (
    build_org_login_url,
    normalize_org_slug,
    org_slug_from_request,
)


def test_normalize_org_slug():
    assert normalize_org_slug("  Pharmasight-Meds  ") == "pharmasight-meds"
    assert normalize_org_slug("__default__") is None
    assert normalize_org_slug("") is None


def test_org_slug_from_request_query():
    req = SimpleNamespace(
        headers={},
        query_params={"org": "acme-pharmacy-9c71915e3e"},
    )
    assert org_slug_from_request(req) == "acme-pharmacy-9c71915e3e"


def test_build_org_login_url():
    url = build_org_login_url("acme-co", base_url="https://pharmasight.onrender.com")
    assert url == "https://pharmasight.onrender.com/app?org=acme-co#login"


