"""
Stripe Webhook Handler
Receives and processes Stripe webhook events
"""
from fastapi import APIRouter, Request, HTTPException, status, Header

# Optional Stripe import - app can run without it
try:
    import stripe
    STRIPE_AVAILABLE = True
except ImportError:
    STRIPE_AVAILABLE = False
    stripe = None

# Optional Stripe service import
try:
    from app.services.stripe_service import StripeService, parse_verified_stripe_event
    STRIPE_SERVICE_AVAILABLE = True
except ImportError:
    STRIPE_SERVICE_AVAILABLE = False
    StripeService = None
    parse_verified_stripe_event = None

router = APIRouter()


@router.post("/webhooks/stripe")
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(None, alias="stripe-signature")
):
    """
    Handle Stripe webhook events
    
    Events handled:
    - checkout.session.completed
    - customer.subscription.created
    - customer.subscription.updated
    - customer.subscription.deleted
    - invoice.payment_succeeded
    - invoice.payment_failed
    """
    if not STRIPE_AVAILABLE or not STRIPE_SERVICE_AVAILABLE or parse_verified_stripe_event is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stripe integration not available. Please install stripe package: pip install stripe"
        )
    
    if not stripe_signature:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing stripe-signature header"
        )
    
    # Get raw body
    body = await request.body()
    
    event = parse_verified_stripe_event(body, stripe_signature)
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid webhook signature or payload",
        )
    
    # Handle event
    try:
        result = StripeService.handle_webhook(event)
        return {"status": "success", "result": result}
    except Exception as e:
        # Log error but return 200 to Stripe (so they don't retry)
        print(f"Error handling webhook: {e}")
        return {"status": "error", "message": str(e)}


@router.get("/webhooks/stripe/test")
def test_webhook():
    """Test endpoint to verify webhook is accessible"""
    return {"status": "ok", "message": "Webhook endpoint is active"}
