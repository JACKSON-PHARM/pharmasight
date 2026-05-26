"""
Public marketing site API: trial signup entry point (same behaviour as /api/auth/start-demo).
"""
import base64
import logging
import os
from datetime import datetime
from urllib import error as url_error
from urllib import request as url_request

from fastapi import APIRouter, HTTPException, Request, status, Depends
from pydantic import BaseModel, EmailStr, Field

from app.rate_limit import limiter
from app.services.demo_signup_service import create_demo_tenant
from app.api.auth import StartDemoRequest, start_demo_api_response
from app.models import PublicSiteSettings
from app.dependencies import get_tenant_db
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

router = APIRouter()


class PublicSignupRequest(BaseModel):
    """Alias of StartDemoRequest for public marketing documentation."""
    organization_name: str = Field(..., min_length=1, max_length=255)
    full_name: str = Field(..., min_length=1, max_length=255)
    email: EmailStr
    phone: str = Field(..., min_length=5, max_length=50)
    password: str = Field(..., min_length=8)


class PublicSiteSettingsResponse(BaseModel):
    support_email: str = ""
    sales_email: str = ""
    phone: str = ""
    whatsapp: str = ""
    address: str = ""
    logo_url: str = ""
    marketing_images: dict = Field(default_factory=dict)


class SubscriptionCheckoutRequest(BaseModel):
    full_name: str = Field(..., min_length=1, max_length=255)
    phone: str = Field(..., min_length=8, max_length=32, description="Phone to prompt with STK push")
    email: EmailStr
    organization_name: str = Field(..., min_length=1, max_length=255)


class SubscriptionCheckoutResponse(BaseModel):
    provider: str = "daraja"
    amount_kes: int = 999
    currency: str = "KES"
    plan_label: str = "First month access"
    merchant_phone: str
    message: str
    payment_initiated: bool = False
    payment_method_label: str = "M-PESA"
    manual_payment_instructions: str = ""
    checkout_request_id: str = ""
    customer_message: str = ""




def _normalize_kenya_phone(raw: str) -> str:
    digits = ''.join(ch for ch in (raw or '') if ch.isdigit())
    if digits.startswith('254') and len(digits) == 12:
        return digits
    if digits.startswith('0') and len(digits) == 10:
        return f"254{digits[1:]}"
    if len(digits) == 9 and digits.startswith('7'):
        return f"254{digits}"
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Use a valid Kenyan Safaricom number (e.g. 07XXXXXXXX).')


def _daraja_access_token() -> str:
    key = (os.getenv('DARAJA_CONSUMER_KEY') or '').strip()
    secret = (os.getenv('DARAJA_CONSUMER_SECRET') or '').strip()
    if not key or not secret:
        raise HTTPException(status_code=503, detail='Daraja is not configured yet. Set DARAJA_CONSUMER_KEY and DARAJA_CONSUMER_SECRET.')
    auth = base64.b64encode(f"{key}:{secret}".encode('utf-8')).decode('utf-8')
    req = url_request.Request(
        'https://api.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials',
        headers={'Authorization': f'Basic {auth}'},
        method='GET',
    )
    try:
        with url_request.urlopen(req, timeout=20) as res:
            payload = res.read().decode('utf-8')
    except url_error.HTTPError as e:
        raise HTTPException(status_code=502, detail=f'Daraja auth failed ({e.code}).')
    import json
    data = json.loads(payload or '{}')
    token = (data.get('access_token') or '').strip()
    if not token:
        raise HTTPException(status_code=502, detail='Daraja auth returned no access token.')
    return token


def _daraja_stk_push(phone_254: str, account_ref: str, amount_kes: int = 999) -> tuple[str, str]:
    import json
    shortcode = (os.getenv('DARAJA_SHORTCODE') or '').strip()
    passkey = (os.getenv('DARAJA_PASSKEY') or '').strip()
    callback_url = (os.getenv('DARAJA_CALLBACK_URL') or '').strip()
    if not shortcode or not passkey or not callback_url:
        raise HTTPException(status_code=503, detail='Daraja paybill is not configured yet. Set DARAJA_SHORTCODE, DARAJA_PASSKEY, and DARAJA_CALLBACK_URL.')

    timestamp = datetime.utcnow().strftime('%Y%m%d%H%M%S')
    password = base64.b64encode(f"{shortcode}{passkey}{timestamp}".encode('utf-8')).decode('utf-8')
    token = _daraja_access_token()
    body = {
        'BusinessShortCode': shortcode,
        'Password': password,
        'Timestamp': timestamp,
        'TransactionType': _daraja_transaction_type(),
        'Amount': amount_kes,
        'PartyA': phone_254,
        'PartyB': shortcode,
        'PhoneNumber': phone_254,
        'CallBackURL': callback_url,
        'AccountReference': account_ref[:12],
        'TransactionDesc': 'SightOps Starter Plan',
    }
    req = url_request.Request(
        'https://api.safaricom.co.ke/mpesa/stkpush/v1/processrequest',
        data=json.dumps(body).encode('utf-8'),
        headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {token}'},
        method='POST',
    )
    try:
        with url_request.urlopen(req, timeout=20) as res:
            payload = res.read().decode('utf-8')
    except url_error.HTTPError as e:
        detail = e.read().decode('utf-8') if hasattr(e, 'read') else ''
        message = _daraja_error_message(detail) or f'Daraja STK push failed ({e.code}).'
        raise HTTPException(status_code=502, detail=message)
    data = json.loads(payload or '{}')
    return (data.get('CheckoutRequestID') or ''), (data.get('CustomerMessage') or '')


def _daraja_transaction_type() -> str:
    configured = (os.getenv('DARAJA_TRANSACTION_TYPE') or '').strip()
    if configured:
        return configured
    mode = (os.getenv('DARAJA_PAYMENT_MODE') or 'paybill').strip().lower()
    return 'CustomerBuyGoodsOnline' if mode in ('till', 'buygoods', 'buy_goods') else 'CustomerPayBillOnline'


def _daraja_payment_label() -> str:
    mode = (os.getenv('DARAJA_PAYMENT_MODE') or 'paybill').strip().lower()
    return 'M-PESA Till' if mode in ('till', 'buygoods', 'buy_goods') else 'M-PESA PayBill'


def _manual_payment_number() -> str:
    return (
        os.getenv('DARAJA_MANUAL_PAYMENT_NUMBER')
        or os.getenv('DARAJA_TILL_NUMBER')
        or os.getenv('DARAJA_SHORTCODE')
        or os.getenv('DARAJA_SETTLEMENT_PHONE')
        or '254708476318'
    ).strip()


def _daraja_error_message(raw: str) -> str:
    if not raw:
        return ''
    try:
        import json
        data = json.loads(raw)
    except Exception:
        return raw[:180]
    for key in ('errorMessage', 'ResponseDescription', 'CustomerMessage', 'faultstring'):
        value = data.get(key)
        if value:
            return str(value)
    return raw[:180]

@router.get("/public/site-settings", response_model=PublicSiteSettingsResponse)
def public_site_settings(db: Session = Depends(get_tenant_db)):
    row = db.query(PublicSiteSettings).filter(PublicSiteSettings.id == 1).first()
    if not row:
        return PublicSiteSettingsResponse()
    return PublicSiteSettingsResponse(
        support_email=(row.support_email or "").strip(),
        sales_email=(row.sales_email or "").strip(),
        phone=(row.phone or "").strip(),
        whatsapp=(row.whatsapp or "").strip(),
        address=(row.address or "").strip(),
        logo_url=(row.logo_url or "").strip(),
        marketing_images=dict(row.marketing_images or {}),
    )


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
                    or "already registered with this phone number" in msg_lc
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
    try:
        from app.database import SessionLocal
        from app.services.platform_usage_service import SIGNUP_EVENT, record_platform_event

        with SessionLocal() as telemetry_db:
            record_platform_event(
                telemetry_db,
                event_type=SIGNUP_EVENT,
                company_id=result.get("company_id"),
                user_id=result.get("user_id"),
                actor_email=result.get("email"),
                actor_name=inner.full_name,
                company_name=result.get("company_name") or inner.organization_name,
                metadata={
                    "source": "marketing_signup",
                    "username": result.get("username"),
                    "tenant_subdomain": result.get("tenant_subdomain"),
                },
                request=request,
                send_email=True,
            )
    except Exception:
        logger.debug("Platform signup telemetry skipped", exc_info=True)
    return start_demo_api_response(result, str(inner.email))


@router.post("/public/subscription/daraja-checkout", response_model=SubscriptionCheckoutResponse)
@limiter.limit("20/hour")
def public_daraja_checkout(request: Request, body: SubscriptionCheckoutRequest):
    """
    Marketing subscription intent endpoint for paid onboarding.
    Returns the starter amount and copy the frontend can display before account activation.
    """
    phone_254 = _normalize_kenya_phone(body.phone)
    merchant_phone = _manual_payment_number()
    payment_label = _daraja_payment_label()
    checkout_request_id = ''
    customer_message = ''
    payment_initiated = False
    if (os.getenv('DARAJA_ENABLE_STK_PUSH') or '').strip().lower() in ('1', 'true', 'yes'):
        account_ref = (body.organization_name or body.full_name or 'SightOps').strip()
        checkout_request_id, customer_message = _daraja_stk_push(phone_254, account_ref, amount_kes=999)
        payment_initiated = bool(checkout_request_id)
    manual_payment_instructions = (
        f"STK push was not sent. Ask the client to pay KES 999 via {payment_label} "
        f"{merchant_phone}, then confirm activation manually."
    )
    message = (
        (
            "M-PESA prompt sent. Ask the client to approve it on their phone to complete activation."
            if payment_initiated
            else manual_payment_instructions
        )
    )
    return SubscriptionCheckoutResponse(
        merchant_phone=merchant_phone,
        message=message,
        payment_initiated=payment_initiated,
        payment_method_label=payment_label,
        manual_payment_instructions=manual_payment_instructions,
        checkout_request_id=checkout_request_id,
        customer_message=customer_message,
    )
