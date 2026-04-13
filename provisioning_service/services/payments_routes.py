from datetime import timezone, datetime, timedelta
import stripe
from fastapi import HTTPException, APIRouter, Request, Depends
from fastapi import WebSocket, WebSocketDisconnect
import asyncio
from sqlalchemy.orm import Session

from provisioning_service.Models import TenantSubscription, SubscriptionPlan, PlanPrice, Tenant, Mandate
from provisioning_service.Schemas import CheckoutRequest
from provisioning_service.core.config import SETTINGS
from provisioning_service.core.db_config import get_db
from provisioning_service.core.user_auth import check_user_authorization
from provisioning_service.core.helpers.outbox_helpers import create_outbox_event
from provisioning_service.utils.logger import logger

GRACE_PERIOD_DAYS = getattr(SETTINGS, "PAYMENT_GRACE_PERIOD_DAYS", 3)

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

        # Outbox audit event
        try:
            create_outbox_event(db, data.tenant_id, "payment.checkout_session.created", {
                "tenant_id": data.tenant_id,
                "plan_code": data.plan_code,
                "billing_cycle": data.billing_cycle or "monthly",
                "session_id": session.id,
            })
            db.commit()
        except Exception as _oe:
            logger.warning(f"Outbox failed for payment.checkout_session.created: {_oe}")

        return {"checkout_url": session.url, "session_id": session.id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Checkout session failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/create-portal-session")
async def create_portal_session(
    cust_id: str,
    db: Session = Depends(get_db),
    ctx = Depends(check_user_authorization("tenant.admin"))
):
    try:
        session = stripe.billing_portal.Session.create(
            customer=cust_id,
            return_url="http://localhost:8000"
        )

        # Outbox audit event
        tenant_id = ctx["tenant_id"] if isinstance(ctx, dict) else ctx.tenant_id
        try:
            create_outbox_event(db, tenant_id, "payment.portal_session.created", {
                "stripe_customer_id": cust_id,
            })
            db.commit()
        except Exception as _oe:
            logger.warning(f"Outbox failed for payment.portal_session.created: {_oe}")

        return {"portal_url": session.url}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/webhook")
async def stripe_webhook(request: Request, db=Depends(get_db)):
    """
    Comprehensive Stripe webhook handler.

    Handles the full subscription lifecycle for the Spotify-style auto-pay model:

    - ``invoice.payment_succeeded``   — extend access, clear grace period
    - ``invoice.payment_failed``      — start grace period, warn tenant
    - ``customer.subscription.updated`` — trial→active, active→past_due, etc.
    - ``customer.subscription.deleted`` — revoke access
    - ``customer.subscription.trial_will_end`` — pre-trial-end reminder
    - ``checkout.session.completed``  — legacy checkout flow
    - ``setup_intent.succeeded``      — payment method saved confirmation
    """
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

    # ── Routing ─────────────────────────────────────────────────────

    if event_type == "invoice.payment_succeeded":
        return _handle_invoice_paid(db, data)

    if event_type == "invoice.payment_failed":
        return _handle_invoice_failed(db, data)

    if event_type == "customer.subscription.updated":
        return _handle_subscription_updated(db, data)

    if event_type == "customer.subscription.deleted":
        return _handle_subscription_deleted(db, data)

    if event_type == "customer.subscription.trial_will_end":
        return _handle_trial_will_end(db, data)

    if event_type == "checkout.session.completed":
        return _handle_checkout_completed(db, data)

    if event_type == "setup_intent.succeeded":
        return _handle_setup_intent_succeeded(db, data)

    logger.debug(f"Unhandled Stripe event: {event_type}")
    return {"status": "ignored"}


# ── Helpers ─────────────────────────────────────────────────────────

def _find_subscription_by_stripe_id(db: Session, stripe_sub_id: str):
    """Look up internal TenantSubscription by Stripe subscription ID."""
    return db.query(TenantSubscription).filter(
        TenantSubscription.external_id == stripe_sub_id
    ).first()


def _find_subscription_by_customer(db: Session, stripe_customer_id: str):
    """Fall back: find subscription via Mandate → tenant_id."""
    mandate = db.query(Mandate).filter(
        Mandate.stripe_customer_id == stripe_customer_id,
        Mandate.status == "active",
    ).first()
    if not mandate or not mandate.tenant_id:
        return None
    return db.query(TenantSubscription).filter(
        TenantSubscription.tenant_id == mandate.tenant_id,
        TenantSubscription.is_active == True,
    ).first()


# ── invoice.payment_succeeded ──────────────────────────────────────

def _handle_invoice_paid(db: Session, invoice: dict):
    """
    Called when Stripe successfully charges the customer.

    This fires:
      - At the end of the 7-day trial (first real charge)
      - On every subsequent billing cycle

    Actions:
      1. Mark subscription as active.
      2. Extend current_period_end to the next billing cycle.
      3. Clear any grace period / payment failure state.
    """
    stripe_sub_id = invoice.get("subscription")
    if not stripe_sub_id:
        return {"status": "ok", "detail": "no subscription on invoice"}

    sub = _find_subscription_by_stripe_id(db, stripe_sub_id)
    if not sub:
        sub = _find_subscription_by_customer(db, invoice.get("customer"))
    if not sub:
        logger.warning(f"invoice.payment_succeeded: no internal sub for {stripe_sub_id}")
        return {"status": "ok", "detail": "subscription not found"}

    now = datetime.now(timezone.utc)

    # Transition from trialing → active on first real charge
    was_trial = sub.is_trial

    sub.status = "active"
    sub.is_active = True
    sub.is_trial = False
    sub.current_period_start = now
    sub.current_period_end = _period_end(now, sub.billing_cycle)
    sub.payment_failed_at = None
    sub.grace_period_end = None
    sub.last_invoice_id = invoice.get("id")

    db.commit()

    # Outbox audit event
    tenant_id = str(sub.tenant_id)
    event_subtype = "subscription.trial_converted" if was_trial else "subscription.renewed"
    try:
        create_outbox_event(db, tenant_id, f"payment.{event_subtype}", {
            "tenant_id": tenant_id,
            "plan_code": sub.plan_code,
            "stripe_invoice_id": invoice.get("id"),
            "amount_paid": invoice.get("amount_paid"),
            "currency": invoice.get("currency"),
            "was_trial": was_trial,
        })
        db.commit()
    except Exception as _oe:
        logger.warning(f"Outbox failed for payment.{event_subtype}: {_oe}")

    logger.info(
        f"invoice.payment_succeeded: tenant={tenant_id} plan={sub.plan_code} "
        f"{'trial_converted' if was_trial else 'renewed'}"
    )
    return {"status": "ok"}


# ── invoice.payment_failed ─────────────────────────────────────────

def _handle_invoice_failed(db: Session, invoice: dict):
    """
    Called when Stripe fails to charge the customer.

    Actions:
      1. Set subscription to ``past_due``.
      2. Start a grace period (configurable, default 3 days).
      3. If grace period already expired, deactivate access.
      4. Emit outbox event for downstream notification.
    """
    stripe_sub_id = invoice.get("subscription")
    if not stripe_sub_id:
        return {"status": "ok", "detail": "no subscription on invoice"}

    sub = _find_subscription_by_stripe_id(db, stripe_sub_id)
    if not sub:
        sub = _find_subscription_by_customer(db, invoice.get("customer"))
    if not sub:
        logger.warning(f"invoice.payment_failed: no internal sub for {stripe_sub_id}")
        return {"status": "ok", "detail": "subscription not found"}

    now = datetime.now(timezone.utc)
    tenant_id = str(sub.tenant_id)

    if sub.grace_period_end and now > sub.grace_period_end:
        # Grace period expired — revoke access
        sub.status = "unpaid"
        sub.is_active = False
        sub.last_invoice_id = invoice.get("id")
        db.commit()

        try:
            create_outbox_event(db, tenant_id, "payment.access_revoked", {
                "tenant_id": tenant_id,
                "plan_code": sub.plan_code,
                "stripe_invoice_id": invoice.get("id"),
                "reason": "payment_failed_grace_expired",
            })
            db.commit()
        except Exception as _oe:
            logger.warning(f"Outbox failed for payment.access_revoked: {_oe}")

        logger.warning(f"Access REVOKED for tenant={tenant_id} — grace period expired")
        return {"status": "ok", "action": "access_revoked"}

    # Start or continue grace period
    sub.status = "past_due"
    sub.payment_failed_at = sub.payment_failed_at or now
    sub.grace_period_end = sub.grace_period_end or (now + timedelta(days=GRACE_PERIOD_DAYS))
    sub.last_invoice_id = invoice.get("id")
    db.commit()

    try:
        create_outbox_event(db, tenant_id, "payment.invoice_failed", {
            "tenant_id": tenant_id,
            "plan_code": sub.plan_code,
            "stripe_invoice_id": invoice.get("id"),
            "attempt_count": invoice.get("attempt_count"),
            "grace_period_end": sub.grace_period_end.isoformat(),
        })
        db.commit()
    except Exception as _oe:
        logger.warning(f"Outbox failed for payment.invoice_failed: {_oe}")

    logger.warning(
        f"invoice.payment_failed: tenant={tenant_id} — grace period until {sub.grace_period_end.isoformat()}"
    )
    return {"status": "ok", "action": "grace_period_started"}


# ── customer.subscription.updated ──────────────────────────────────

def _handle_subscription_updated(db: Session, stripe_sub: dict):
    """
    Called on any subscription state change (trial→active, active→past_due, etc.).

    Stripe fires this when:
      - Trial ends and first invoice succeeds (status: trialing → active)
      - Payment fails (status: active → past_due)
      - Payment recovered (status: past_due → active)
      - Subscription canceled (status: → canceled)
    """
    stripe_sub_id = stripe_sub.get("id")
    new_status = stripe_sub.get("status")  # trialing, active, past_due, canceled, unpaid

    sub = _find_subscription_by_stripe_id(db, stripe_sub_id)
    if not sub:
        sub = _find_subscription_by_customer(db, stripe_sub.get("customer"))
    if not sub:
        logger.debug(f"subscription.updated: no internal sub for {stripe_sub_id}")
        return {"status": "ok"}

    now = datetime.now(timezone.utc)
    tenant_id = str(sub.tenant_id)

    if new_status == "active":
        sub.status = "active"
        sub.is_active = True
        sub.is_trial = False
        sub.payment_failed_at = None
        sub.grace_period_end = None
        # Update period from Stripe data
        period_end = stripe_sub.get("current_period_end")
        if period_end:
            sub.current_period_end = datetime.fromtimestamp(period_end, tz=timezone.utc)
        period_start = stripe_sub.get("current_period_start")
        if period_start:
            sub.current_period_start = datetime.fromtimestamp(period_start, tz=timezone.utc)

    elif new_status == "trialing":
        sub.status = "trialing"
        sub.is_trial = True
        sub.is_active = True
        trial_end = stripe_sub.get("trial_end")
        if trial_end:
            sub.current_period_end = datetime.fromtimestamp(trial_end, tz=timezone.utc)

    elif new_status == "past_due":
        sub.status = "past_due"
        sub.is_active = True  # still active during grace
        sub.payment_failed_at = sub.payment_failed_at or now
        sub.grace_period_end = sub.grace_period_end or (now + timedelta(days=GRACE_PERIOD_DAYS))

    elif new_status in ("canceled", "unpaid"):
        sub.status = new_status
        sub.is_active = False
        sub.canceled_at = sub.canceled_at or now

    db.commit()

    try:
        create_outbox_event(db, tenant_id, "payment.subscription_updated", {
            "tenant_id": tenant_id,
            "plan_code": sub.plan_code,
            "new_status": new_status,
            "stripe_subscription_id": stripe_sub_id,
        })
        db.commit()
    except Exception as _oe:
        logger.warning(f"Outbox failed for payment.subscription_updated: {_oe}")

    logger.info(f"subscription.updated: tenant={tenant_id} status={new_status}")
    return {"status": "ok"}


# ── customer.subscription.deleted ──────────────────────────────────

def _handle_subscription_deleted(db: Session, stripe_sub: dict):
    """
    Called when a subscription is fully canceled/deleted.

    Revokes access and updates the mandate to 'expired'.
    """
    stripe_sub_id = stripe_sub.get("id")

    sub = _find_subscription_by_stripe_id(db, stripe_sub_id)
    if not sub:
        logger.debug(f"subscription.deleted: no internal sub for {stripe_sub_id}")
        return {"status": "ok"}

    now = datetime.now(timezone.utc)
    tenant_id = str(sub.tenant_id)

    sub.status = "canceled"
    sub.is_active = False
    sub.canceled_at = now

    # Expire the mandate
    mandate = db.query(Mandate).filter(
        Mandate.stripe_subscription_id == stripe_sub_id,
    ).first()
    if mandate:
        mandate.status = "expired"

    db.commit()

    try:
        create_outbox_event(db, tenant_id, "payment.subscription_deleted", {
            "tenant_id": tenant_id,
            "plan_code": sub.plan_code,
            "stripe_subscription_id": stripe_sub_id,
        })
        db.commit()
    except Exception as _oe:
        logger.warning(f"Outbox failed for payment.subscription_deleted: {_oe}")

    logger.info(f"subscription.deleted: tenant={tenant_id} — access revoked")
    return {"status": "ok"}


# ── customer.subscription.trial_will_end ───────────────────────────

def _handle_trial_will_end(db: Session, stripe_sub: dict):
    """
    Fired 3 days before the trial ends (Stripe default).

    Emits an outbox event so the communication module can send a
    "your trial is ending" reminder email.
    """
    stripe_sub_id = stripe_sub.get("id")

    sub = _find_subscription_by_stripe_id(db, stripe_sub_id)
    if not sub:
        return {"status": "ok"}

    tenant_id = str(sub.tenant_id)
    trial_end = stripe_sub.get("trial_end")
    trial_end_dt = datetime.fromtimestamp(trial_end, tz=timezone.utc) if trial_end else None

    try:
        create_outbox_event(db, tenant_id, "payment.trial_ending", {
            "tenant_id": tenant_id,
            "plan_code": sub.plan_code,
            "trial_ends_at": trial_end_dt.isoformat() if trial_end_dt else None,
            "stripe_subscription_id": stripe_sub_id,
        })
        db.commit()
    except Exception as _oe:
        logger.warning(f"Outbox failed for payment.trial_ending: {_oe}")

    logger.info(f"trial_will_end: tenant={tenant_id} ends={trial_end_dt}")
    return {"status": "ok"}


# ── checkout.session.completed (legacy) ────────────────────────────

def _handle_checkout_completed(db: Session, data: dict):
    """Legacy checkout flow — upserts subscription from checkout metadata."""
    tenant_id = data.get("metadata", {}).get("tenant_id")
    plan_code = data.get("metadata", {}).get("plan_code")
    billing_cycle = data.get("metadata", {}).get("billing_cycle", "monthly")

    if not tenant_id or not plan_code:
        return {"status": "ok", "detail": "missing metadata"}

    now = datetime.now(timezone.utc)
    sub = db.query(TenantSubscription).filter(
        TenantSubscription.tenant_id == tenant_id,
        TenantSubscription.plan_code == plan_code,
    ).first()
    if not sub:
        sub = TenantSubscription(tenant_id=tenant_id, plan_code=plan_code)
        db.add(sub)

    sub.external_id = data.get("subscription") or data.get("id")
    sub.billing_cycle = billing_cycle
    sub.current_period_start = now
    sub.current_period_end = _period_end(now, billing_cycle)
    sub.is_trial = False
    sub.is_active = True
    sub.payment_method = data.get("mode", "card")
    sub.status = "active"
    db.commit()

    try:
        create_outbox_event(db, tenant_id, "payment.checkout.completed", {
            "tenant_id": tenant_id,
            "plan_code": plan_code,
            "billing_cycle": billing_cycle,
            "stripe_session_id": data.get("id"),
        })
        db.commit()
    except Exception as _oe:
        logger.warning(f"Outbox failed for payment.checkout.completed: {_oe}")

    return {"status": "ok"}


# ── setup_intent.succeeded ─────────────────────────────────────────

def _handle_setup_intent_succeeded(db: Session, setup_intent: dict):
    """
    Fired when the customer successfully confirms the SetupIntent.

    This means the payment method is saved and the mandate is authorised.
    We log it as an audit event — the actual subscription creation happens
    when the frontend calls ``POST /onboarding/activate``.
    """
    customer_id = setup_intent.get("customer")
    payment_method = setup_intent.get("payment_method")
    plan_code = setup_intent.get("metadata", {}).get("plan_code")

    mandate = db.query(Mandate).filter(
        Mandate.stripe_customer_id == customer_id,
        Mandate.status == "pending",
    ).first()

    tenant_id = str(mandate.tenant_id) if mandate and mandate.tenant_id else None

    try:
        create_outbox_event(
            db,
            tenant_id or "00000000-0000-0000-0000-000000000000",
            "payment.setup_intent_succeeded",
            {
                "stripe_customer_id": customer_id,
                "payment_method_id": payment_method,
                "plan_code": plan_code,
                "mandate_id": str(mandate.mandate_id) if mandate else None,
            },
        )
        db.commit()
    except Exception as _oe:
        logger.warning(f"Outbox failed for payment.setup_intent_succeeded: {_oe}")

    logger.info(f"setup_intent.succeeded: customer={customer_id} pm={payment_method}")
    return {"status": "ok"}


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

