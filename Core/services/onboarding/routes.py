import uuid
from datetime import datetime, timezone, timedelta
from typing import List
import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from Models import Tenant, TenantSubscription, SubscriptionPlan
from Schemas import TenantRequest
from core.helpers.auth_helper import issue_refresh_token
from utils.metrics import req_total, req_duration
from Models import User, UserRole, Role
from Schemas import LoginRequest, LoginResponse
from core.db_config import get_db
from core.config import SETTINGS
from utils.logger import logger
import bcrypt

router = APIRouter(prefix="/onboarding", tags=["onboarding tenant"])

@router.post("/tenant-signup", status_code=201)
async def create_tenant(
        req: TenantRequest,
        db: Session = Depends(get_db)
):
    """Create a new tenant"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_tenant", status="start").inc()

        normalized_email = req.email.lower()

        # Idempotency & uniqueness checks (case-insensitive)
        existing = db.query(Tenant).filter(func.lower(Tenant.email) == normalized_email).first()
        if existing:
            raise HTTPException(status_code=409, detail="Tenant email already exists")

        existing_user = db.query(User).filter(func.lower(User.email) == normalized_email).first()
        if existing_user:
            raise HTTPException(status_code=409, detail="User email already exists")

        password_hash = bcrypt.hashpw(req.password.encode("utf-8"), bcrypt.gensalt(12)).decode("utf-8")

        # Create tenant
        tenant = Tenant(
            tenant_id=uuid.uuid4(),
            name=req.name,
            tenant_type=req.type,
            registration_number=req.registration_number,
            email=normalized_email,
            phone=req.phone,
            active=True
        )
        db.add(tenant)
        db.flush()  # ensure tenant_id is available

        # create user
        display_name = f"{req.admin_first_name} {req.admin_last_name}".strip()
        user = User(
            user_id=uuid.uuid4(),
            tenant_id=tenant.tenant_id,
            display_name=display_name or tenant.name,
            first_name=req.admin_first_name,
            last_name=req.admin_last_name,
            email=normalized_email,
            password_hash=password_hash,
            active=True
        )
        db.add(user)
        db.flush()

        # create user role
        tenant_admin_role = db.query(Role.role_id).filter(Role.code == "tenant_admin").first()
        if not tenant_admin_role:
            raise HTTPException(status_code=500, detail="tenant_admin role not seeded")
        role = UserRole(id=uuid.uuid4(), user_id=user.user_id, role_id=tenant_admin_role[0])
        db.add(role)

        # single commit to avoid partial writes
        db.commit()

        db.refresh(tenant)

        req_total.labels(operation="create_tenant", status="success").inc()
        req_duration.labels(operation="create_tenant").observe(
            (datetime.now() - start).total_seconds()
        )

        logger.info(f"✅ Created tenant: {tenant.tenant_id} ({tenant.name})")

        return {
            "tenant_id": str(tenant.tenant_id),
            "name": tenant.name,
            "type": tenant.tenant_type,
            "created_at": tenant.created_at.isoformat()
        }
    except HTTPException:
        req_total.labels(operation="create_tenant", status="error").inc()
        raise
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_tenant", status="error").inc()
        logger.error(f"❌ Tenant creation failed: {e}")
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

        try:
            password_valid = bcrypt.checkpw(
                req.password.encode('utf-8'),
                (user.password_hash or "").encode('utf-8')
            )
        except Exception:
            password_valid = False

        if not password_valid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password"
            )

        # Check if the user is active
        if not user.active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is inactive"
            )

        user.last_login_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(user)
        # load roles from user_roles table
        roles_query = db.query(Role.code) \
            .join(UserRole, Role.role_id == UserRole.role_id) \
            .filter(UserRole.user_id == user.user_id) \
            .all()

        roles: List[str] = [r[0] for r in roles_query if r and r[0]]

        sub = db.query(TenantSubscription).filter(TenantSubscription.tenant_id == user.tenant_id).first()
        subscription = None
        if sub:
            plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.code == sub.plan_selected).first()
            subscription = {
                "plan_selected": sub.plan_selected,
                "plan_name": plan.name if plan else None,
                "status": sub.status,
                "billing_cycle": sub.billing_cycle,
                "current_period_start": sub.current_period_start.isoformat() if sub.current_period_start else None,
                "current_period_end": sub.current_period_end.isoformat() if sub.current_period_end else None,
                "trial_start": sub.trial_start.isoformat() if sub.trial_start else None,
                "trial_end": sub.trial_end.isoformat() if sub.trial_end else None,
                "is_trial": sub.is_trial,
                "is_active": sub.is_active,
            }

        # prepare JWT
        jwt_exp_minutes = getattr(SETTINGS, "JWT_EXPIRY_MINUTES", 60)
        jwt_algorithm = getattr(SETTINGS, "JWT_ALGORITHM", "HS256")
        jwt_secret = getattr(SETTINGS, "JWT_SECRET", "jwt_secret")
        if not jwt_secret:
            logger.error("JWT_SECRET not configured in SETTINGS")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Server configuration error")

        jwt_expires_at = datetime.now(timezone.utc) + timedelta(minutes=jwt_exp_minutes)
        payload = {
            "sub": str(user.user_id),
            "email": user.email,
            "tenant_id": str(user.tenant_id),
            "roles": roles,
            "exp": int(jwt_expires_at.timestamp())
        }
        token = jwt.encode(payload, jwt_secret, algorithm=jwt_algorithm)

        logger.info(f"✅ User {user.email} logged in successfully")

        # Return existing response plus jwt fields - ensure

        logger.info(f"✅ User {user.email} logged in successfully")

        refresh_token = issue_refresh_token(user, db)

        return LoginResponse(
            user_id=str(user.user_id),
            tenant_id=str(user.tenant_id),
            email=user.email,
            display_name=user.display_name,
            last_login_at=user.last_login_at.isoformat() if user.last_login_at else None,
            token=token,
            expiring_at=jwt_expires_at,
            refresh_token=refresh_token,
            roles=roles,
            subscription=subscription
        )

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Login failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )