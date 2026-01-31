"""
Stripe Integration Service
Handles subscription billing and webhooks
"""
import os
from typing import Dict, Optional
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

# Optional Stripe import - app can run without it
try:
    import stripe
    STRIPE_AVAILABLE = True
    # Initialize Stripe
    stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
    STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")
except ImportError:
    STRIPE_AVAILABLE = False
    stripe = None
    STRIPE_WEBHOOK_SECRET = None

from app.database_master import MasterSessionLocal
from app.models.tenant import Tenant, TenantSubscription, SubscriptionPlan


class StripeService:
    """Service for Stripe integration"""
    
    @staticmethod
    def create_checkout_session(
        tenant_id: str,
        plan_id: str,
        success_url: str,
        cancel_url: str
    ) -> Dict:
        """
        Create Stripe Checkout Session for subscription
        
        Args:
            tenant_id: Tenant UUID
            plan_id: Subscription plan UUID
            success_url: URL to redirect after successful payment
            cancel_url: URL to redirect if payment cancelled
        
        Returns:
            Checkout session with URL
        """
        if not STRIPE_AVAILABLE:
            raise RuntimeError("Stripe package not installed. Install with: pip install stripe")
        
        db = MasterSessionLocal()
        
        try:
            tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
            plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.id == plan_id).first()
            
            if not tenant or not plan:
                raise ValueError("Tenant or plan not found")
            
            # Get or create Stripe customer
            customer_id = StripeService._get_or_create_customer(tenant, db)
            
            # Get Stripe price ID (stored in plan or create dynamically)
            price_id = StripeService._get_stripe_price_id(plan)
            
            # Create checkout session
            session = stripe.checkout.Session.create(
                customer=customer_id,
                payment_method_types=['card'],
                line_items=[{
                    'price': price_id,
                    'quantity': 1,
                }],
                mode='subscription',
                success_url=success_url,
                cancel_url=cancel_url,
                metadata={
                    'tenant_id': str(tenant_id),
                    'plan_id': str(plan_id)
                },
                subscription_data={
                    'metadata': {
                        'tenant_id': str(tenant_id),
                        'plan_id': str(plan_id)
                    }
                }
            )
            
            return {
                "session_id": session.id,
                "url": session.url
            }
        
        finally:
            db.close()
    
    @staticmethod
    def _get_or_create_customer(tenant: Tenant, db: Session) -> str:
        """Get existing Stripe customer or create new one"""
        if not STRIPE_AVAILABLE:
            raise RuntimeError("Stripe package not installed. Install with: pip install stripe")
        
        # Check if customer already exists
        subscription = db.query(TenantSubscription).filter(
            TenantSubscription.tenant_id == tenant.id
        ).first()
        
        if subscription and subscription.stripe_customer_id:
            return subscription.stripe_customer_id
        
        # Create new customer
        customer = stripe.Customer.create(
            email=tenant.admin_email,
            name=tenant.name,
            metadata={
                'tenant_id': str(tenant.id),
                'subdomain': tenant.subdomain
            }
        )
        
        # Store customer ID
        if subscription:
            subscription.stripe_customer_id = customer.id
        else:
            # Create subscription record
            subscription = TenantSubscription(
                tenant_id=tenant.id,
                stripe_customer_id=customer.id
            )
            db.add(subscription)
        
        db.commit()
        
        return customer.id
    
    @staticmethod
    def _get_stripe_price_id(plan: SubscriptionPlan) -> str:
        """Get Stripe price ID for plan"""
        # Option 1: Store price ID in database
        # Add stripe_price_id_monthly and stripe_price_id_yearly to SubscriptionPlan model
        
        # Option 2: Create price dynamically (not recommended for production)
        # For now, return placeholder - you'll need to create prices in Stripe dashboard
        # and store the IDs
        
        # This should be stored in your database
        # For now, raise error to remind you to set it up
        raise NotImplementedError(
            "Stripe price IDs not configured. "
            "Create prices in Stripe dashboard and store IDs in subscription_plans table."
        )
    
    @staticmethod
    def handle_webhook(event: Dict) -> Dict:
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
        if not STRIPE_AVAILABLE:
            raise RuntimeError("Stripe package not installed. Install with: pip install stripe")
        
        event_type = event.get('type')
        data = event.get('data', {}).get('object', {})
        
        db = MasterSessionLocal()
        
        try:
            if event_type == 'checkout.session.completed':
                return StripeService._handle_checkout_completed(data, db)
            
            elif event_type == 'customer.subscription.created':
                return StripeService._handle_subscription_created(data, db)
            
            elif event_type == 'customer.subscription.updated':
                return StripeService._handle_subscription_updated(data, db)
            
            elif event_type == 'customer.subscription.deleted':
                return StripeService._handle_subscription_deleted(data, db)
            
            elif event_type == 'invoice.payment_succeeded':
                return StripeService._handle_payment_succeeded(data, db)
            
            elif event_type == 'invoice.payment_failed':
                return StripeService._handle_payment_failed(data, db)
            
            else:
                return {"status": "ignored", "event_type": event_type}
        
        finally:
            db.close()
    
    @staticmethod
    def _handle_checkout_completed(data: Dict, db: Session) -> Dict:
        """Handle successful checkout"""
        metadata = data.get('metadata', {})
        tenant_id = metadata.get('tenant_id')
        
        if not tenant_id:
            return {"status": "error", "message": "No tenant_id in metadata"}
        
        tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
        if not tenant:
            return {"status": "error", "message": "Tenant not found"}
        
        # Get subscription from Stripe
        subscription_id = data.get('subscription')
        if subscription_id and STRIPE_AVAILABLE:
            subscription = stripe.Subscription.retrieve(subscription_id)
            StripeService._update_subscription_from_stripe(tenant, subscription, db)
        
        # Activate tenant
        tenant.status = 'active'
        db.commit()
        
        return {"status": "success", "tenant_id": tenant_id}
    
    @staticmethod
    def _handle_subscription_created(data: Dict, db: Session) -> Dict:
        """Handle new subscription"""
        metadata = data.get('metadata', {})
        tenant_id = metadata.get('tenant_id')
        
        tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
        if not tenant:
            return {"status": "error", "message": "Tenant not found"}
        
        StripeService._update_subscription_from_stripe(tenant, data, db)
        
        return {"status": "success", "tenant_id": tenant_id}
    
    @staticmethod
    def _handle_subscription_updated(data: Dict, db: Session) -> Dict:
        """Handle subscription update (plan change, etc.)"""
        subscription_id = data.get('id')
        
        subscription_record = db.query(TenantSubscription).filter(
            TenantSubscription.stripe_subscription_id == subscription_id
        ).first()
        
        if not subscription_record:
            return {"status": "error", "message": "Subscription not found"}
        
        tenant = subscription_record.tenant
        StripeService._update_subscription_from_stripe(tenant, data, db)
        
        return {"status": "success", "tenant_id": str(tenant.id)}
    
    @staticmethod
    def _handle_subscription_deleted(data: Dict, db: Session) -> Dict:
        """Handle subscription cancellation"""
        subscription_id = data.get('id')
        
        subscription_record = db.query(TenantSubscription).filter(
            TenantSubscription.stripe_subscription_id == subscription_id
        ).first()
        
        if not subscription_record:
            return {"status": "error", "message": "Subscription not found"}
        
        tenant = subscription_record.tenant
        
        # Mark subscription as cancelled
        subscription_record.status = 'cancelled'
        subscription_record.cancelled_at = datetime.utcnow()
        
        # Suspend tenant access (or wait until period end)
        # For now, suspend immediately
        tenant.status = 'suspended'
        
        db.commit()
        
        return {"status": "success", "tenant_id": str(tenant.id)}
    
    @staticmethod
    def _handle_payment_succeeded(data: Dict, db: Session) -> Dict:
        """Handle successful payment"""
        subscription_id = data.get('subscription')
        
        if not subscription_id:
            return {"status": "ignored", "message": "No subscription in invoice"}
        
        subscription_record = db.query(TenantSubscription).filter(
            TenantSubscription.stripe_subscription_id == subscription_id
        ).first()
        
        if subscription_record:
            # Renew subscription period
            period_end = datetime.fromtimestamp(data.get('period_end', 0))
            subscription_record.current_period_end = period_end
            subscription_record.status = 'active'
            
            subscription_record.tenant.status = 'active'
            db.commit()
        
        return {"status": "success"}
    
    @staticmethod
    def _handle_payment_failed(data: Dict, db: Session) -> Dict:
        """Handle failed payment"""
        subscription_id = data.get('subscription')
        
        if not subscription_id:
            return {"status": "ignored"}
        
        subscription_record = db.query(TenantSubscription).filter(
            TenantSubscription.stripe_subscription_id == subscription_id
        ).first()
        
        if subscription_record:
            subscription_record.status = 'past_due'
            subscription_record.tenant.status = 'past_due'
            db.commit()
            
            # TODO: Send email reminder
        
        return {"status": "success"}
    
    @staticmethod
    def _update_subscription_from_stripe(tenant: Tenant, stripe_subscription: Dict, db: Session):
        """Update subscription record from Stripe data"""
        subscription = db.query(TenantSubscription).filter(
            TenantSubscription.tenant_id == tenant.id
        ).first()
        
        if not subscription:
            # Create new subscription record
            subscription = TenantSubscription(tenant_id=tenant.id)
            db.add(subscription)
        
        subscription.stripe_subscription_id = stripe_subscription.get('id')
        subscription.stripe_customer_id = stripe_subscription.get('customer')
        
        # Update period
        current_period_start = stripe_subscription.get('current_period_start')
        current_period_end = stripe_subscription.get('current_period_end')
        
        if current_period_start:
            subscription.current_period_start = datetime.fromtimestamp(current_period_start)
        if current_period_end:
            subscription.current_period_end = datetime.fromtimestamp(current_period_end)
        
        # Update status
        stripe_status = stripe_subscription.get('status')
        if stripe_status == 'active':
            subscription.status = 'active'
            tenant.status = 'active'
        elif stripe_status == 'canceled':
            subscription.status = 'cancelled'
        
        db.commit()


# Webhook verification
def verify_webhook_signature(payload: bytes, signature: str) -> bool:
    """Verify Stripe webhook signature"""
    if not STRIPE_AVAILABLE:
        return False
    
    try:
        event = stripe.Webhook.construct_event(
            payload, signature, STRIPE_WEBHOOK_SECRET
        )
        return True
    except ValueError:
        return False
    except stripe.error.SignatureVerificationError:
        return False
