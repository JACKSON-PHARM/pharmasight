"""
Company and Branch API routes
"""
import json
from fastapi import APIRouter, Depends, HTTPException, Request, status, UploadFile, File, Query
from sqlalchemy.orm import Session
from typing import Any, Dict, List, Optional
from uuid import UUID
from pathlib import Path
from pydantic import BaseModel
from app.dependencies import get_tenant_db, get_tenant_or_default, require_settings_edit, get_current_user, get_effective_company_id_for_user
from app.models.tenant import Tenant
from app.models.company import Company, Branch, BranchSetting
from app.models.settings import CompanySetting
from app.schemas.company import (
    CompanyCreate, CompanyResponse, CompanyUpdate,
    BranchCreate, BranchResponse, BranchUpdate,
    BranchSettingResponse, BranchSettingUpdate,
)
from app.services.tenant_storage_service import (
    upload_stamp,
    upload_logo,
    get_signed_url,
    BUCKET,
    ALLOWED_IMAGE_EXTENSIONS,
    MAX_IMAGE_BYTES,
    SIGNED_URL_EXPIRY_SECONDS,
)

router = APIRouter()


class CompanySettingUpdate(BaseModel):
    """Body for upserting a company setting"""
    key: str
    value: Any  # string, number, bool, or dict (stored as JSON)

# Legacy logo upload directory (used when Supabase storage not configured)
UPLOAD_DIR = Path("uploads/logos")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


# Company endpoints
@router.post("/companies", response_model=CompanyResponse, status_code=status.HTTP_201_CREATED)
def create_company(
    company: CompanyCreate,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Create a new company
    
    **IMPORTANT: This database supports only ONE company.**
    Use /api/startup endpoint for complete initialization instead.
    """
    from app.services.startup_service import StartupService
    
    # Enforce ONE COMPANY rule
    if StartupService.check_company_exists(db):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Company already exists. This database supports only ONE company. "
                   "Use /api/startup for complete initialization, or update the existing company."
        )
    
    try:
        # Use model_dump() for Pydantic v2, fallback to dict() for v1
        if hasattr(company, 'model_dump'):
            company_data = company.model_dump(exclude_none=False)
        else:
            company_data = company.dict()
        
        # Handle fiscal_start_date - convert empty string to None
        if 'fiscal_start_date' in company_data and company_data['fiscal_start_date'] == '':
            company_data['fiscal_start_date'] = None
        
        # Create company with the data
        db_company = Company(**company_data)
        db.add(db_company)
        db.flush()  # Get the ID before commit
        db.commit()
        db.refresh(db_company)
        
        # Return the database model directly - FastAPI will serialize it using the response_model
        return db_company
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        import traceback
        error_details = traceback.format_exc()
        print(f"Error creating company: {error_details}")  # Log to console/terminal
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating company: {str(e)}"
        )


@router.get("/companies", response_model=List[CompanyResponse])
def get_companies(
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """Get companies the current user has access to (via branch roles). Ensures tenant isolation."""
    user = current_user_and_db[0]
    effective_company_id = get_effective_company_id_for_user(db, user)
    if not effective_company_id:
        return []
    company = db.query(Company).filter(Company.id == effective_company_id).first()
    return [company] if company else []


@router.get("/companies/{company_id}", response_model=CompanyResponse)
def get_company(
    company_id: UUID,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """Get company by ID. User may only access their effective company (tenant isolation)."""
    user = current_user_and_db[0]
    effective_company_id = get_effective_company_id_for_user(db, user)
    if effective_company_id is None or company_id != effective_company_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to this company")
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return company


@router.get("/companies/{company_id}/logo-url")
def get_company_logo_url(
    company_id: UUID,
    request: Request,
    current_user_and_db: tuple = Depends(get_current_user),
    tenant: Tenant = Depends(get_tenant_or_default),
    db: Session = Depends(get_tenant_db),
):
    """Return a viewable URL for the company logo (signed for tenant-assets, or absolute for /uploads)."""
    user = current_user_and_db[0]
    effective_company_id = get_effective_company_id_for_user(db, user)
    if effective_company_id is None or company_id != effective_company_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to this company")
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company or not getattr(company, "logo_url", None) or not str(company.logo_url).strip():
        raise HTTPException(status_code=404, detail="Company or logo not found")
    logo_path = str(company.logo_url).strip()
    if logo_path.startswith("tenant-assets/"):
        url = get_signed_url(logo_path, tenant=tenant)
        if not url:
            raise HTTPException(status_code=404, detail="Logo URL not available")
        return {"url": url}
    if logo_path.startswith("/"):
        base = str(request.base_url).rstrip("/")
        return {"url": f"{base}{logo_path}"}
    if logo_path.startswith("http://") or logo_path.startswith("https://"):
        return {"url": logo_path}
    raise HTTPException(status_code=404, detail="Logo URL not available")


@router.put("/companies/{company_id}", response_model=CompanyResponse)
def update_company(
    company_id: UUID,
    company_update: CompanyUpdate,
    db: Session = Depends(get_tenant_db),
    _auth: tuple = Depends(require_settings_edit),
):
    """Update company (requires settings.edit)."""
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    
    update_data = company_update.model_dump(exclude_unset=True) if hasattr(company_update, 'model_dump') else company_update.dict(exclude_unset=True)
    if "logo_url" in update_data and (not update_data["logo_url"] or not str(update_data["logo_url"]).strip()) and (company.logo_url or "").startswith("tenant-assets/"):
        del update_data["logo_url"]
    for field, value in update_data.items():
        setattr(company, field, value)
    
    db.commit()
    db.refresh(company)
    return company


# Company settings (e.g. print_config for receipts - set by admin, applies to all users)
def _mask_document_branding_for_frontend(
    raw: Dict[str, Any], tenant: Optional[Any] = None
) -> Dict[str, Any]:
    """Never expose raw storage paths. Replace stamp_url with short-lived signed URL."""
    out = {k: v for k, v in raw.items() if k != "stamp_url"}
    stamp_path = raw.get("stamp_url")
    if stamp_path and isinstance(stamp_path, str):
        signed = get_signed_url(stamp_path, expires_in=SIGNED_URL_EXPIRY_SECONDS, tenant=tenant)
        if signed:
            out["stamp_preview_url"] = signed
    return out


@router.get("/companies/{company_id}/settings")
def get_company_settings(
    company_id: UUID,
    key: Optional[str] = Query(None, description="Setting key, e.g. 'print_config'. Omit to get all."),
    current_user_and_db: tuple = Depends(get_current_user),
    tenant: Tenant = Depends(get_tenant_or_default),
    db: Session = Depends(get_tenant_db),
) -> Dict[str, Any]:
    """Get company-level settings. User may only access settings of their effective company. Raw storage paths are never returned; use signed URLs for preview."""
    user = current_user_and_db[0]
    effective_company_id = get_effective_company_id_for_user(db, user)
    if effective_company_id is None or company_id != effective_company_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to this company")
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    q = db.query(CompanySetting).filter(
        CompanySetting.company_id == company_id,
    )
    if key:
        q = q.filter(CompanySetting.setting_key == key)
    rows = q.all()
    if key and rows:
        r = rows[0]
        if r.setting_type == "json":
            try:
                val = json.loads(r.setting_value or "{}")
                if r.setting_key == "document_branding" and isinstance(val, dict):
                    val = _mask_document_branding_for_frontend(val, tenant)
                return {"key": r.setting_key, "value": val}
            except json.JSONDecodeError:
                return {"key": r.setting_key, "value": r.setting_value}
        return {"key": r.setting_key, "value": r.setting_value}
    if key:
        return {"key": key, "value": None}
    out = {}
    for r in rows:
        if r.setting_type == "json":
            try:
                val = json.loads(r.setting_value or "{}")
                if r.setting_key == "document_branding" and isinstance(val, dict):
                    val = _mask_document_branding_for_frontend(val, tenant)
                out[r.setting_key] = val
            except json.JSONDecodeError:
                out[r.setting_key] = r.setting_value
        else:
            out[r.setting_key] = r.setting_value
    return {"settings": out}


@router.put("/companies/{company_id}/settings")
def update_company_setting(
    company_id: UUID,
    body: CompanySettingUpdate,
    db: Session = Depends(get_tenant_db),
    _auth: tuple = Depends(require_settings_edit),
) -> Dict[str, Any]:
    """Upsert a company setting (e.g. print_config, document_branding). Requires settings.edit."""
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    val = body.value
    if isinstance(val, (dict, list)):
        setting_type = "json"
        # Preserve stamp_url when updating document_branding (frontend never sends raw path)
        if body.key == "document_branding" and isinstance(val, dict) and "stamp_url" not in val:
            row = db.query(CompanySetting).filter(
                CompanySetting.company_id == company_id,
                CompanySetting.setting_key == body.key,
            ).first()
            if row and row.setting_value:
                try:
                    existing = json.loads(row.setting_value)
                    if isinstance(existing, dict) and existing.get("stamp_url"):
                        val = {**val, "stamp_url": existing["stamp_url"]}
                except json.JSONDecodeError:
                    pass
        setting_value = json.dumps(val)
    else:
        setting_type = "string"
        setting_value = str(val) if val is not None else None
    row = db.query(CompanySetting).filter(
        CompanySetting.company_id == company_id,
        CompanySetting.setting_key == body.key,
    ).first()
    if row:
        row.setting_value = setting_value
        row.setting_type = setting_type
    else:
        row = CompanySetting(
            company_id=company_id,
            setting_key=body.key,
            setting_value=setting_value,
            setting_type=setting_type,
        )
        db.add(row)
    db.commit()
    return {"key": body.key, "value": val}


@router.post("/companies/{company_id}/stamp")
async def upload_company_stamp(
    company_id: UUID,
    file: UploadFile = File(...),
    tenant: Tenant = Depends(get_tenant_or_default),
    db: Session = Depends(get_tenant_db),
    _auth: tuple = Depends(require_settings_edit),
) -> Dict[str, Any]:
    """
    Upload company stamp (e.g. pharmacy seal). Requires settings.edit.
    Stores in Supabase tenant-assets/{tenant_id}/stamp.png. Saves path in document_branding.
    PNG/JPG only, max 2MB.
    """
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    file_ext = Path(file.filename or "").suffix.lower()
    if file_ext not in ALLOWED_IMAGE_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file type. Allowed: PNG, JPG, JPEG",
        )
    content = await file.read()
    if len(content) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File too large. Maximum size is 2MB",
        )
    content_type = (file.content_type or "").strip().lower() or ("image/png" if file_ext == ".png" else "image/jpeg")
    if content_type not in ("image/png", "image/jpeg"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid content-type. Allowed: image/png, image/jpeg",
        )
    stored_path = upload_stamp(tenant.id, content, content_type, tenant=tenant)
    if not stored_path:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Storage unavailable. Check Supabase configuration.",
        )
    # Merge stamp_url into document_branding
    row = db.query(CompanySetting).filter(
        CompanySetting.company_id == company_id,
        CompanySetting.setting_key == "document_branding",
    ).first()
    try:
        branding = json.loads(row.setting_value or "{}") if row else {}
    except json.JSONDecodeError:
        branding = {}
    branding["stamp_url"] = stored_path
    if row:
        row.setting_value = json.dumps(branding)
        row.setting_type = "json"
    else:
        db.add(CompanySetting(
            company_id=company_id,
            setting_key="document_branding",
            setting_value=json.dumps(branding),
            setting_type="json",
        ))
    db.commit()
    # Never expose raw path to frontend; return signed preview URL only
    out_branding = _mask_document_branding_for_frontend(branding, tenant)
    return {"document_branding": out_branding}


@router.post("/companies/{company_id}/logo", response_model=CompanyResponse)
async def upload_company_logo(
    company_id: UUID,
    file: UploadFile = File(...),
    tenant: Tenant = Depends(get_tenant_or_default),
    db: Session = Depends(get_tenant_db),
    _auth: tuple = Depends(require_settings_edit),
):
    """
    Upload company logo (requires settings.edit).
    Prefer Supabase tenant-assets (PNG/JPG, max 2MB). Falls back to local uploads if storage unavailable.
    Returns the company with updated logo_url (stored path or local URL).
    """
    import os
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    file_content = await file.read()
    file_ext = Path(file.filename or "").suffix.lower()
    content_type = (file.content_type or "image/png").split(";")[0].strip()
    if file_ext not in {".png", ".jpg", ".jpeg"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file type. Allowed: .png, .jpg, .jpeg",
        )
    if len(file_content) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File too large. Maximum size is 2MB",
        )
    stored_path = upload_logo(tenant.id, file_content, content_type, tenant=tenant)
    if stored_path:
        company.logo_url = stored_path
        db.commit()
        db.refresh(company)
        return company
    file_path = None
    try:
        filename = f"{company_id}_{int(os.urandom(4).hex(), 16)}{file_ext}"
        file_path = UPLOAD_DIR / filename
        with open(file_path, "wb") as buffer:
            buffer.write(file_content)
        logo_url = f"/uploads/logos/{filename}"
        company.logo_url = logo_url
        db.commit()
        db.refresh(company)
        return company
    except Exception as e:
        db.rollback()
        if file_path and file_path.exists():
            file_path.unlink()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error uploading logo: {str(e)}",
        )


# Branch endpoints
@router.post("/branches", response_model=BranchResponse, status_code=status.HTTP_201_CREATED)
def create_branch(
    branch: BranchCreate,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Create a new branch
    
    **IMPORTANT: Branch code is REQUIRED and used in invoice numbering.**
    Format for invoice numbers: {BRANCH_CODE}-INV-YYYY-000001
    """
    try:
        # Verify company exists
        company = db.query(Company).filter(Company.id == branch.company_id).first()
        if not company:
            raise HTTPException(status_code=404, detail="Company not found")
        
        # Validate branch code is provided (schema should enforce, but double-check)
        if not branch.code or branch.code.strip() == '':
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Branch code is REQUIRED. It is used in invoice numbering (format: {BRANCH_CODE}-INV-YYYY-000001)"
            )
        
        # Use model_dump() for Pydantic v2, fallback to dict() for v1
        branch_data = branch.model_dump() if hasattr(branch, 'model_dump') else branch.dict()
        db_branch = Branch(**branch_data)
        db.add(db_branch)
        db.commit()
        db.refresh(db_branch)
        return db_branch
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        import traceback
        error_details = traceback.format_exc()
        print(f"Error creating branch: {error_details}")  # Log to console
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating branch: {str(e)}"
        )


@router.get("/branches/company/{company_id}", response_model=List[BranchResponse])
def get_branches_by_company(
    company_id: UUID,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """Get all branches for a company. User may only access branches of their effective company."""
    user = current_user_and_db[0]
    effective_company_id = get_effective_company_id_for_user(db, user)
    if effective_company_id is None or company_id != effective_company_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to this company")
    branches = db.query(Branch).filter(Branch.company_id == company_id).all()
    return branches


@router.get("/branches/{branch_id}", response_model=BranchResponse)
def get_branch(
    branch_id: UUID,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """Get branch by ID. User may only access branches of their effective company."""
    user = current_user_and_db[0]
    effective_company_id = get_effective_company_id_for_user(db, user)
    branch = db.query(Branch).filter(Branch.id == branch_id).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")
    if effective_company_id is None or branch.company_id != effective_company_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to this branch")
    return branch


@router.put("/branches/{branch_id}", response_model=BranchResponse)
def update_branch(
    branch_id: UUID,
    branch_update: BranchUpdate,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """Update branch"""
    branch = db.query(Branch).filter(Branch.id == branch_id).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")
    
    update_data = branch_update.model_dump(exclude_unset=True) if hasattr(branch_update, 'model_dump') else branch_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(branch, field, value)
    
    db.commit()
    db.refresh(branch)
    return branch


@router.post("/branches/{branch_id}/set-hq", response_model=BranchResponse)
def set_branch_as_hq(
    branch_id: UUID,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Set this branch as the HQ (headquarters) branch.
    Only one branch per company can be HQ. HQ has exclusive access to:
    create items, suppliers, users, roles, and other branches.
    """
    branch = db.query(Branch).filter(Branch.id == branch_id).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")

    # Clear is_hq on all other branches of the same company
    db.query(Branch).filter(
        Branch.company_id == branch.company_id,
        Branch.id != branch_id,
    ).update({Branch.is_hq: False})

    branch.is_hq = True
    db.commit()
    db.refresh(branch)
    return branch


@router.get("/branches/{branch_id}/settings", response_model=BranchSettingResponse)
def get_branch_settings(
    branch_id: UUID,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """Get branch settings (branch inventory: allow manual transfer/receipt). Returns defaults if no row exists."""
    branch = db.query(Branch).filter(Branch.id == branch_id).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")
    row = db.query(BranchSetting).filter(BranchSetting.branch_id == branch_id).first()
    if row:
        return BranchSettingResponse(
            branch_id=row.branch_id,
            allow_manual_transfer=row.allow_manual_transfer,
            allow_manual_receipt=row.allow_manual_receipt,
        )
    return BranchSettingResponse(
        branch_id=branch_id,
        allow_manual_transfer=True,
        allow_manual_receipt=True,
    )


@router.patch("/branches/{branch_id}/settings", response_model=BranchSettingResponse)
def update_branch_settings(
    branch_id: UUID,
    body: BranchSettingUpdate,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """Update branch settings. Requires settings.edit or equivalent."""
    branch = db.query(Branch).filter(Branch.id == branch_id).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")
    row = db.query(BranchSetting).filter(BranchSetting.branch_id == branch_id).first()
    if not row:
        row = BranchSetting(
            branch_id=branch_id,
            allow_manual_transfer=True,
            allow_manual_receipt=True,
        )
        db.add(row)
        db.flush()
    if body.allow_manual_transfer is not None:
        row.allow_manual_transfer = body.allow_manual_transfer
    if body.allow_manual_receipt is not None:
        row.allow_manual_receipt = body.allow_manual_receipt
    db.commit()
    db.refresh(row)
    return BranchSettingResponse(
        branch_id=row.branch_id,
        allow_manual_transfer=row.allow_manual_transfer,
        allow_manual_receipt=row.allow_manual_receipt,
    )

