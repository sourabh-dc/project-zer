# ==================================================================================
# AUTHENTICATION ENDPOINTS
# ==================================================================================
from datetime import datetime, timezone, timedelta
from typing import List
import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from Models import User, UserRole, Role
from Schemas import RefreshJwtResponse, RefreshJwtRequest, ResetPasswordRequest
from core.db_config import get_db
from core.config import SETTINGS
from core.helpers.auth_helper import issue_refresh_token, revoke_refresh_token
from utils.logger import logger
import bcrypt

app = APIRouter(prefix="authentication", tags=["authentication"])

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

@app.post("/v1/auth/reset-password", status_code=200)
async def reset_password(
    user_id: str,
    req: ResetPasswordRequest,
    db: Session = Depends(get_db)
):
    """
    Reset password for the currently authenticated user.
    Requires current password and a new password (min length validated by schema).
    """
    try:
        current_user = db.query(User).filter(User.user_id == user_id).first()
        # Verify current password
        if not bcrypt.checkpw(req.current_password.encode("utf-8"), current_user.password.encode("utf-8")):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Current password is incorrect")

        # Optional: prevent reuse of the same password
        if bcrypt.checkpw(req.new_password.encode("utf-8"), current_user.password.encode("utf-8")):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="New password must be different")

        # Hash and save new password
        hashed = bcrypt.hashpw(req.new_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        current_user.password = hashed
        db.commit()
        db.refresh(current_user)

        logger.info(f"🔒 Password changed for user {current_user.email}")
        return {"message": "Password updated successfully"}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Password reset failed: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error")
