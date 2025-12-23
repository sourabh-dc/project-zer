from datetime import timezone, datetime, timedelta
import stripe
from fastapi.responses import JSONResponse
from fastapi import HTTPException, APIRouter, Request, Depends
from fastapi import WebSocket, WebSocketDisconnect
import asyncio
from sqlalchemy.orm import Session

from Models import TenantSubscription, SubscriptionPlan
from Schemas import CheckoutRequest
from core.config import SETTINGS
from core.db_config import get_db
from utils.logger import logger

router = APIRouter(prefix="/payments", tags=["Payments"])

stripe.api_key=SETTINGS.STRIPE_SECRET_KEY

@router.post("/create-checkout-session")
async def create_checkout_session(data: CheckoutRequest):
    try:
        # If using predefined Stripe Price IDs (recommended for subscriptions)
        if data.price_id:
            line_items = [{
                "price": data.price_id,
                "quantity": data.quantity,
            }]
        else:
            # If you want to accept a raw amount from frontend (one-time payments)
            line_items = [{
                "price_data": {
                    "currency": data.currency,
                    "product_data": {"name": "Custom Payment"},
                    "unit_amount": data.amount,  # amount in cents
                }
            }]
        metadata = {
            "tenant_id": data.tenant_id,
            "plan_code": data.plan_code,
            "billing_cycle": data.billing_cycle
        }

        session = stripe.checkout.Session.create(
            payment_method_types=["card"],  # could extend to ["card", "upi", "PayPal"] if supported
            mode=data.mode,
            line_items=line_items,
            customer_email=data.customer_email,
            success_url="https://yourdomain.com/success?session_id={CHECKOUT_SESSION_ID}", #replace it with actual success page
            cancel_url="https://yourdomain.com/cancel",
            metadata=metadata
        )

        return JSONResponse({"checkout_url": session.url})
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/webhook")
async def stripe_webhook(request: Request, db=get_db()):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    endpoint_secret = SETTINGS.STRIPE_WEBHOOK_SECRET

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, endpoint_secret
        )
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    # Handle events
    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        tenant_id = session["metadata"]["tenant_id"]
        plan_code = session["metadata"]["plan_code"]
        billing_cycle = session["metadata"]["billing_cycle"]
        current_period_start = datetime.now(timezone.utc)
        current_period_end = current_period_start + timedelta(days=30 if billing_cycle == "monthly" else 365)

        """Create a new subscription"""
        tenant_subscription = TenantSubscription(tenant_id=tenant_id, plan_code=plan_code,
                                                 current_period_start=current_period_start, is_trial=False,
                                                 current_period_end=current_period_end,
                                                 payment_method=session["mode"],
                                                 is_active=True, external_id=session["id"])

        db.add(tenant_subscription)
        db.commit()
        return tenant_subscription
    elif event["type"] == "invoice.payment_failed":
        # ❌ Handle failed payments
        pass

    return {"status": "success"}

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
