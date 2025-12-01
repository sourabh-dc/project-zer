# ==================================================================================
# AUTHENTICATION ENDPOINTS
# ==================================================================================
import secrets
from datetime import datetime, timezone, timedelta
from typing import List
import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from Models import User, UserRole, Role
from Schemas import LoginRequest, LoginResponse, RefreshJwtResponse, RefreshJwtRequest
from core.db_config import get_db
from core.config import SETTINGS
from core.user_auth import check_user_authorization
from utils.logger import logger
import bcrypt

app = APIRouter()


def issue_refresh_token(user: User, db: Session, days: int = None) -> str:
    """Generate a plaintext refresh token, store its bcrypt hash and expiry on the user,
    commit and return plaintext."""
    refresh_days = days or getattr(SETTINGS, "REFRESH_TOKEN_DAYS", 30)
    plaintext = secrets.token_urlsafe(48)
    hashed = bcrypt.hashpw(plaintext.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    user.refresh_token = hashed
    user.refresh_token_expires_at = datetime.now(timezone.utc) + timedelta(days=refresh_days)
    db.commit()
    db.refresh(user)
    return plaintext

def revoke_refresh_token(user: User, db: Session) -> None:
    """Remove stored refresh token (logout / revoke)."""
    user.refresh_token_hash = None
    user.refresh_token_expires_at = None
    db.commit()
    db.refresh(user)

@app.post("/v1/auth/login", response_model=LoginResponse, status_code=200)
async def login(
    req: LoginRequest,
    db: Session = Depends(get_db)
):
    """
    Login with email and password to get API key
    This endpoint allows users to authenticate receive a jwt key.
    """
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

@app.post("/v1/auth/refresh-jwt", response_model=RefreshJwtResponse, status_code=200)
async def refresh_jwt(req: RefreshJwtRequest, db: Session = Depends(get_db)):
    """
    Exchange a valid refresh token for a new JWT.
    Requires: user_id and the refresh_token string returned at login.
    Rotates the refresh token on success when configured.
    """
    user = db.query(User).filter(User.user_id == req.user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    # Ensure stored refresh token exists and is not expired
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


@app.post("/v1/auth/logout", status_code=200)
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
    return {"message":"Logged out successfully"}

app.get("/test")
async def test_token(user_auth: bool=Depends(check_user_authorization(permission="test"))):
    return {"message": "Authorized"}