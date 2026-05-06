"""
Platform admin: public marketing site settings (singleton).

Used by admin.html to edit contact info and marketing image URLs (stored in Supabase Storage public bucket).
"""

from __future__ import annotations

from typing import Dict, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.dependencies import get_current_admin, get_tenant_db
from app.models import PublicSiteSettings
from app.services.tenant_storage_service import upload_platform_marketing_image


router = APIRouter(tags=["Admin Site Settings"])


class SiteSettingsPayload(BaseModel):
    support_email: Optional[str] = Field(None, max_length=255)
    sales_email: Optional[str] = Field(None, max_length=255)
    phone: Optional[str] = Field(None, max_length=80)
    whatsapp: Optional[str] = Field(None, max_length=80)
    address: Optional[str] = Field(None, max_length=500)
    logo_url: Optional[str] = Field(None, max_length=2048)
    marketing_images: Optional[Dict[str, str]] = None


def _get_or_create_singleton(db: Session) -> PublicSiteSettings:
    row = db.query(PublicSiteSettings).filter(PublicSiteSettings.id == 1).first()
    if row:
        return row
    row = PublicSiteSettings(id=1)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _row_to_payload(row: Optional[PublicSiteSettings]) -> SiteSettingsPayload:
    if not row:
        return SiteSettingsPayload(
            support_email=None,
            sales_email=None,
            phone=None,
            whatsapp=None,
            address=None,
            logo_url="",
            marketing_images={},
        )
    return SiteSettingsPayload(
        support_email=row.support_email,
        sales_email=row.sales_email,
        phone=row.phone,
        whatsapp=row.whatsapp,
        address=row.address,
        logo_url=(row.logo_url or "").strip(),
        marketing_images=dict(row.marketing_images or {}),
    )


@router.get("/site-settings", response_model=SiteSettingsPayload)
def get_site_settings(
    _admin: None = Depends(get_current_admin),
    db: Session = Depends(get_tenant_db),
):
    row = db.query(PublicSiteSettings).filter(PublicSiteSettings.id == 1).first()
    return _row_to_payload(row)


@router.put("/site-settings", response_model=SiteSettingsPayload)
def put_site_settings(
    body: SiteSettingsPayload,
    _admin: None = Depends(get_current_admin),
    db: Session = Depends(get_tenant_db),
):
    row = _get_or_create_singleton(db)
    data = body.model_dump(exclude_unset=True)

    mi_in = data.pop("marketing_images", "__unset__")
    if mi_in != "__unset__" and mi_in is not None:
        row.marketing_images = {
            str(k).strip(): str(v).strip()
            for k, v in mi_in.items()
            if str(k).strip() and str(v).strip()
        }

    for k, v in data.items():
        if k == "logo_url":
            if v is None:
                continue
            s = str(v).strip()
            setattr(row, k, s if s else None)
            continue
        if v is None:
            continue
        s = str(v).strip()
        setattr(row, k, s if s else None)

    db.commit()
    db.refresh(row)
    return _row_to_payload(row)


@router.post("/site-settings/marketing-image", response_model=SiteSettingsPayload)
async def post_site_settings_marketing_image(
    kind: str = Form(...),
    file: UploadFile = File(...),
    _admin: None = Depends(get_current_admin),
    db: Session = Depends(get_tenant_db),
):
    """
    Upload logo / favicon / hero / og_image to Supabase Storage (`marketing-public` bucket)
    and save the public URL on the singleton row.
    """
    content = await file.read()
    ct = (file.content_type or "").strip() or "application/octet-stream"
    url, err = upload_platform_marketing_image(kind=kind, content=content, content_type=ct)
    if not url:
        raise HTTPException(status_code=400, detail=err or "Upload failed")

    row = _get_or_create_singleton(db)
    k = kind.strip().lower()
    if k == "logo":
        row.logo_url = url
    else:
        imgs = dict(row.marketing_images or {})
        imgs[k] = url
        row.marketing_images = imgs

    db.commit()
    db.refresh(row)
    return _row_to_payload(row)
