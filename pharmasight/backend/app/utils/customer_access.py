"""
Branch-scoped customer hub access (wholesale B2B + retail credit).

Company-scoped master data; operations are allowed when the session branch
doctrine matches the hub mode and the required module is licensed.
"""
from __future__ import annotations

from typing import Callable, Literal, Optional, Tuple
from uuid import UUID

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.dependencies import ensure_user_has_branch_access, get_current_user, get_effective_company_id_for_user
from app.models.company import Branch
from app.models.user import User
from app.module_enforcement import is_module_enabled_for_company
from app.services.invoice_workflow_policy import (
    RETAIL_COUNTER,
    WHOLESALE_DISTRIBUTION,
    get_invoice_workflow_type,
    normalize_invoice_workflow_type,
)

CustomerHubMode = Literal["wholesale", "retail_credit"]


def resolve_customer_hub_mode(branch: Branch | None, *, wholesale_licensed: bool) -> Optional[CustomerHubMode]:
    wf = normalize_invoice_workflow_type(getattr(branch, "invoice_workflow_type", None) if branch else None)
    if wf == WHOLESALE_DISTRIBUTION:
        if not wholesale_licensed:
            return None
        return "wholesale"
    if wf == RETAIL_COUNTER:
        return "retail_credit"
    return None


def default_sales_type_for_hub_mode(mode: CustomerHubMode) -> str:
    return "WHOLESALE" if mode == "wholesale" else "RETAIL"


def get_branch_id_from_session(
    x_branch_id: str = Header(..., alias="X-Branch-ID", description="Current branch (session context)"),
) -> UUID:
    if not (x_branch_id and str(x_branch_id).strip()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Branch-ID header is required (current branch from session).",
        )
    try:
        return UUID(str(x_branch_id).strip())
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid X-Branch-ID format.",
        )


def require_customer_hub_branch() -> Callable[..., Tuple[User, Session, UUID, CustomerHubMode]]:
    """
    Wholesale distribution branch + wholesale module, or retail counter branch (pharmacy).
    """

    def _dependency(
        user_db: Tuple[User, Session] = Depends(get_current_user),
        branch_id: UUID = Depends(get_branch_id_from_session),
    ) -> Tuple[User, Session, UUID, CustomerHubMode]:
        user, db = user_db
        company_id = get_effective_company_id_for_user(db, user)
        if company_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot resolve company for customer access",
            )
        branch = (
            db.query(Branch)
            .filter(Branch.id == branch_id, Branch.company_id == company_id)
            .first()
        )
        if not branch:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Branch not found for this company")
        ensure_user_has_branch_access(db, user.id, branch_id)

        wholesale_licensed = is_module_enabled_for_company(db, company_id, "wholesale")
        mode = resolve_customer_hub_mode(branch, wholesale_licensed=wholesale_licensed)
        if mode is None:
            wf = get_invoice_workflow_type(branch)
            if wf == WHOLESALE_DISTRIBUTION and not wholesale_licensed:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=(
                        "Wholesale fiscal doctrine is set for this branch, but the Wholesale "
                        "module is not licensed. Enable it under Admin → Licensed capabilities."
                    ),
                )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Customer management is available on Retail counter or "
                    "Wholesale distribution branches."
                ),
            )
        return user, db, branch_id, mode

    return _dependency


def get_customer_hub_mode(
    hub: Tuple[User, Session, UUID, CustomerHubMode] = Depends(require_customer_hub_branch()),
) -> CustomerHubMode:
    return hub[3]
