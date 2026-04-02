from __future__ import annotations

from typing import Dict, List, Tuple

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.dependencies import get_current_user
from app.dependencies import get_effective_company_id_for_user
from app.module_metadata import get_core_modules
from app.models.user import User
from app.models.company_module import CompanyModule
from app.module_registry import get_user_modules

router = APIRouter(prefix="/modules", tags=["Modules"])


@router.get("/me", response_model=Dict[str, List[str]])
def get_my_modules(user_db: Tuple[User, Session] = Depends(get_current_user)):
    """
    UI-only module visibility for the authenticated user.
    This endpoint does NOT enforce access; it only reports what modules the UI may show.
    """
    user, db = user_db
    user_rbac_modules = get_user_modules(db, user.id) or []

    company_id = get_effective_company_id_for_user(db, user)
    if company_id is None:
        # Without a resolved tenant/company, fall back to core modules only.
        allowed = set(get_core_modules(db))
        filtered = [m for m in user_rbac_modules if str(m).strip().lower() in allowed]
        return {"modules": filtered}

    # Licensed business/clinical modules from company_modules.
    rows = (
        db.query(CompanyModule.module_name)
        .filter(CompanyModule.company_id == company_id, CompanyModule.is_enabled.is_(True))
        .all()
    )
    licensed_modules = {str(r[0] or "").strip().lower() for r in (rows or []) if r and r[0]}

    # Backward compatibility: if there's no explicit pharmacy row, treat pharmacy as enabled.
    pharmacy_row = (
        db.query(CompanyModule.id)
        .filter(CompanyModule.company_id == company_id, CompanyModule.module_name == "pharmacy")
        .first()
    )
    if pharmacy_row is None:
        licensed_modules.add("pharmacy")

    allowed = set(get_core_modules(db)) | licensed_modules
    allowed = {str(x).strip().lower() for x in allowed if x}

    # Intersection: RBAC capabilities AND (core ∪ licensed)
    filtered: List[str] = []
    for m in user_rbac_modules:
        if str(m).strip().lower() in allowed:
            filtered.append(m)

    return {"modules": filtered}

