"""
Runtime guards: tenant registry must always reference a company (Option B).

Used on the central auth path so broken tenant↔company linkage cannot be silently ignored.
"""
from __future__ import annotations

from typing import Any, Optional
from uuid import UUID


def assert_tenant_company_link(tenant: Any) -> None:
    """Require a resolved tenant row with a populated company_id."""
    if tenant is None:
        raise RuntimeError("Missing tenant resolution")
    cid = getattr(tenant, "company_id", None)
    if cid is None:
        raise RuntimeError(
            f"BROKEN STATE: Tenant {getattr(tenant, 'id', '?')} has no company_id"
        )


def assert_effective_company_matches_tenant(
    tenant: Any, effective_company_id: Optional[UUID]
) -> None:
    """After user resolution, effective company must match the tenant's linked company."""
    assert_tenant_company_link(tenant)
    if effective_company_id is None:
        raise RuntimeError("AUTH DESYNC: missing effective company for tenant-linked session")
    if str(getattr(tenant, "company_id", "")) != str(effective_company_id):
        raise RuntimeError(
            "AUTH DESYNC: tenant-company mismatch "
            f"tenant.company_id={tenant.company_id!s} effective_company_id={effective_company_id!s}"
        )


def assert_jwt_company_claim_matches_tenant(tenant: Any, company_id_claim: str) -> None:
    """When JWT carries company_id, it must agree with the registry row."""
    claim = (company_id_claim or "").strip()
    if not claim:
        return
    assert_tenant_company_link(tenant)
    if str(getattr(tenant, "company_id", "")) != claim:
        raise RuntimeError(
            "AUTH DESYNC: JWT company_id does not match tenant.company_id "
            f"jwt={claim!r} tenant.company_id={getattr(tenant, 'company_id', None)!r}"
        )
