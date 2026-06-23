import uuid
import stripe
from datetime import datetime, timezone, timedelta
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from provisioning_service.Models import (
    Tenant, User, UserIdentity, UserRole, Role, Permission, RolePermission,
    TenantUserRole, TenantRole, TenantRolePermission,
    Mandate, TenantSubscription, SubscriptionPlan, PlanFeature, PlanPrice,
)
from provisioning_service.Schemas import (
    MandateCreateRequest, MandateResponse,
    MandateActivateRequest, MandateActivateResponse,
    SubscriptionContext,
)
from provisioning_service.core.helpers.signin_context import (
    build_subscription_context,
)
from provisioning_service.core.helpers.outbox_helpers import create_outbox_event, dispatch_outbox_to_queue
from provisioning_service.utils.metrics import req_total
from provisioning_service.core.db_config import get_db
from provisioning_service.core.config import SETTINGS
from provisioning_service.utils.logger import logger

stripe.api_key = SETTINGS.STRIPE_SECRET_KEY

router = APIRouter(prefix="/onboarding", tags=["onboarding tenant"])

# =====================================================================
# MANDATE-FIRST ONBOARDING (New Flow — Token-Driven Auth)
# =====================================================================

@router.post("/register", response_model=MandateResponse, status_code=201)
async def create_mandate(
    req: MandateCreateRequest,
    db: Session = Depends(get_db),
):
    """
    Step 1: Create a billing mandate BEFORE any tenant/user data is persisted.

    Creates a Stripe Customer and a SetupIntent configured for **off-session
    recurring charges** (the "Spotify model").  The SetupIntent's
    ``usage='off_session'`` tells Stripe to collect a mandate authorisation
    from the cardholder, allowing us to debit them automatically when the
    trial ends and on every subsequent billing cycle.

    No tenant or user rows are written until ``POST /onboarding/activate``
    is called after the payment method is confirmed on the frontend.

    Trial is mandatory and always 7 days.
    """
    try:
        # If a pending mandate already exists, return it (idempotent — user can retry)
        existing = db.query(Mandate).filter(
            Mandate.email == req.email, Mandate.status.in_(["pending", "active"])
        ).first()
        if existing:
            if existing.status == "active":
                raise HTTPException(status_code=409, detail="Tenant already activated for this email")
            # Pending mandate — return it so the frontend can continue to card setup
            return MandateResponse(
                mandate_id=str(existing.mandate_id),
                status=existing.status,
                stripe_customer_id=existing.stripe_customer_id,
                client_secret=existing.stripe_setup_intent_secret,
            )

        existing_tenant = db.query(Tenant).filter(Tenant.email == req.email).first()
        if existing_tenant:
            raise HTTPException(status_code=409, detail="Tenant email already registered")

        # Create Stripe customer
        stripe_customer = stripe.Customer.create(
            email=req.admin_email,
            name=f"{req.admin_firstname} {req.admin_lastname}",
            metadata={"tenant_name": req.tenant_name, "plan_code": req.plan_code},
        )

        # ── Create SetupIntent for off-session recurring charges ───────
        # usage="off_session" signals that saved payment method will be used
        # for future charges without the cardholder being present (auto-pay).
        # mandate_data tells Stripe to present a mandate agreement (required
        # for India RBI e-mandates, EU SCA, and best practice everywhere).
        currency = (req.default_currency or "GBP").lower()

        # Look up the plan price to include in the mandate notification
        plan_price = db.query(PlanPrice).filter(PlanPrice.plan_code == req.plan_code).first()
        amount_hint = plan_price.price_monthly_minor if plan_price else 0

        setup_intent = stripe.SetupIntent.create(
            customer=stripe_customer.id,
            payment_method_types=["card"],
            usage="off_session",
            metadata={
                "plan_code": req.plan_code,
                "billing_cycle": req.billing_cycle,
                "mandate_type": "recurring_auto_pay",
            },
        )

        # Trial is ALWAYS mandatory — 7 days, non-bypassable
        mandate = Mandate(
            mandate_id=uuid.uuid4(),
            email=req.email,
            tenant_name=req.tenant_name,
            tenant_type=req.tenant_type,
            admin_email=req.admin_email,
            admin_firstname=req.admin_firstname,
            admin_lastname=req.admin_lastname,
            plan_code=req.plan_code,
            billing_cycle=req.billing_cycle,
            is_trial=True,      # mandatory trial — cannot be bypassed
            trial_days=7,       # fixed 7-day trial
            stripe_customer_id=stripe_customer.id,
            stripe_setup_intent_secret=setup_intent.client_secret,
            status="pending",
            phone=req.phone,
            default_currency=req.default_currency,
            timezone=req.timezone,
            locale=req.locale,
            industry=req.industry,
            registration_number=req.registration_number,
            billing_address=req.billing_address,
            primary_domain=req.primary_domain,
            billing_email=req.billing_email,
            tech_contact_email=req.tech_contact_email,
            support_contact_email=req.support_contact_email,
        )
        db.add(mandate)
        db.commit()
        db.refresh(mandate)

        logger.info(f"Mandate created: {mandate.mandate_id} for {req.email}")

        return MandateResponse(
            mandate_id=str(mandate.mandate_id),
            status="pending",
            stripe_customer_id=stripe_customer.id,
            client_secret=setup_intent.client_secret,
        )
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Mandate creation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create mandate")


def _get_or_create_stripe_product(plan_code: str) -> str:
    """Return a Stripe Product ID for the given plan, creating one if it doesn't exist."""
    product_name = f"ZeroQue {plan_code}"
    results = stripe.Product.search(query=f'name:"{product_name}"', limit=1)
    if results.data:
        return results.data[0].id
    product = stripe.Product.create(name=product_name, metadata={"plan_code": plan_code})
    return product.id


@router.post("/activate", response_model=MandateActivateResponse, status_code=201)
async def activate_mandate(
    req: MandateActivateRequest,
    db: Session = Depends(get_db),
):
    """
    Step 2: Activate the mandate after the payment method is confirmed.

    The frontend has already confirmed the SetupIntent (via Stripe.js
    ``confirmCardSetup``).  This endpoint:

      1. Retrieves the confirmed SetupIntent to get the saved payment method.
      2. Sets the payment method as the customer's default for invoices.
      3. Creates a Stripe Subscription with:
         - ``collection_method='charge_automatically'`` (Spotify model)
         - ``default_payment_method`` = saved card from SetupIntent
         - ``trial_period_days=7`` (mandatory, non-bypassable)
         - Real pricing from the PlanPrice table
      4. Persists Tenant, TenantSubscription, and updates the Mandate.
      5. Emits a ``tenant.signup`` outbox event for downstream processing.

    When the 7-day trial ends Stripe will automatically create an invoice
    and charge the saved payment method — no user intervention needed.
    """
    try:
        mandate = db.query(Mandate).filter(
            Mandate.mandate_id == req.mandate_id,
            Mandate.status == "pending",
        ).first()
        if not mandate:
            raise HTTPException(status_code=404, detail="Mandate not found or already activated")

        # ── Retrieve confirmed SetupIntent to get payment method ────
        # The client_secret contains the SetupIntent ID before the "_secret_" part
        si_id = mandate.stripe_setup_intent_secret.split("_secret_")[0]
        setup_intent = stripe.SetupIntent.retrieve(si_id)

        if setup_intent.status != "succeeded":
            raise HTTPException(
                status_code=400,
                detail=f"Payment method not yet confirmed (SetupIntent status: {setup_intent.status}). "
                       "Complete card setup on the frontend first.",
            )

        payment_method_id = setup_intent.payment_method
        if not payment_method_id:
            raise HTTPException(status_code=400, detail="No payment method found on confirmed SetupIntent")

        # ── Attach payment method as customer default ───────────────
        # This ensures all future invoices charge this card automatically.
        stripe.PaymentMethod.attach(payment_method_id, customer=mandate.stripe_customer_id)
        stripe.Customer.modify(
            mandate.stripe_customer_id,
            invoice_settings={"default_payment_method": payment_method_id},
        )

        # ── Resolve real pricing from PlanPrice table ───────────────
        currency = (mandate.default_currency or "GBP").lower()
        billing_cycle = (mandate.billing_cycle or "monthly").lower()

        plan_price = db.query(PlanPrice).filter(PlanPrice.plan_code == mandate.plan_code).first()
        if plan_price:
            if billing_cycle == "yearly":
                unit_amount = int(plan_price.price_yearly_minor)
                stripe_interval = "year"
            elif billing_cycle == "quarterly":
                unit_amount = int(plan_price.price_quarterly_minor)
                stripe_interval = "month"
                stripe_interval_count = 3
            else:  # monthly
                unit_amount = int(plan_price.price_monthly_minor)
                stripe_interval = "month"
            currency = plan_price.currency.lower() if plan_price.currency else currency
        else:
            # Fallback: zero-amount (admin must configure pricing)
            unit_amount = 0
            stripe_interval = "month"
            logger.warning(f"No PlanPrice found for {mandate.plan_code} — subscription created with amount=0")

        # ── Create Stripe Subscription (auto-charge with mandate) ───
        recurring = {"interval": stripe_interval}
        if billing_cycle == "quarterly":
            recurring["interval_count"] = 3

        sub_params = {
            "customer": mandate.stripe_customer_id,
            "default_payment_method": payment_method_id,
            "collection_method": "charge_automatically",
            "items": [{
                "price_data": {
                    "currency": currency,
                    "product": _get_or_create_stripe_product(mandate.plan_code),
                    "unit_amount": unit_amount,
                    "recurring": recurring,
                },
            }],
            "trial_period_days": 7,  # mandatory 7-day trial — non-bypassable
            "payment_settings": {
                "payment_method_types": ["card"],
                "save_default_payment_method": "on_subscription",
            },
            "metadata": {
                "plan_code": mandate.plan_code,
                "billing_cycle": mandate.billing_cycle,
                "mandate_id": str(mandate.mandate_id),
            },
        }

        stripe_sub = stripe.Subscription.create(**sub_params)
        mandate.stripe_subscription_id = stripe_sub.id

        # ── Create Tenant ───────────────────────────────────────────
        now = datetime.now(timezone.utc)
        tenant = Tenant(
            tenant_id=uuid.uuid4(),
            tenant_name=mandate.tenant_name,
            tenant_type=mandate.tenant_type,
            email=mandate.email,
            phone=mandate.phone,
            default_currency=mandate.default_currency,
            timezone=mandate.timezone,
            locale=mandate.locale,
            industry=mandate.industry,
            registration_number=mandate.registration_number,
            billing_address=mandate.billing_address,
            primary_domain=mandate.primary_domain,
            billing_email=mandate.billing_email,
            tech_contact_email=mandate.tech_contact_email,
            support_contact_email=mandate.support_contact_email,
            active=True,
        )
        db.add(tenant)
        db.flush()

        # ── Create TenantSubscription ───────────────────────────────
        trial_end = now + timedelta(days=7)
        subscription = TenantSubscription(
            tenant_id=tenant.tenant_id,
            plan_code=mandate.plan_code,
            billing_cycle=mandate.billing_cycle,
            payment_method="card",
            external_id=stripe_sub.id,
            current_period_start=now,
            current_period_end=trial_end,
            is_active=True,
            is_trial=True,
            status="trialing",
        )
        db.add(subscription)
        db.flush()

        # ── Update mandate ──────────────────────────────────────────
        mandate.status = "active"
        mandate.tenant_id = tenant.tenant_id
        mandate.activated_at = now
        mandate.expires_at = trial_end

        # ── Emit outbox event ───────────────────────────────────────
        event_data = {
            "tenant_id": str(tenant.tenant_id),
            "mandate_id": str(mandate.mandate_id),
            "tenant_name": mandate.tenant_name,
            "email": mandate.email,
            "admin_email": mandate.admin_email,
            "admin_firstname": mandate.admin_firstname,
            "admin_lastname": mandate.admin_lastname,
            "plan_code": mandate.plan_code,
            "billing_cycle": mandate.billing_cycle,
            "is_trial": True,
            "trial_days": 7,
            "stripe_customer_id": mandate.stripe_customer_id,
            "stripe_subscription_id": stripe_sub.id,
        }
        outbox = create_outbox_event(
            db, tenant.tenant_id, "tenant.signup", event_data, status="pending",
        )
        db.commit()

        # Best-effort queue notification
        try:
            await dispatch_outbox_to_queue(outbox)
        except Exception as e:
            logger.warning(f"Failed to notify Service Bus: {e}")

        # ── Build subscription context for response ─────────────────
        plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.code == mandate.plan_code).first()
        features = []
        if plan:
            feature_rows = db.query(PlanFeature.feature_code).filter(PlanFeature.plan_code == plan.code).all()
            features = [f[0] for f in feature_rows]

        sub_ctx = SubscriptionContext(
            plan_code=mandate.plan_code,
            plan_name=plan.name if plan else mandate.plan_code,
            billing_cycle=mandate.billing_cycle,
            is_active=True,
            is_trial=True,
            trial_ends_at=trial_end.isoformat(),
            current_period_end=subscription.current_period_end.isoformat(),
            features=features,
        )

        logger.info(f"Mandate {mandate.mandate_id} activated -> tenant {tenant.tenant_id}")

        return MandateActivateResponse(
            tenant_id=str(tenant.tenant_id),
            mandate_id=str(mandate.mandate_id),
            status="active",
            subscription=sub_ctx,
        )
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Mandate activation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to activate mandate")