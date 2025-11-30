# ==================================================================================
# AUTHENTICATION ENDPOINTS
# ==================================================================================
import uuid
from datetime import datetime, timezone, timedelta
from typing import List

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from Models import User, UserRole
from Schemas import LoginRequest, LoginResponse, RefreshApiKeyRequest, RefreshApiKeyResponse
from core.db_config import get_db
from core.config import SETTINGS
from core.user_auth import generate_api_key
from utils.logger import logger
import bcrypt

app = APIRouter()

@app.post("/v1/auth/login", response_model=LoginResponse, status_code=200)
async def login(
    req: LoginRequest,
    db: Session = Depends(get_db)
):
    """
    Login with email and password to get API key
    This endpoint allows users to authenticate receive a jwt key.
    """
    start = datetime.now()
    try:
        # Find user by email
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
        
        # Check if user is active
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
        roles_query = db.query(UserRole).filter(UserRole.user_id == user.user_id).all()
        roles: List[str] = [getattr(r, "role", None) or getattr(r, "role_name", None) for r in roles_query]
        roles = [r for r in roles if r]  # filter out None

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
        
        return LoginResponse(
            user_id=str(user.user_id),
            tenant_id=str(user.tenant_id),
            email=user.email,
            display_name=user.display_name,
            last_login_at=user.last_login_at.isoformat() if user.last_login_at else None,
            token=token,
            expiring_at=jwt_expires_at
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


@app.post("/v1/auth/refresh-api-key", response_model=RefreshApiKeyResponse, status_code=200)
async def refresh_api_key(
    req: RefreshApiKeyRequest,
    db: Session = Depends(get_db)
):
    """
    Refresh API key (invalidates old one)
    
    This endpoint allows users to regenerate their API key.
    The old API key will be invalidated immediately.
    """
    try:
        # Find user by email
        user = db.query(User).filter(
            func.lower(User.email) == req.email.lower()
        ).first()
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password"
            )
        
        # Verify password
        if not user.password_hash:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password"
            )
        
        password_valid = bcrypt.checkpw(
            req.password.encode('utf-8'),
            user.password_hash.encode('utf-8')
        )
        
        if not password_valid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password"
            )
        
        # Check if user is active
        if not user.active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is inactive"
            )
        
        # Generate new API key (invalidates old one)
        old_api_key = user.api_key
        user.api_key = generate_api_key()
        user.api_key_created_at = datetime.now(timezone.utc)
        user.api_key_expires_at = datetime.now(timezone.utc) + timedelta(
            days=SETTINGS.API_KEY_EXPIRY_DAYS
        )
        
        db.commit()
        db.refresh(user)
        
        logger.info(f"🔄 API key refreshed for user {user.email} (old key invalidated)")
        
        return RefreshApiKeyResponse(
            api_key=user.api_key,
            api_key_expires_at=user.api_key_expires_at.isoformat(),
            message="API key refreshed successfully. Old API key is now invalid."
        )
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ API key refresh failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )

