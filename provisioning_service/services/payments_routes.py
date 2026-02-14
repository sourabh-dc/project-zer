from datetime import timezone, datetime, timedelta
import stripe
from fastapi import HTTPException, APIRouter, Request, Depends
from fastapi import WebSocket, WebSocketDisconnect
import asyncio
from sqlalchemy.orm import Session
from sqlalchemy import text
import uuid
import os
import httpx

from provisioning_service.Models import TenantSubscription, SubscriptionPlan, PlanPrice, SpendingEvent, User
from provisioning_service.Schemas import CheckoutRequest
from provisioning_service.core.config import SETTINGS
from provisioning_service.core.db_config import get_db
from provisioning_service.core.user_auth import check_user_authorization
from provisioning_service.utils.logger import logger

router = APIRouter(prefix="/payments", tags=["Payments"])

stripe.api_key = SETTINGS.STRIPE_SECRET_KEY


def _plan_pricing(db: Session, plan_code: str, billing_cycle: str):
    price = db.query(PlanPrice).filter(PlanPrice.plan_code == plan_code).first()
    if not price:
        return None
    cycle = (billing_cycle or "monthly").lower()
    if cycle == "monthly":
        return int(price.price_monthly_minor), price.currency
    if cycle == "quarterly":
        return int(price.price_quarterly_minor), price.currency
    if cycle == "yearly":
        return int(price.price_yearly_minor), price.currency
    return None


def _period_end(start: datetime, cycle: str) -> datetime:
    cycle = (cycle or "monthly").lower()
    if cycle == "monthly":
        return start + timedelta(days=30)
    if cycle == "quarterly":
        return start + timedelta(days=90)
    if cycle == "yearly":
        return start + timedelta(days=365)
    return start + timedelta(days=30)

@router.post("/create-checkout-session")
async def create_checkout_session(
    data: CheckoutRequest,
    db: Session = Depends(get_db),
    ctx = Depends(check_user_authorization("tenant.admin"))
):
    try:
        if not SETTINGS.STRIPE_SECRET_KEY:
            raise HTTPException(status_code=400, detail="Stripe not configured")

        price_amount, currency = _plan_pricing(db, data.plan_code, data.billing_cycle)
        if not price_amount:
            raise HTTPException(status_code=404, detail="Plan price not found")

        metadata = {
            "tenant_id": data.tenant_id,
            "plan_code": data.plan_code,
            "billing_cycle": data.billing_cycle or "monthly"
        }
        stripe_customer_id = getattr(data, "stripe_customer_id", None)
        if not stripe_customer_id and getattr(data, "email", None):
            customer = stripe.Customer.create(email=data.email, metadata={"tenant_id": data.tenant_id})
            stripe_customer_id = customer.id

        line_items = [{
            "price_data": {
                "currency": currency,
                "product_data": {"name": f"Plan {data.plan_code} ({metadata['billing_cycle']})"},
                "unit_amount": price_amount,
                "recurring": {"interval": metadata["billing_cycle"] if metadata["billing_cycle"] in ["month", "year"] else "month"}
            },
            "quantity": 1,
        }]

        session = stripe.checkout.Session.create(
            customer=stripe_customer_id,
            payment_method_types=["card"],
            mode="subscription",
            line_items=line_items,
            success_url="http://127.0.0.1:8000/payments/success",
            cancel_url="http://127.0.0.1:8000/payments/cancel",
            metadata=metadata
        )
        return {"checkout_url": session.url, "session_id": session.id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Checkout session failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/create-portal-session")
async def create_portal_session(
    cust_id: str,
    ctx = Depends(check_user_authorization("tenant.admin"))
):
    try:
        session = stripe.billing_portal.Session.create(
            customer=cust_id,
            return_url="http://localhost:8000"
        )
        return {"portal_url": session.url}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/webhook")
async def stripe_webhook(request: Request, db=Depends(get_db)):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    endpoint_secret = SETTINGS.STRIPE_WEBHOOK_SECRET
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, endpoint_secret
        )
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    event_type = event.get("type")
    data = event.get("data", {}).get("object", {})

    def upsert_subscription(tenant_id, plan_code, billing_cycle, external_id, status, is_active, payment_method, amount_minor=None, currency=None):
        now = datetime.now(timezone.utc)
        sub = db.query(TenantSubscription).filter(TenantSubscription.tenant_id == tenant_id, TenantSubscription.plan_code == plan_code).first()
        if not sub:
            sub = TenantSubscription(
                tenant_id=tenant_id,
                plan_code=plan_code,
            )
            db.add(sub)
        sub.external_id = external_id
        sub.billing_cycle = billing_cycle
        sub.current_period_start = now
        sub.current_period_end = _period_end(now, billing_cycle)
        sub.is_trial = False
        sub.is_active = is_active
        sub.payment_method = payment_method
        sub.status = status
        db.commit()
        return {"status": "ok"}

    if event_type == "checkout.session.completed":
        tenant_id = data.get("metadata", {}).get("tenant_id")
        plan_code = data.get("metadata", {}).get("plan_code")
        billing_cycle = data.get("metadata", {}).get("billing_cycle", "monthly")
        upsert_subscription(tenant_id, plan_code, billing_cycle, data.get("id"), "active", True, data.get("mode"))
        return {"status": "ok"}

    if event_type == "invoice.payment_succeeded":
        return {"status": "ok"}

    if event_type == "invoice.payment_failed":
        return {"status": "failed"}

    if event_type == "payment_intent.succeeded":
        return {"status": "ok"}

    if event_type == "payment_intent.payment_failed":
        return {"status": "failed"}

    if event_type in ["customer.subscription.deleted", "customer.subscription.updated"]:
        return {"status": "ok"}

    return {"status": "ignored"}


@router.websocket("/ws/subscription-status/{tenant_id}")
async def subscription_status_websocket(
        websocket: WebSocket,
        tenant_id: str,
        db: Session = Depends(get_db)
):
    """
    WebSocket endpoint to check subscription status in real-time.
    Sends periodic updates about subscription creation/status for a tenant.
    """
    await websocket.accept()
    logger.info(f"WebSocket connected for tenant {tenant_id}")

    try:
        while True:
            # Query the current subscription status
            now = datetime.now(timezone.utc)
            subscription = db.query(TenantSubscription).filter(
                TenantSubscription.tenant_id == tenant_id,
                TenantSubscription.is_active == True,
                TenantSubscription.current_period_end > now
            ).first()

            if subscription:
                # Subscription found
                plan = db.query(SubscriptionPlan).filter_by(code=subscription.plan_code).first()

                response = {
                    "status": "active",
                    "subscription_exists": True,
                    "subscription_id": str(subscription.id),
                    "plan_code": subscription.plan_code,
                    "plan_name": plan.name if plan else None,
                    "is_active": subscription.is_active,
                    "is_trial": subscription.is_trial,
                    "current_period_end": subscription.current_period_end.isoformat() if subscription.current_period_end else None,
                    "timestamp": now.isoformat()
                }
            else:
                # No active subscription
                response = {
                    "status": "no_subscription",
                    "subscription_exists": False,
                    "timestamp": now.isoformat()
                }

            # Send status to a client
            await websocket.send_json(response)

            # Wait 3 seconds before the next check
            await asyncio.sleep(3)

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for tenant {tenant_id}")
    except Exception as e:
        logger.error(f"WebSocket error for tenant {tenant_id}: {e}", exc_info=True)
        await websocket.close(code=1011, reason="Internal server error")

