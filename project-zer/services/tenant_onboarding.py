import uuid
from datetime import datetime, timezone, timedelta
from typing import List
import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from Models import Tenant, TenantSubscription
from core.helpers.auth_helper import issue_refresh_token
from utils.metrics import req_total, req_duration
from Models import User, UserRole, Role
from Schemas import LoginRequest, LoginResponse
from core.db_config import get_db
from core.config import SETTINGS
from utils.logger import logger
import bcrypt

router = APIRouter(prefix="/onboarding", tags=["onboarding tenant"])

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
            user.password.encode('utf-8')
        )

        if not password_valid:
            # Increment failed login attempts
            user.failed_login_attempts += 1

            # Lock account if max attempts reached
            if user.failed_login_attempts >= SETTINGS.MAX_FAILED_LOGIN_ATTEMPTS:
                logger.warning(f"🔒 Account locked for user {user.email} due to failed login attempts")
                return "Account locked due to too many failed login attempts. Please try Forget Password."
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

        # Reset failed login attempts on successful login
        user.failed_login_attempts = 0
        user.last_login_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(user)
        # load roles from user_roles table
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
            refresh_token=refresh_token
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