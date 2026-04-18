"""
Public marketing site API: trial signup entry point (same behaviour as /api/auth/start-demo).
"""
import logging

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field

from app.rate_limit import limiter
from app.services.demo_signup_service import create_demo_tenant
from app.api.auth import StartDemoRequest, start_demo_api_response

logger = logging.getLogger(__name__)

router = APIRouter()


class PublicSignupRequest(BaseModel):
    """Alias of StartDemoRequest for public marketing documentation."""
    organization_name: str = Field(..., min_length=1, max_length=255)
    full_name: str = Field(..., min_length=1, max_length=255)
    email: EmailStr
    phone: str | None = None
    password: str = Field(..., min_length=8)


@router.post("/public/signup", status_code=status.HTTP_201_CREATED)
@limiter.limit("10/hour")
def public_signup(request: Request, body: PublicSignupRequest):
    """
    Start free trial from the marketing site. Creates company + admin user (shared DB) and returns tokens
    plus a short-lived signup_handoff_token for redirecting to the ERP SPA on another origin.
    """
    inner = StartDemoRequest(
        organization_name=body.organization_name,
        full_name=body.full_name,
        email=body.email,
        phone=body.phone,
        password=body.password,
    )
    try:
        result = create_demo_tenant(
            organization_name=inner.organization_name.strip(),
            full_name=inner.full_name.strip(),
            email=str(inner.email).strip().lower(),
            phone=inner.phone,
            password=inner.password,
        )
    except ValueError as e:
        msg = str(e)
        msg_lc = msg.lower()
        code = (
            status.HTTP_429_TOO_MANY_REQUESTS
            if "too many demo signups" in msg_lc
            else (
                status.HTTP_409_CONFLICT
                if (
                    "already registered with this email" in msg_lc
                    or "already registered for this organization" in msg_lc
                    or "organization with this name already exists" in msg_lc
                )
                else status.HTTP_400_BAD_REQUEST
            )
        )
        raise HTTPException(status_code=code, detail=msg)
    except Exception as e:
        logger.exception("Public signup failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not create your account right now. Please try again later.",
        )
    return start_demo_api_response(result, str(inner.email))
