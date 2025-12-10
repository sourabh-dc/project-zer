# ==================================================================================
# AUTHENTICATION ENDPOINTS
# ==================================================================================
from datetime import datetime, timezone, timedelta
from typing import List
import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from Models import User, UserRole, Role, TenantSubscription, PlanCatalog, PlanPriceCatalog
from Schemas import RefreshJwtResponse, RefreshJwtRequest
from core.db_config import get_db
from core.config import SETTINGS
from core.helpers.auth_helper import issue_refresh_token, revoke_refresh_token
from core.user_auth import get_user_context
from utils.logger import logger
import bcrypt

router = APIRouter(prefix="/authentication", tags=["authentication"])

@router.post("/refresh-jwt", response_model=RefreshJwtResponse, status_code=200)
async def refresh_jwt(req: RefreshJwtRequest, db: Session = Depends(get_db)):
    """
    Exchange a valid refresh token for a new JWT.
    Requires: user_id and the refresh_token string returned at login.
    Rotates the refresh token on success when configured.
    """
    user = db.query(User).filter(User.user_id == req.user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    # Ensure the stored refresh token exists and is not expired
    if not getattr(user, "refresh_token", None) or not getattr(user, "refresh_token_expires_at", None):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No refresh token configured")

    if user.refresh_token_expires_at and user.refresh_token_expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token expired")

    # Verify refresh token
    try:
        valid = bcrypt.checkpw(req.refresh_token.encode("utf-8"), user.refresh_token.encode("utf-8"))
    except Exception:
        valid = False

    if not valid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    roles_query = db.query(Role.code) \
        .join(UserRole, Role.role_id == UserRole.role_id) \
        .filter(UserRole.user_id == user.user_id) \
        .all()

    # each row is a single-column tuple; extract codes and filter out falsy values
    roles: List[str] = [r[0] for r in roles_query if r and r[0]]

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
        "tenant_id": str(user.tenant_id) if user.tenant_id else None,
        "roles": roles,
        "exp": int(jwt_expires_at.timestamp())
    }
    token = jwt.encode(payload, jwt_secret, algorithm=jwt_algorithm)

    new_refresh_token = issue_refresh_token(user, db)

    logger.info(f"🔁 Refresh token used for user {user.email}, new JWT issued")
    return RefreshJwtResponse(
        token=token,
        expiring_at=jwt_expires_at.isoformat(),
        refresh_token=new_refresh_token,
        roles=roles
    )


@router.post("/logout", status_code=200)
async def logout(user_id: str, db: Session = Depends(get_db)):
    """
    Log out a user: set last_logout_at, revoke stored refresh token.
    """
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid user")
    # mark logout time
    user.last_logout_at = datetime.now(timezone.utc)

    # revoke the stored refresh token (this helper commits/refreshes the user)
    revoke_refresh_token(user, db)

    logger.info(f"🔓 User {user.email} logged out and refresh token revoked")
    return {"message": "Logged out successfully"}


@router.get("/whoami", status_code=200)
async def whoami(
    ctx = Depends(get_user_context),
    db: Session = Depends(get_db),
):
    """
    Return basic identity and subscription details for the authenticated user.
    """
    sub = db.query(TenantSubscription).filter(
        TenantSubscription.tenant_id == ctx.tenant_id,
        TenantSubscription.is_active.is_(True)
    ).first()

    subscription = None
    if sub:
        plan = db.query(PlanCatalog).filter(PlanCatalog.code == sub.plan_selected).first()
        price = db.query(PlanPriceCatalog).filter(PlanPriceCatalog.plan_code == sub.plan_selected).first()
        subscription = {
            "plan_code": sub.plan_selected,
            "plan_name": plan.name if plan else None,
            "status": sub.status,
            "is_trial": sub.is_trial,
            "current_period_start": sub.current_period_start.isoformat() if sub.current_period_start else None,
            "current_period_end": sub.current_period_end.isoformat() if sub.current_period_end else None,
            "trial_start": sub.trial_start.isoformat() if sub.trial_start else None,
            "trial_end": sub.trial_end.isoformat() if sub.trial_end else None,
            "billing_cycle": sub.billing_cycle,
            "currency": sub.currency,
            "price_minor": sub.price_minor,
            "catalog_price": {
                "monthly_minor": price.price_monthly_minor if price else None,
                "quarterly_minor": price.price_quarterly_minor if price else None,
                "yearly_minor": price.price_yearly_minor if price else None,
                "currency": price.currency if price else None,
            } if price else None,
        }

    return {
        "user_id": ctx.user_id,
        "tenant_id": ctx.tenant_id,
        "roles": ctx.roles,
        "subscription": subscription,
    }


@router.post("/reset-password", status_code=501)
async def reset_password_placeholder():
    """
    Placeholder endpoint for future password reset flow.
    """
    return {"message": "Password reset flow is not enabled yet."}
