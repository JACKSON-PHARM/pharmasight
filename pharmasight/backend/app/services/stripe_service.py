"""
Stripe integration — Phase 2 (company-scoped billing only).

Rules:
- All persistence touches ``companies`` on the application database only.
- Do **not** import or use the ``Tenant`` ORM for business logic (catalog/plan reads use raw SQL on master when needed).
- No writes to ``Tenant`` or legacy tenant-scoped billing tables.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.company import Company

logger = logging.getLogger(__name__)

try:
    import stripe

    STRIPE_AVAILABLE = True
    stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
    STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET") or ""
except ImportError:
    STRIPE_AVAILABLE = False
    stripe = None  # type: ignore
    STRIPE_WEBHOOK_SECRET = ""


def _require_stripe() -> None:
    if not STRIPE_AVAILABLE:
        raise RuntimeError("Stripe package not installed. Install with: pip install stripe")


def _checkout_price_id() -> str:
    """Stripe Price id for subscription Checkout (env)."""
    pid = (os.getenv("STRIPE_PRICE_ID") or os.getenv("STRIPE_DEFAULT_PRICE_ID") or "").strip()
    if not pid:
        raise RuntimeError(
            "Set STRIPE_PRICE_ID (or STRIPE_DEFAULT_PRICE_ID) to a Stripe price_… id for subscription checkout."
        )
    return pid


def _subscription_plan_slug_from_name(name: Optional[str]) -> str:
    base = (name or "plan").strip().lower().replace(" ", "_")
    return base[:80] if base else "plan"


def _stripe_subscription_status_to_company(status: Optional[str]) -> str:
    s = (status or "").strip().lower()
    mapping = {
        "active": "active",
        "trialing": "trialing",
        "past_due": "past_due",
        "canceled": "canceled",
        "cancelled": "canceled",
        "unpaid": "canceled",
        "incomplete": "incomplete",
        "incomplete_expired": "canceled",
        "paused": "suspended",
    }
    return mapping.get(s, s or "unknown")


def _as_dict(obj: Any) -> Dict[str, Any]:
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "to_dict") and callable(obj.to_dict):
        return dict(obj.to_dict())
    return dict(obj)


def _subscription_id_from_invoice(inv: Dict[str, Any]) -> Optional[str]:
    """Normalize invoice.subscription (string or expanded object) to a subscription id."""
    sub = inv.get("subscription")
    if sub is None:
        return None
    if isinstance(sub, str):
        s = sub.strip()
        return s or None
    if isinstance(sub, dict):
        sid = sub.get("id")
        return str(sid).strip() if sid else None
    return str(sub).strip() or None


def verify_webhook_signature(payload: bytes, signature: str) -> bool:
    """Return True if Stripe signature verifies (legacy bool API for the HTTP layer)."""
    return parse_verified_stripe_event(payload, signature) is not None


def parse_verified_stripe_event(payload: bytes, signature: Optional[str]) -> Optional[Dict[str, Any]]:
    """Verify and return the Stripe event as a dict, or None."""
    _require_stripe()
    if not signature or not STRIPE_WEBHOOK_SECRET:
        return None
    try:
        ev = stripe.Webhook.construct_event(payload, signature, STRIPE_WEBHOOK_SECRET)  # type: ignore[arg-type]
        return _as_dict(ev)
    except Exception as e:
        logger.warning("Stripe webhook verify failed: %s", e)
        return None


def _load_plan_row(master_db: Session, plan_id: UUID) -> Optional[Dict[str, Any]]:
    """Read subscription_plans by id (master DB). Raw SQL avoids importing the Tenant ORM module."""
    row = master_db.execute(
        text(
            """
            SELECT id::text AS id, name, is_active
            FROM subscription_plans
            WHERE id = CAST(:id AS uuid)
            """
        ),
        {"id": str(plan_id)},
    ).fetchone()
    if not row:
        return None
    return {"id": row[0], "name": row[1], "is_active": bool(row[2]) if row[2] is not None else True}


def _resolve_company_id(app_db: Session, metadata: Dict[str, Any], customer_id: Optional[str]) -> Optional[UUID]:
    raw = (metadata or {}).get("company_id")
    if raw:
        try:
            return UUID(str(raw).strip())
        except (ValueError, TypeError):
            pass
    if customer_id:
        c = app_db.query(Company).filter(Company.stripe_customer_id == customer_id).first()
        if c:
            return c.id
    return None


class StripeService:
    """Stripe Checkout + webhooks; persistence on ``companies`` only."""

    @staticmethod
    def create_checkout_session(
        company_id: str,
        plan_id: str,
        success_url: str,
        cancel_url: str,
    ) -> Dict[str, Any]:
        """
        Create a Stripe Checkout Session (subscription mode).

        Metadata on the subscription includes ``company_id`` and ``plan_slug`` for webhook correlation.
        """
        _require_stripe()
        from app.database import SessionLocal
        from app.database_master import MasterSessionLocal

        cid = UUID(str(company_id).strip())
        pid = UUID(str(plan_id).strip())
        price_id = _checkout_price_id()

        master_db = MasterSessionLocal()
        app_db = SessionLocal()
        try:
            prow = _load_plan_row(master_db, pid)
            if not prow or not prow.get("is_active", True):
                raise ValueError("Plan not found or inactive")
            plan_slug = _subscription_plan_slug_from_name(prow.get("name"))

            company = app_db.query(Company).filter(Company.id == cid).first()
            if not company:
                raise ValueError("Company not found")

            cust_id = (company.stripe_customer_id or "").strip() or None
            if not cust_id:
                cust = stripe.Customer.create(  # type: ignore[union-attr]
                    email=(company.email or "").strip() or None,
                    name=company.name,
                    metadata={"company_id": str(company.id)},
                )
                cust_id = cust["id"] if isinstance(cust, dict) else cust.id
                company.stripe_customer_id = cust_id
                app_db.add(company)
                app_db.commit()
                app_db.refresh(company)

            session = stripe.checkout.Session.create(  # type: ignore[union-attr]
                customer=cust_id,
                mode="subscription",
                success_url=success_url,
                cancel_url=cancel_url,
                line_items=[{"price": price_id, "quantity": 1}],
                metadata={
                    "company_id": str(company.id),
                    "plan_id": str(pid),
                    "plan_slug": plan_slug,
                },
                subscription_data={
                    "metadata": {
                        "company_id": str(company.id),
                        "plan_id": str(pid),
                        "plan_slug": plan_slug,
                    }
                },
            )
            sid = session["id"] if isinstance(session, dict) else session.id
            url = session["url"] if isinstance(session, dict) else session.url
            return {"session_id": sid, "url": url}
        finally:
            master_db.close()
            app_db.close()

    @staticmethod
    def handle_webhook(event: Dict[str, Any]) -> Dict[str, Any]:
        """Dispatch Stripe events; update ``companies`` only."""
        _require_stripe()
        from app.database import SessionLocal

        et = (event or {}).get("type") or ""
        data_obj = (event.get("data") or {}).get("object") or {}
        app_db = SessionLocal()
        try:
            if et == "checkout.session.completed":
                return StripeService._on_checkout_completed(app_db, _as_dict(data_obj))
            if et in ("customer.subscription.created", "customer.subscription.updated"):
                sub = _as_dict(data_obj)
                sub_full = StripeService._retrieve_subscription(sub.get("id"))
                return StripeService._apply_subscription(app_db, _as_dict(sub_full))
            if et == "customer.subscription.deleted":
                sub = _as_dict(data_obj)
                return StripeService._on_subscription_deleted(app_db, sub)
            if et == "invoice.payment_succeeded":
                inv = _as_dict(data_obj)
                sub_id = _subscription_id_from_invoice(inv)
                if sub_id:
                    sub_full = StripeService._retrieve_subscription(sub_id)
                    return StripeService._apply_subscription(app_db, _as_dict(sub_full))
                return {"status": "ignored", "reason": "no subscription on invoice"}
            if et == "invoice.payment_failed":
                inv = _as_dict(data_obj)
                sub_id = _subscription_id_from_invoice(inv)
                if sub_id:
                    sub_full = StripeService._retrieve_subscription(sub_id)
                    return StripeService._apply_subscription(app_db, _as_dict(sub_full))
                return {"status": "ignored", "reason": "no subscription on invoice"}
            return {"status": "ignored", "event_type": et}
        finally:
            app_db.close()

    @staticmethod
    def _retrieve_subscription(sub_id: Optional[str]) -> Dict[str, Any]:
        if not sub_id:
            return {}
        sub = stripe.Subscription.retrieve(sub_id)  # type: ignore[union-attr]
        return _as_dict(sub)

    @staticmethod
    def _on_checkout_completed(app_db: Session, session: Dict[str, Any]) -> Dict[str, Any]:
        sub_id = session.get("subscription")
        if not sub_id:
            return {"status": "ok", "detail": "no subscription on checkout session"}
        sub = StripeService._retrieve_subscription(sub_id)
        return StripeService._apply_subscription(app_db, sub)

    @staticmethod
    def _apply_subscription(app_db: Session, sub: Dict[str, Any]) -> Dict[str, Any]:
        if not sub:
            return {"status": "error", "message": "empty subscription"}
        meta = sub.get("metadata") or {}
        customer_id = sub.get("customer")
        if isinstance(customer_id, dict):
            customer_id = customer_id.get("id")
        customer_id = str(customer_id).strip() if customer_id else None

        company_id = _resolve_company_id(app_db, meta, customer_id)
        if not company_id:
            logger.warning("Stripe subscription %s: could not resolve company_id", sub.get("id"))
            return {"status": "skipped", "reason": "company_id not resolved"}

        company = app_db.query(Company).filter(Company.id == company_id).first()
        if not company:
            return {"status": "error", "message": "company not found"}

        st = (sub.get("status") or "").strip().lower()
        company.stripe_subscription_id = str(sub.get("id") or "").strip() or company.stripe_subscription_id
        if customer_id:
            company.stripe_customer_id = company.stripe_customer_id or customer_id

        slug = (meta.get("plan_slug") or "").strip()
        if slug:
            company.subscription_plan = slug
        elif not (company.subscription_plan or "").strip():
            company.subscription_plan = "stripe"

        company.subscription_status = _stripe_subscription_status_to_company(st)

        trial_end = sub.get("trial_end")
        if st == "trialing" and trial_end:
            try:
                company.trial_expires_at = datetime.fromtimestamp(int(trial_end), tz=timezone.utc)
            except (TypeError, ValueError, OSError):
                pass

        app_db.add(company)
        app_db.commit()
        return {"status": "ok", "company_id": str(company_id), "subscription_status": company.subscription_status}

    @staticmethod
    def _on_subscription_deleted(app_db: Session, sub: Dict[str, Any]) -> Dict[str, Any]:
        meta = sub.get("metadata") or {}
        customer_id = sub.get("customer")
        if isinstance(customer_id, dict):
            customer_id = customer_id.get("id")
        customer_id = str(customer_id).strip() if customer_id else None

        company_id = _resolve_company_id(app_db, meta, customer_id)
        if not company_id:
            return {"status": "skipped", "reason": "company_id not resolved"}

        company = app_db.query(Company).filter(Company.id == company_id).first()
        if not company:
            return {"status": "error", "message": "company not found"}

        company.stripe_subscription_id = None
        company.subscription_status = "canceled"
        app_db.add(company)
        app_db.commit()
        return {"status": "ok", "company_id": str(company_id), "action": "subscription_deleted"}
