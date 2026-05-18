"""
FastAPI dependencies for finance permission enforcement.
"""
from __future__ import annotations

from typing import Callable, Optional, Tuple
from uuid import UUID

from fastapi import Depends, HTTPException, status

from app.dependencies import get_current_user
from app.finance.governance.permissions import resolves_finance_permission
from app.models import User
from sqlalchemy.orm import Session


def require_finance_permission(
    permission_name: str,
    *,
    allow_legacy: bool = True,
    detail: Optional[str] = None,
) -> Callable[..., Tuple[User, Session]]:
    """
    Dependency factory: require explicit finance permission (with optional legacy shim).

    Does not validate branch access — combine with resolve_finance_access_context + assert_access.
    Branch-scoped permission checks pass branch_id when available in a later E2 dependency.
    """

    def _dependency(
        user_db: Tuple[User, Session] = Depends(get_current_user),
    ) -> Tuple[User, Session]:
        user, db = user_db
        if not resolves_finance_permission(
            db, user.id, permission_name, allow_legacy=allow_legacy
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=detail or f"Permission {permission_name} required",
            )
        return user_db

    return _dependency


def require_any_finance_permission(
    *permission_names: str,
    allow_legacy: bool = True,
    detail: Optional[str] = None,
) -> Callable[..., Tuple[User, Session]]:
    """Dependency: user must hold at least one of the given finance permissions."""

    def _dependency(
        user_db: Tuple[User, Session] = Depends(get_current_user),
    ) -> Tuple[User, Session]:
        user, db = user_db
        for name in permission_names:
            if resolves_finance_permission(
                db, user.id, name, allow_legacy=allow_legacy
            ):
                return user_db
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail or f"One of permissions required: {', '.join(permission_names)}",
        )

    return _dependency
