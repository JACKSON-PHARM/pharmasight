"""
Authenticated company billing (Stripe Checkout). Writes go through StripeService → ``companies`` only.
"""
from __future__ import annotations

from typing import Tuple
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, HttpUrl
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_effective_company_id_for_user
from app.models.user import User

router = APIRouter()


class StripeCheckoutRequest(BaseModel):
    plan_id: UUID
    success_url: HttpUrl
    cancel_url: HttpUrl


@router.post("/billing/stripe/checkout-session")
def create_stripe_checkout_session(
    request: Request,
    body: StripeCheckoutRequest,
    current: Tuple[User, Session] = Depends(get_current_user),
):
    """
    Create a Stripe Checkout Session for the authenticated user's company.
    Company id is taken from auth context only (never from the client body).
    """
    try:
        from app.services.stripe_service import StripeService
    except ImportError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stripe is not available on this server.",
        )

    user, db = current
    company_id = getattr(request.state, "effective_company_id", None) or get_effective_company_id_for_user(db, user)
    if company_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No company context for this user")

    try:
        out = StripeService.create_checkout_session(
            str(company_id),
            str(body.plan_id),
            str(body.success_url),
            str(body.cancel_url),
        )
    except RuntimeError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Stripe error: {e}") from e

    return out
