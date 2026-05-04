"""
Tenant setup invites (single-DB + registry).

Used by both ``/api/admin/tenants/.../invites`` (legacy, gated by ENABLE_TENANT_ADMIN) and
``/api/admin/platform-licensing/tenants/.../invites`` (always on for admin.html licensing).
"""
from __future__ import annotations

import logging
import secrets
import string
from datetime import datetime, timedelta
from typing import List
from uuid import UUID

from fastapi import BackgroundTasks, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import settings
from app.dependencies import is_tenant_ready_for_invite, tenant_or_app_db_session
from app.models.tenant import Tenant, TenantInvite
from app.schemas.tenant import TenantInviteCreate, TenantInviteResponse
from app.services.email_service import EmailService
from app.utils.public_url import get_public_base_url
from app.utils.username_generator import generate_username_from_name

logger = logging.getLogger(__name__)


def _generate_invite_token(length: int = 32) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def create_tenant_invite(
    *,
    tenant_id: UUID,
    invite_data: TenantInviteCreate,
    db: Session,
    request: Request,
    background_tasks: BackgroundTasks,
) -> TenantInviteResponse:
    """Create invite row + optional background email (same behavior as legacy admin tenants API)."""
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found",
        )
    if not is_tenant_ready_for_invite(tenant):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Tenant not ready for invite. Set database_url to your app database URL or leave it unset "
                "to use the shared app DB."
            ),
        )

    generated_username = None
    with tenant_or_app_db_session(tenant) as tenant_db:
        if tenant.admin_full_name:
            try:
                generated_username = generate_username_from_name(
                    tenant.admin_full_name,
                    db_session=tenant_db,
                )
            except Exception as e:
                logger.warning("Could not generate username from admin_full_name: %s", e)
        if not generated_username:
            email_local = tenant.admin_email.split("@")[0]
            name_parts = email_local.replace(".", " ").replace("_", " ").replace("-", " ").split()
            if len(name_parts) >= 2:
                try:
                    generated_username = generate_username_from_name(
                        " ".join(name_parts),
                        db_session=tenant_db,
                    )
                except Exception:
                    generated_username = f"{email_local[0].upper()}-{email_local.upper()[:10]}"
            else:
                generated_username = f"{email_local[0].upper()}-{email_local.upper()[:10]}"

    token = _generate_invite_token()
    invite = TenantInvite(
        tenant_id=tenant_id,
        token=token,
        expires_at=datetime.utcnow() + timedelta(days=invite_data.expires_in_days),
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)

    base_url = get_public_base_url(request)
    setup_url = f"{base_url.rstrip('/')}/setup?token={invite.token}"

    invite_response = TenantInviteResponse.model_validate(invite)
    invite_response.username = generated_username
    invite_response.setup_url = setup_url

    if invite_data.send_email:
        smtp_configured = EmailService.is_configured()
        invite_response.email_sent = smtp_configured

        if not smtp_configured:
            missing = []
            if not settings.SMTP_HOST:
                missing.append("SMTP_HOST")
            if not settings.SMTP_USER:
                missing.append("SMTP_USER")
            if not settings.SMTP_PASSWORD:
                missing.append("SMTP_PASSWORD")
            logger.warning(
                "SMTP not configured (missing: %s). Invite created for %s but email will not be sent. Link: %s",
                ", ".join(missing),
                tenant.admin_email,
                setup_url,
            )
        else:

            def send_email_with_logging():
                try:
                    logger.info(
                        "Background task: Sending invite email to %s for tenant %s",
                        tenant.admin_email,
                        tenant.name,
                    )
                    result = EmailService.send_tenant_invite(
                        to_email=tenant.admin_email,
                        tenant_name=tenant.name,
                        setup_url=setup_url,
                        username=generated_username,
                    )
                    if result:
                        logger.info("Background task: Successfully sent invite email to %s", tenant.admin_email)
                    else:
                        logger.warning(
                            "Background task: Failed to send invite email to %s (check SMTP)",
                            tenant.admin_email,
                        )
                except Exception as e:
                    logger.exception("Background task: Exception sending invite email to %s: %s", tenant.admin_email, e)

            background_tasks.add_task(send_email_with_logging)
            logger.info(
                "Invite created for %s. Email sending queued in background task (SMTP configured).",
                tenant.admin_email,
            )
    else:
        invite_response.email_sent = False

    return invite_response


def list_tenant_invites(*, tenant_id: UUID, db: Session) -> List[TenantInviteResponse]:
    invites = (
        db.query(TenantInvite)
        .filter(TenantInvite.tenant_id == tenant_id)
        .order_by(TenantInvite.created_at.desc())
        .all()
    )
    return [TenantInviteResponse.model_validate(inv) for inv in invites]
