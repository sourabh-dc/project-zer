import uuid
import stripe
from datetime import datetime, timezone, timedelta
from typing import List
import jwt
from azure.communication.email import EmailClient
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from provisioning_service.Models import (
    Tenant, User, UserRole, Role, Permission, RolePermission,
    TenantUserRole, TenantRole, TenantRolePermission,
    Mandate, TenantSubscription, SubscriptionPlan, PlanFeature, PlanPrice,
)
from provisioning_service.Schemas import (
    TenantRequest, LoginRequest, LoginResponse,
    MandateCreateRequest, MandateResponse,
    MandateActivateRequest, MandateActivateResponse,
    SubscriptionContext,
)
from provisioning_service.core.helpers.signin_context import (
    build_subscription_context, build_tenant_context,
    build_balance_context, build_rbac_context,
)
from provisioning_service.core.helpers.auth_helper import issue_refresh_token
from provisioning_service.core.helpers.outbox_helpers import create_outbox_event, dispatch_outbox_to_queue
from provisioning_service.utils.metrics import req_total
from provisioning_service.core.db_config import get_db
from provisioning_service.core.config import SETTINGS
from provisioning_service.utils.logger import logger
import bcrypt

stripe.api_key = SETTINGS.STRIPE_SECRET_KEY

router = APIRouter(prefix="/onboarding", tags=["onboarding tenant"])

# python
from fastapi import BackgroundTasks
from pydantic import BaseModel, EmailStr
import secrets
import hmac
import hashlib
from typing import Dict


# OTP configuration (tunable via SETTINGS)
OTP_EXPIRY_MINUTES = getattr(SETTINGS, "OTP_EXPIRY_MINUTES", 5)
OTP_MAX_ATTEMPTS = getattr(SETTINGS, "OTP_MAX_ATTEMPTS", 3)
OTP_SECRET = getattr(SETTINGS, "OTP_SECRET", getattr(SETTINGS, "JWT_SECRET", "otp_fallback_secret"))

# In-memory store: { email: { "hash": ..., "expires_at": datetime, "attempts_left": int } }
OTP_STORE: Dict[str, Dict] = {}

class OtpGenerateRequest(BaseModel):
    email: EmailStr

class OtpGenerateResponse(BaseModel):
    detail: str

class OtpValidateRequest(BaseModel):
    email: EmailStr
    otp: str

class OtpValidateResponse(BaseModel):
    detail: str

def _hash_otp(otp: str) -> str:
    return hmac.new(OTP_SECRET.encode("utf-8"), otp.encode("utf-8"), hashlib.sha256).hexdigest()

def _send_email_smtp(to_email: str, otp, expiry_minutes, support_contact):
    # Simple SMTP sender using SETTINGS if configured; logs on error or if not configured.
    try:
        mail_from = "DoNotReply@32c276cf-0d14-43a7-8e89-2e45988729a8.azurecomm.net"
        subject = "Zeroque - One time password"
        body = (
        f"Dear Customer,\n\n"
        f"Thank you for your interest. Please find your One Time Password (OTP) below:\n\n"
        f"OTP: {otp}\n\n"
        f"This OTP will expire in {expiry_minutes} minutes and is valid for a single use only. "
        f"For your security, do not share this code with anyone.\n\n"
        f"If you did not request this OTP or believe your account may be compromised, please contact "
        f"our support team at {support_contact} immediately.\n\n"
        f"Kind regards,\n"
        f"The Support Team\n"
    )
        try:
            connection_string = SETTINGS.EMAIL_CONNECTION_STRING
            client = EmailClient.from_connection_string(connection_string)

            message = {
                "senderAddress": mail_from,
                "recipients": {
                    "to": [{"address": to_email}]
                },
                "content": {
                    "subject": subject,
                    "plainText": body,
                    "html": f"""<html>
                  <body style="font-family: Arial, Helvetica, sans-serif; color: #222; line-height:1.5;">
                    <p>Dear Customer,</p>
                    <p>Thank you for your interest. Please find your One-Time Password (OTP) below:</p>
                    <div style="margin:16px 0; padding:12px 16px; display:inline-block; background:#f6f8fa; border-radius:6px; font-size:1.25rem; font-weight:600; letter-spacing:2px;">
                      {otp}
                    </div>
                    <p>This OTP will expire in {expiry_minutes} minutes and is valid for a single use only. For your security, do not share this code with anyone.</p>
                    <p>If you did not request this OTP or believe your account may be compromised, please contact our support team at <a href="mailto:{support_contact}">{support_contact}</a> immediately.</p>
                    <p>Kind regards,<br/>The Support Team</p>
                  </body>
                </html>"""
                },

            }

            poller = client.begin_send(message)
            result = poller.result()
            print("Message sent: ", result)
            return result

        except Exception as ex:
            print(ex)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Otp generation failed: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error")

@router.post("/otp/generate", response_model=OtpGenerateResponse, status_code=202)
async def generate_otp(
    req: OtpGenerateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Generate an OTP for the provided email, send it by email, and store a hashed copy with expiry.
    """
    try:
        # Optional: ensure user exists (else still generate? here we require user)
        user = db.query(User).filter(func.lower(User.email) == req.email.lower()).first()
        if user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="A Tenant Already Exists with this Email ID")

        # generate 6-digit OTP
        otp = f"{secrets.randbelow(10**6):06d}"
        hashed = _hash_otp(otp)
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=OTP_EXPIRY_MINUTES)

        # store hashed otp
        OTP_STORE[req.email.lower()] = {
            "hash": hashed,
            "expires_at": expires_at,
            "attempts_left": OTP_MAX_ATTEMPTS
        }

        # send email in background
        background_tasks.add_task(_send_email_smtp, req.email, otp, OTP_EXPIRY_MINUTES, "zeroque.support@consumables.com")

        return OtpGenerateResponse(detail="OTP generated and being sent if email configured")
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Failed to generate OTP for {req.email}: {exc}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to generate OTP")

@router.post("/otp/validate", response_model=OtpValidateResponse, status_code=200)
async def validate_otp(
    req: OtpValidateRequest,
):
    """
    Validate provided OTP for email. On success, removes stored OTP.
    """
    try:
        key = req.email.lower()
        entry = OTP_STORE.get(key)
        if not entry:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No OTP requested for this email")

        # check expiry
        if datetime.now(timezone.utc) > entry["expires_at"]:
            OTP_STORE.pop(key, None)
            raise HTTPException(status_code=status.HTTP_410_GONE, detail="OTP expired")

        # check attempts
        if entry["attempts_left"] <= 0:
            OTP_STORE.pop(key, None)
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Too many invalid attempts")

        # verify OTP
        provided_hash = _hash_otp(req.otp)
        if hmac.compare_digest(provided_hash, entry["hash"]):
            # success: remove stored otp and return success
            OTP_STORE.pop(key, None)
            return OtpValidateResponse(detail="OTP validated successfully")
        else:
            # decrement attempts
            entry["attempts_left"] -= 1
            if entry["attempts_left"] <= 0:
                OTP_STORE.pop(key, None)
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Too many invalid attempts")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid OTP")
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"OTP validation error for {req.email}: {exc}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="OTP validation failed")


# =====================================================================
# MANDATE-FIRST ONBOARDING (New Flow)
# =====================================================================

@router.post("/mandate", response_model=MandateResponse, status_code=201)
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
        # Reject if email already used
        existing = db.query(Mandate).filter(
            Mandate.email == req.email, Mandate.status.in_(["pending", "active"])
        ).first()
        if existing:
            raise HTTPException(status_code=409, detail="A mandate already exists for this email")

        existing_tenant = db.query(Tenant).filter(Tenant.email == req.email).first()
        if existing_tenant:
            raise HTTPException(status_code=409, detail="Tenant email already registered")

        # Hash password now — stored on mandate, transferred to user on activation
        pw_hash = bcrypt.hashpw(req.password.encode("utf-8"), bcrypt.gensalt(12)).decode("utf-8")

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
            password_hash=pw_hash,
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
            "password_hash": mandate.password_hash,
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


# =====================================================================
# LEGACY SIGNUP (kept for backwards compatibility)
# =====================================================================

@router.post("/tenant-signup", status_code=201)
async def create_tenant(
        req: TenantRequest,
        db: Session = Depends(get_db)
):
    """Create a new tenant (legacy — prefer /onboarding/mandate + /onboarding/activate)"""
    try:
        # Check if tenant exists
        existing = db.query(Tenant).filter(Tenant.email == req.email).first()
        if existing:
            raise HTTPException(status_code=409, detail="Tenant email already exists")

        tenant = Tenant(
            tenant_id=uuid.uuid4(),
            tenant_name=getattr(req, "tenant_name", getattr(req, "name", None)),
            tenant_type=req.type,
            registration_number=req.registration_number,
            email=req.email,
            billing_email=getattr(req, "billing_email", None),
            billing_address=getattr(req, "billing_address", None),
            primary_domain=getattr(req, "primary_domain", None),
            phone=req.phone,
            default_currency=getattr(req, "default_currency", None),
            timezone=getattr(req, "timezone", None),
            locale=getattr(req, "locale", "en_GB"),
            owner_user_id=getattr(req, "owner_user_id", None),
            industry=getattr(req, "industry", None),
            tech_contact_email=getattr(req, "tech_contact_email", None),
            support_contact_email=getattr(req, "support_contact_email", None),
            # store raw logo bytes (schema/DB must have a matching binary column)
            logo=getattr(req, "logo", None),
            active=True if getattr(req, "active", None) is None else req.active,
        )

        db.add(tenant)
        db.commit()
        db.refresh(tenant)

        # Create outbox event record so worker can process and update status
        event_data = req.dict()
        event_data["tenant_id"] = str(tenant.tenant_id)

        outbox = create_outbox_event(db, tenant.tenant_id, "tenant.signup", event_data, status="pending")
        db.commit()

        try:
            from provisioning_service.core.sb_client import messaging_service
            await messaging_service.send_outbox_message(str(outbox.id))
        except Exception as e:
            # The outbox worker will pick this up later if the notify fails.
            logger.warning(f"Failed to notify Service Bus: {e}")

        return {"tenant_id": str(tenant.tenant_id), "status": "Signup initiated"}
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_tenant", status="error").inc()
        logger.error(f"Tenant creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/tenant-signin", response_model=LoginResponse, status_code=200)
async def tenant_login(
        req: LoginRequest,
        db: Session = Depends(get_db)
):
    """
    Login with email and password to get API key
    This endpoint allows users to authenticate receive a jwt key.
    """
    try:
        # Find the user by email
        user = db.query(User).filter(
            func.lower(User.email) == req.email.lower()
        ).first()

        if not user:
            # Don't reveal if email exists (security best practice)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password"
            )

        password_valid = bcrypt.checkpw(
            req.password.encode('utf-8'),
            user.password_hash.encode('utf-8')
        )

        if not password_valid:
            # Increment failed login attempts
            user.failed_login_attempts += 1

            # Lock account if max attempts reached
            if user.failed_login_attempts >= SETTINGS.MAX_FAILED_LOGIN_ATTEMPTS:
                logger.warning(f"Account locked for user {user.email} due to failed login attempts")
                return "Account locked due to too many failed login attempts. Please try Forget Password."
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password"
            )

        # Check if the user is active
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is inactive"
            )

        # Reset failed login attempts on successful login
        user.failed_login_attempts = 0
        user.last_login_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(user)
        # load roles from user_roles table (global) and tenant roles
        roles_query = db.query(Role.code) \
            .join(UserRole, Role.role_id == UserRole.role_id) \
            .filter(UserRole.user_id == user.user_id) \
            .all()
        tenant_roles_query = db.query(TenantRole.code) \
            .join(TenantUserRole, TenantRole.role_id == TenantUserRole.tenant_role_id) \
            .filter(TenantUserRole.user_id == user.user_id) \
            .all()

        # each row is a single-column tuple; extract codes and filter out falsy values
        roles: List[str] = [r[0] for r in roles_query if r and r[0]]
        tenant_roles: List[str] = [r[0] for r in tenant_roles_query if r and r[0]]
        all_roles: List[str] = roles + tenant_roles

        # prepare JWT
        jwt_exp_minutes = getattr(SETTINGS, "JWT_EXPIRY_MINUTES", 60)
        jwt_algorithm = getattr(SETTINGS, "JWT_ALGORITHM", "HS256")
        jwt_secret = getattr(SETTINGS, "JWT_SECRET", "jwt_secret")
        if not jwt_secret:
            logger.error("JWT_SECRET not configured in SETTINGS")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Server configuration error")

        jwt_expires_at = datetime.now(timezone.utc) + timedelta(minutes=jwt_exp_minutes)
        now = datetime.now(timezone.utc)
        # Resolve permissions from roles; tenant_admin gets wildcard
        role_perms = db.query(Permission.code).join(
            RolePermission, RolePermission.permission_code == Permission.code
        ).filter(RolePermission.role_code.in_(roles)).all()
        tenant_role_perms = db.query(Permission.code).join(
            TenantRolePermission, TenantRolePermission.permission_code == Permission.code
        ).join(
            TenantRole, TenantRolePermission.tenant_role_id == TenantRole.role_id
        ).join(
            TenantUserRole, TenantUserRole.tenant_role_id == TenantRole.role_id
        ).filter(TenantUserRole.user_id == user.user_id).all()

        perm_list = list({p[0] for p in role_perms + tenant_role_perms})
        if "tenant_admin" in roles:
            perm_list = ["*"]
        elif not perm_list:
            perm_list = []
        payload = {
            "sub": str(user.user_id),
            "email": user.email,
            "tenant_id": str(user.tenant_id),
            "roles": all_roles,
            "permissions": perm_list,
            "iat": int(now.timestamp()),
            "exp": int(jwt_expires_at.timestamp()),
            "iss": getattr(SETTINGS, "JWT_ISSUER", "http://mock-idp"),
            "aud": getattr(SETTINGS, "JWT_AUDIENCE", "zeroque-api"),
        }
        token = jwt.encode(payload, jwt_secret, algorithm=jwt_algorithm)

        logger.info(f"User {user.email} logged in successfully")

        refresh_token = issue_refresh_token(user, db)

        # ── Build full status-check context for sign-in response ─────────
        sub_ctx = build_subscription_context(db, user.tenant_id)
        tenant_ctx = build_tenant_context(db, user.tenant_id)
        balance_ctx = build_balance_context(db, user.user_id, user.tenant_id)
        rbac_ctx = build_rbac_context(
            roles=all_roles,
            permissions=perm_list,
            feature_codes=sub_ctx.features if sub_ctx else [],
        )

        return LoginResponse(
            user_id=str(user.user_id),
            tenant_id=str(user.tenant_id),
            email=user.email,
            display_name=user.display_name,
            first_name=user.first_name,
            last_name=user.last_name,
            last_login_at=user.last_login_at.isoformat() if user.last_login_at else None,
            token=token,
            expiring_at=jwt_expires_at,
            refresh_token=refresh_token,
            subscription=sub_ctx,
            tenant=tenant_ctx,
            balance=balance_ctx,
            rbac=rbac_ctx,
        )

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Login failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )