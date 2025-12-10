# ==================================================================================
# AUTHENTICATION ENDPOINTS
# ==================================================================================
from datetime import datetime, timezone, timedelta
from typing import List
import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
import smtplib
from email.message import EmailMessage
from urllib.parse import quote_plus

from Models import User, UserRole, Role
from Schemas import RefreshJwtResponse, RefreshJwtRequest, ResetPasswordRequest, ForgotPasswordRequest, \
    PasswordResetConfirmRequest
from core.db_config import get_db
from core.config import SETTINGS
from core.helpers.auth_helper import issue_refresh_token, revoke_refresh_token
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
    return {"message":"Logged out successfully"}

@router.post("/reset-password", status_code=200)
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
        # Verify the current password
        if not bcrypt.checkpw(req.current_password.encode("utf-8"), current_user.password.encode("utf-8")):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Current password is incorrect")

        # Optional: prevent reuse of the same password
        if bcrypt.checkpw(req.new_password.encode("utf-8"), current_user.password.encode("utf-8")):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="New password must be different")

        # Hash and save a new password
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


@router.post("/forgot-password", status_code=200)
async def forgot_password(req: ForgotPasswordRequest, db: Session = Depends(get_db)):
    """
    Request a password reset. If the email exists, send a signed reset URL by email.
    Response is the same whether or not the account exists.
    """
    try:
        user = db.query(User).filter(User.email == req.email).first()

        # Always return same message so we don't reveal whether the email exists
        response = {"message": "If an account with that email exists, a password reset link has been sent."}

        if not user:
            logger.info(f"Password reset requested for unknown email: {req.email}")
            return response

        # Build JWT reset token
        jwt_secret = getattr(SETTINGS, "JWT_SECRET", None)
        if not jwt_secret:
            logger.error("JWT_SECRET not configured in SETTINGS")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Server configuration error")

        expiry_minutes = getattr(SETTINGS, "PASSWORD_RESET_EXPIRY_MINUTES", 60)
        jwt_algorithm = getattr(SETTINGS, "JWT_ALGORITHM", "HS256")
        exp_at = datetime.now(timezone.utc) + timedelta(minutes=expiry_minutes)
        payload = {
            "sub": str(user.user_id),
            "action": "password_reset",
            "exp": int(exp_at.timestamp())
        }
        token = jwt.encode(payload, jwt_secret, algorithm=jwt_algorithm)

        # Build reset URL (frontend URL should be configured)
        frontend_base = getattr(SETTINGS, "FRONTEND_URL", None) or getattr(SETTINGS, "BASE_URL", "http://localhost:3000")
        reset_path = getattr(SETTINGS, "PASSWORD_RESET_PATH", "/reset-password")
        reset_url = f"{frontend_base.rstrip('/')}{reset_path}?token={quote_plus(token)}"

        # Compose email
        mail_from = getattr(SETTINGS, "MAIL_FROM", "no-reply@example.com")
        subject = getattr(SETTINGS, "PASSWORD_RESET_SUBJECT", "Reset your password")
        body = (
            f"Hello,\n\n"
            f"You (or someone else) requested a password reset for your account. "
            f"Click the link below to reset your password. This link will expire in {expiry_minutes} minutes.\n\n"
            f"{reset_url}\n\n"
            f"If you did not request this, you can safely ignore this email.\n"
        )

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = mail_from
        msg["To"] = user.email
        msg.set_content(body)

        # Send email using SMTP settings in SETTINGS
        smtp_host = getattr(SETTINGS, "SMTP_HOST", None)
        smtp_port = getattr(SETTINGS, "SMTP_PORT", None)
        smtp_user = getattr(SETTINGS, "SMTP_USERNAME", None)
        smtp_pass = getattr(SETTINGS, "SMTP_PASSWORD", None)
        use_ssl = getattr(SETTINGS, "SMTP_USE_SSL", False)
        use_tls = getattr(SETTINGS, "SMTP_USE_TLS", True)

        if not smtp_host or not smtp_port:
            logger.error("SMTP not configured properly in SETTINGS")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Mail server not configured")

        try:
            if use_ssl:
                server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=10)
            else:
                server = smtplib.SMTP(smtp_host, smtp_port, timeout=10)
            server.ehlo()
            if use_tls and not use_ssl:
                server.starttls()
                server.ehlo()
            if smtp_user and smtp_pass:
                server.login(smtp_user, smtp_pass)
            server.send_message(msg)
            server.quit()
            logger.info(f"Password reset email sent to {user.email}")
        except Exception as e:
            logger.error(f"Failed to send password reset email to {user.email}: {e}", exc_info=True)
            # Do not expose email errors to caller; return a generic message
            return response

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Forgot password flow failed: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error")


@router.post("/reset-password/confirm", status_code=200)
async def confirm_reset_password(req: PasswordResetConfirmRequest, db: Session = Depends(get_db)):
    """
    Verify a password-reset JWT token and set a new password for the user.
    """
    try:
        jwt_secret = getattr(SETTINGS, "JWT_SECRET", None)
        if not jwt_secret:
            logger.error("JWT_SECRET not configured in SETTINGS")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Server configuration error")

        jwt_algorithm = getattr(SETTINGS, "JWT_ALGORITHM", "HS256")

        try:
            payload = jwt.decode(req.token, jwt_secret, algorithms=[jwt_algorithm])
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Reset token expired")
        except jwt.InvalidTokenError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid reset token")

        if payload.get("action") != "password_reset" or not payload.get("sub"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid reset token")

        user_id = payload.get("sub")
        user = db.query(User).filter(User.user_id == user_id).first()
        if not user:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid reset token")

        hashed = bcrypt.hashpw(req.new_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        user.password = hashed
        db.commit()
        db.refresh(user)

        try:
            revoke_refresh_token(user, db)
        except Exception:
            logger.error("Failed to revoke refresh token after password reset", exc_info=True)

        logger.info(f"🔒 Password reset completed for user {user.email}")
        return {"message": "Password updated successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Password reset confirmation failed: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error")
