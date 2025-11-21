# ==================================================================================
# AUTHENTICATION ENDPOINTS
# ==================================================================================
import uuid
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from Models import User
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
    
    This endpoint allows users to authenticate and retrieve their API key.
    The API key is stored in the database and returned to the user.
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
        
        # Check if account is locked
        if user.account_locked_until and user.account_locked_until > datetime.now(timezone.utc):
            remaining_minutes = int((user.account_locked_until - datetime.now(timezone.utc)).total_seconds() / 60)
            raise HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail=f"Account is locked. Try again in {remaining_minutes} minutes."
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
            # Increment failed login attempts
            user.failed_login_attempts += 1
            
            # Lock account if max attempts reached
            if user.failed_login_attempts >= SETTINGS.MAX_FAILED_LOGIN_ATTEMPTS:
                user.account_locked_until = datetime.now(timezone.utc) + timedelta(
                    minutes=SETTINGS.ACCOUNT_LOCKOUT_MINUTES
                )
                logger.warning(f"🔒 Account locked for user {user.email} due to failed login attempts")
            
            db.commit()
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
        user.account_locked_until = None
        user.last_login_at = datetime.now(timezone.utc)
        
        # Check if API key exists and is valid
        if not user.api_key or (user.api_key_expires_at and user.api_key_expires_at < datetime.now(timezone.utc)):
            # Regenerate API key if expired or missing
            user.api_key = generate_api_key()
            user.api_key_created_at = datetime.now(timezone.utc)
            user.api_key_expires_at = datetime.now(timezone.utc) + timedelta(
                days=SETTINGS.API_KEY_EXPIRY_DAYS
            )
            logger.info(f"🔄 Regenerated API key for user {user.email}")
        
        db.commit()
        db.refresh(user)
        
        logger.info(f"✅ User {user.email} logged in successfully")
        
        return LoginResponse(
            user_id=str(user.user_id),
            tenant_id=str(user.tenant_id),
            email=user.email,
            display_name=user.display_name,
            api_key=user.api_key,
            api_key_expires_at=user.api_key_expires_at.isoformat(),
            last_login_at=user.last_login_at.isoformat() if user.last_login_at else None
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

