# ==================================================================================
# AUTHENTICATION ENDPOINTS
# ==================================================================================
from datetime import datetime, timezone, timedelta
from typing import List
import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from azure.communication.email import EmailClient
from urllib.parse import quote_plus

from provisioning_service.Models import (
    User, UserRole, Role, TenantSubscription, SubscriptionPlan, PlanPrice,
    TenantUserRole, TenantRole, TenantRolePermission, Permission, RolePermission,
    PlanFeature,
)
from provisioning_service.Schemas import (
    RefreshJwtResponse, RefreshJwtRequest, ResetPasswordRequest,
    ForgotPasswordRequest, PasswordResetConfirmRequest,
    LoginResponse, SubscriptionContext,
)
from provisioning_service.core.helpers.signin_context import (
    build_subscription_context, build_tenant_context,
    build_balance_context, build_rbac_context,
)
from provisioning_service.core.db_config import get_db
from provisioning_service.core.config import SETTINGS
from provisioning_service.core.helpers.auth_helper import issue_refresh_token, revoke_refresh_token
from provisioning_service.core.user_auth import check_user_authorization
from provisioning_service.core.azure_auth import validate_azure_token, is_azure_auth_configured
from provisioning_service.core.helpers.outbox_helpers import create_outbox_event
from provisioning_service.utils.logger import logger
import bcrypt
from sqlalchemy import func
from typing import List

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

    now = datetime.now(timezone.utc)
    jwt_expires_at = now + timedelta(minutes=jwt_exp_minutes)
    payload = {
        "sub": str(user.user_id),
        "email": user.email,
        "tenant_id": str(user.tenant_id) if user.tenant_id else None,
        "roles": roles,
        "iat": int(now.timestamp()),
        "exp": int(jwt_expires_at.timestamp()),
        "iss": getattr(SETTINGS, "JWT_ISSUER", "http://mock-idp"),
        "aud": getattr(SETTINGS, "JWT_AUDIENCE", "zeroque-api"),
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

    logger.info(f"User {user.email} logged out and refresh token revoked")

    # Outbox audit event
    try:
        create_outbox_event(db, user.tenant_id, "user.logged_out", {
            "user_id": str(user.user_id),
            "email": user.email,
        })
        db.commit()
    except Exception as _oe:
        logger.warning(f"Outbox failed for user.logged_out: {_oe}")

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
        if not current_user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        stored_hash = current_user.password_hash or current_user.password
        # Verify the current password
        if not bcrypt.checkpw(req.current_password.encode("utf-8"), stored_hash.encode("utf-8")):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Current password is incorrect")

        # Optional: prevent reuse of the same password
        if bcrypt.checkpw(req.new_password.encode("utf-8"), stored_hash.encode("utf-8")):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="New password must be different")

        # Hash and save a new password
        hashed = bcrypt.hashpw(req.new_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        if hasattr(current_user, 'password_hash'):
            current_user.password_hash = hashed
        else:
            current_user.password = hashed
        db.commit()
        db.refresh(current_user)

        logger.info(f"Password changed for user {current_user.email}")

        # Outbox audit event
        try:
            create_outbox_event(db, current_user.tenant_id, "user.password_reset", {
                "user_id": str(current_user.user_id),
                "email": current_user.email,
            })
            db.commit()
        except Exception as _oe:
            logger.warning(f"Outbox failed for user.password_reset: {_oe}")

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
        mail_from = "DoNotReply@32c276cf-0d14-43a7-8e89-2e45988729a8.azurecomm.net"
        subject = getattr(SETTINGS, "PASSWORD_RESET_SUBJECT", "Reset your password")
        body = (
            f"Hello,\n\n"
            f"You (or someone else) requested a password reset for your account. "
            f"Click the link below to reset your password. This link will expire in {expiry_minutes} minutes.\n\n"
            f"{reset_url}\n\n"
            f"If you did not request this, you can safely ignore this email.\n"
        )
        try:
            connection_string = SETTINGS.EMAIL_CONNECTION_STRING
            client = EmailClient.from_connection_string(connection_string)

            message = {
                "senderAddress": mail_from,
                "recipients": {
                    "to": [{"address": req.email}]
                },
                "content": {
                    "subject": subject,
                    "plainText": body,
                    "html": f"""
                    <html>
                        <body>
                            <p>Hello,</p>
                            <p>You (or someone else) requested a password reset for your account. 
                            Click the link below to reset your password. This link will expire in {expiry_minutes} minutes.</p>
                            <p><a href="{reset_url}">{reset_url}</a></p>
                            <p>If you did not request this, you can safely ignore this email.</p>
                        </body>
                    </html>
                    """
                },

            }

            poller = client.begin_send(message)
            result = poller.result()
            print("Message sent: ", result)

            # Outbox audit event
            try:
                create_outbox_event(db, user.tenant_id, "user.forgot_password_requested", {
                    "user_id": str(user.user_id),
                    "email": req.email,
                })
                db.commit()
            except Exception as _oe:
                logger.warning(f"Outbox failed for user.forgot_password_requested: {_oe}")

            return result

        except Exception as ex:
            print(ex)

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

        # Outbox audit event
        try:
            create_outbox_event(db, user.tenant_id, "user.password_reset_confirmed", {
                "user_id": str(user.user_id),
                "email": user.email,
            })
            db.commit()
        except Exception as _oe:
            logger.warning(f"Outbox failed for user.password_reset_confirmed: {_oe}")

        logger.info(f"Password reset completed for user {user.email}")
        return {"message": "Password updated successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Password reset confirmation failed: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error")

@router.get("/whoami", status_code=200)
async def whoami(
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("subscriptions.tenant.view")),
):
    """
    Return full status check for the authenticated user: subscription,
    limits, balance, tenant info, and RBAC context.
    """
    import uuid as _uuid
    tenant_id = _uuid.UUID(ctx["tenant_id"]) if isinstance(ctx, dict) else ctx.tenant_id
    user_id = _uuid.UUID(ctx["user_id"]) if isinstance(ctx, dict) else ctx.user_id

    sub_ctx = build_subscription_context(db, tenant_id)
    tenant_ctx = build_tenant_context(db, tenant_id)
    balance_ctx = build_balance_context(db, user_id, tenant_id)

    # Pull roles/permissions from JWT claims
    roles = ctx.get("roles", []) if isinstance(ctx, dict) else []
    permissions = ctx.get("permissions", []) if isinstance(ctx, dict) else []
    rbac_ctx = build_rbac_context(
        roles=roles,
        permissions=permissions,
        feature_codes=sub_ctx.features if sub_ctx else [],
    )

    # Also include pricing info for the plan
    price = None
    if sub_ctx and sub_ctx.plan_code:
        price_row = db.query(PlanPrice).filter(PlanPrice.plan_code == sub_ctx.plan_code).first()
        if price_row:
            price = {
                "monthly_minor": price_row.price_monthly_minor,
                "quarterly_minor": price_row.price_quarterly_minor,
                "yearly_minor": price_row.price_yearly_minor,
                "currency": price_row.currency,
            }

    return {
        "user_id": str(user_id),
        "tenant_id": str(tenant_id),
        "subscription": sub_ctx.model_dump() if sub_ctx else None,
        "tenant": tenant_ctx.model_dump() if tenant_ctx else None,
        "balance": balance_ctx.model_dump() if balance_ctx else None,
        "rbac": rbac_ctx.model_dump() if rbac_ctx else None,
        "catalog_price": price,
    }

@router.post("/azure/token-exchange", response_model=LoginResponse, status_code=200)
async def azure_token_exchange(
    db: Session = Depends(get_db),
    azure_token: str = None,
):
    """
    Exchange an Azure AD B2C / Entra ID token for an internal JWT.

    Flow:
      1. Frontend authenticates user via Azure AD B2C (MSAL.js redirect/popup).
      2. Frontend sends the Azure access/id token to this endpoint.
      3. Backend validates the Azure token against Azure's JWKS.
      4. Backend maps the Azure identity to an internal User record.
      5. Backend issues an internal JWT with tenant_id, roles, and permissions.

    If the Azure user doesn't have an internal account yet, returns 404 so the
    frontend can redirect to the onboarding/mandate flow.
    """
    if not is_azure_auth_configured():
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Azure AD authentication is not configured",
        )

    if not azure_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="azure_token is required",
        )

    # Validate the Azure-issued token
    azure_claims = await validate_azure_token(azure_token)

    # Map Azure identity to internal user by email
    email = azure_claims.email
    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Azure token does not contain an email claim",
        )

    user = db.query(User).filter(func.lower(User.email) == email.lower()).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No internal account found for this Azure identity. Complete onboarding first.",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive",
        )

    # Enable SSO flag if not already set
    if not user.is_sso_enabled:
        user.is_sso_enabled = True

    user.last_login_at = datetime.now(timezone.utc)
    user.failed_login_attempts = 0
    db.commit()
    db.refresh(user)

    # Resolve roles (global + tenant)
    roles_query = db.query(Role.code) \
        .join(UserRole, Role.role_id == UserRole.role_id) \
        .filter(UserRole.user_id == user.user_id).all()
    tenant_roles_query = db.query(TenantRole.code) \
        .join(TenantUserRole, TenantRole.role_id == TenantUserRole.tenant_role_id) \
        .filter(TenantUserRole.user_id == user.user_id).all()

    roles: List[str] = [r[0] for r in roles_query if r and r[0]]
    tenant_roles: List[str] = [r[0] for r in tenant_roles_query if r and r[0]]
    all_roles = roles + tenant_roles

    # Resolve permissions
    role_perms = db.query(Permission.code).join(
        RolePermission, RolePermission.permission_code == Permission.code
    ).filter(RolePermission.role_code.in_(roles)).all()
    tenant_role_perms = db.query(Permission.code).join(
        TenantRolePermission, TenantRolePermission.permission_code == Permission.code
    ).join(TenantRole, TenantRolePermission.tenant_role_id == TenantRole.role_id) \
        .join(TenantUserRole, TenantUserRole.tenant_role_id == TenantRole.role_id) \
        .filter(TenantUserRole.user_id == user.user_id).all()

    perm_list = list({p[0] for p in role_perms + tenant_role_perms})
    if "tenant_admin" in roles:
        perm_list = ["*"]

    # Issue internal JWT
    jwt_exp_minutes = getattr(SETTINGS, "JWT_EXPIRY_MINUTES", 60)
    jwt_algorithm = getattr(SETTINGS, "JWT_ALGORITHM", "HS256")
    jwt_secret = getattr(SETTINGS, "JWT_SECRET", None)
    if not jwt_secret:
        raise HTTPException(status_code=500, detail="Server configuration error")

    now = datetime.now(timezone.utc)
    jwt_expires_at = now + timedelta(minutes=jwt_exp_minutes)

    payload = {
        "sub": str(user.user_id),
        "email": user.email,
        "tenant_id": str(user.tenant_id),
        "roles": all_roles,
        "permissions": perm_list,
        "auth_method": "azure_ad",
        "azure_oid": azure_claims.oid,
        "iat": int(now.timestamp()),
        "exp": int(jwt_expires_at.timestamp()),
        "iss": getattr(SETTINGS, "JWT_ISSUER", "http://mock-idp"),
        "aud": getattr(SETTINGS, "JWT_AUDIENCE", "zeroque-api"),
    }
    token = jwt.encode(payload, jwt_secret, algorithm=jwt_algorithm)
    refresh_token = issue_refresh_token(user, db)

    # Build full status-check context
    sub_ctx = build_subscription_context(db, user.tenant_id)
    tenant_ctx = build_tenant_context(db, user.tenant_id)
    balance_ctx = build_balance_context(db, user.user_id, user.tenant_id)
    rbac_ctx = build_rbac_context(
        roles=all_roles,
        permissions=perm_list,
        feature_codes=sub_ctx.features if sub_ctx else [],
    )

    logger.info(f"Azure SSO login for {user.email} (tenant {user.tenant_id})")

    # Outbox audit event
    try:
        create_outbox_event(db, user.tenant_id, "user.azure_sso_login", {
            "user_id": str(user.user_id),
            "email": user.email,
            "azure_oid": azure_claims.oid,
        })
        db.commit()
    except Exception as _oe:
        logger.warning(f"Outbox failed for user.azure_sso_login: {_oe}")

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


@router.get("/healthcheck")
async def auth_test(user=Depends(check_user_authorization('tenant.admin'))):
    return user