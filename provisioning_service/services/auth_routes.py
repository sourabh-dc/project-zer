# ==================================================================================
# AUTHENTICATION ENDPOINTS
# ==================================================================================
from datetime import datetime, timezone, timedelta
from typing import List, Optional
import uuid as _uuid

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from provisioning_service.Models import (
    User, UserIdentity, Invitation, UserRole, Role, TenantSubscription, SubscriptionPlan, PlanPrice,
    TenantUserRole, TenantRole, TenantRolePermission, Permission, RolePermission,
    PlanFeature,
)
from provisioning_service.Schemas import (
    RefreshJwtResponse, RefreshJwtRequest,
    LoginResponse, SubscriptionContext, TokenExchangeRequest,
)
from provisioning_service.core.helpers.signin_context import (
    build_subscription_context, build_tenant_context,
    build_balance_context, build_rbac_context,
)
from provisioning_service.core.db_config import get_db
from provisioning_service.core.config import SETTINGS
from provisioning_service.core.helpers.auth_helper import issue_refresh_token, revoke_refresh_token
from provisioning_service.core.user_auth import check_user_authorization, decode_jwt_with_settings
from provisioning_service.core.azure_auth import validate_azure_token, is_azure_auth_configured
from provisioning_service.core.helpers.outbox_helpers import create_outbox_event
from provisioning_service.utils.logger import logger
import bcrypt
from sqlalchemy import func

router = APIRouter(prefix="/authentication", tags=["authentication"])


# ── helper: resolve user roles + permissions ──────────────────────────

def _resolve_roles_and_permissions(db: Session, user_id, roles: List[str]) -> List[str]:
    """Resolve permission codes from global + tenant roles. tenant_admin gets wildcard."""
    role_perms = db.query(Permission.code).join(
        RolePermission, RolePermission.permission_code == Permission.code
    ).filter(RolePermission.role_code.in_(roles)).all()

    tenant_role_perms = db.query(Permission.code).join(
        TenantRolePermission, TenantRolePermission.permission_code == Permission.code
    ).join(
        TenantRole, TenantRolePermission.tenant_role_id == TenantRole.role_id
    ).join(
        TenantUserRole, TenantUserRole.tenant_role_id == TenantRole.role_id
    ).filter(TenantUserRole.user_id == user_id).all()

    perm_list = list({p[0] for p in role_perms + tenant_role_perms})
    if "tenant_admin" in roles:
        perm_list = ["*"]
    return perm_list


def _issue_internal_jwt(user_id: str, email: str, tenant_id: str, roles: List[str], permissions: List[str],
                         auth_method: str = "azure_ad", azure_oid: Optional[str] = None) -> tuple:
    """Issue an internal JWT. Returns (token, expires_at_datetime)."""
    jwt_exp_minutes = getattr(SETTINGS, "JWT_EXPIRY_MINUTES", 60)
    jwt_algorithm = getattr(SETTINGS, "JWT_ALGORITHM", "HS256")
    jwt_secret = getattr(SETTINGS, "JWT_SECRET", None)
    if not jwt_secret:
        raise HTTPException(status_code=500, detail="Server configuration error")

    now = datetime.now(timezone.utc)
    jwt_expires_at = now + timedelta(minutes=jwt_exp_minutes)

    payload = {
        "sub": user_id,
        "email": email,
        "tenant_id": tenant_id,
        "roles": roles,
        "permissions": permissions,
        "auth_method": auth_method,
        "azure_oid": azure_oid,
        "iat": int(now.timestamp()),
        "exp": int(jwt_expires_at.timestamp()),
        "iss": getattr(SETTINGS, "JWT_ISSUER", "http://mock-idp"),
        "aud": getattr(SETTINGS, "JWT_AUDIENCE", "zeroque-api"),
    }
    token = jwt.encode(payload, jwt_secret, algorithm=jwt_algorithm)
    return token, jwt_expires_at


def _build_login_response(db: Session, user: User, identity: UserIdentity,
                          token: str, jwt_expires_at: datetime, refresh_token: str,
                          roles: List[str], permissions: List[str]) -> LoginResponse:
    """Build full LoginResponse with subscription, tenant, balance, RBAC context."""
    sub_ctx = build_subscription_context(db, user.tenant_id)
    tenant_ctx = build_tenant_context(db, user.tenant_id)
    balance_ctx = build_balance_context(db, user.user_id, user.tenant_id)
    rbac_ctx = build_rbac_context(
        roles=roles,
        permissions=permissions,
        feature_codes=sub_ctx.features if sub_ctx else [],
    )

    return LoginResponse(
        user_id=str(user.user_id),
        tenant_id=str(user.tenant_id),
        email=identity.email,
        display_name=user.display_name or f"{identity.first_name} {identity.last_name}".strip(),
        first_name=identity.first_name,
        last_name=identity.last_name,
        last_login_at=user.last_login_at.isoformat() if user.last_login_at else None,
        token=token,
        expiring_at=jwt_expires_at,
        refresh_token=refresh_token,
        subscription=sub_ctx,
        tenant=tenant_ctx,
        balance=balance_ctx,
        rbac=rbac_ctx,
    )


# ── TOKEN EXCHANGE (primary auth endpoint) ─────────────────────

@router.post("/token", status_code=200)
async def token_exchange(req: TokenExchangeRequest, db: Session = Depends(get_db)):
    """
    Exchange an Azure AD / CIAM token for an internal JWT.

    Two paths:
      1. **Invitation path**  — ``invitation_token`` is present.
         Validates the invitation, creates UserIdentity + User linked to the
         inviting tenant, issues internal JWT.
      2. **Direct path**       — no invitation_token.
         For existing users: login. For new users: create UserIdentity only,
         return ``pending_onboarding``.
    """
    if not is_azure_auth_configured():
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Azure AD authentication is not configured",
        )

    # 1. Validate the Azure token
    azure_claims = await validate_azure_token(req.azure_token)

    email = azure_claims.email
    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Azure token does not contain an email claim",
        )

    oid = azure_claims.oid
    first_name = azure_claims.given_name or (azure_claims.name.split(" ")[0] if azure_claims.name else "")
    last_name = azure_claims.family_name or (" ".join(azure_claims.name.split(" ")[1:]) if azure_claims.name else "")

    # ── Invitation path ──────────────────────────────────────────────
    if req.invitation_token:
        # Validate the invitation token
        from provisioning_service.Models import Invitation
        invitations = db.query(Invitation).filter(Invitation.status == "pending").all()
        matched_inv = None
        for inv in invitations:
            try:
                if bcrypt.checkpw(req.invitation_token.encode("utf-8"), inv.token_hash.encode("utf-8")):
                    matched_inv = inv
                    break
            except Exception:
                continue

        if not matched_inv:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired invitation token")

        if matched_inv.expires_at < datetime.now(timezone.utc):
            matched_inv.status = "expired"
            db.commit()
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invitation has expired")

        if matched_inv.email.lower() != email.lower():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This invitation was sent to a different email address",
            )

        # Look up or create UserIdentity
        identity = db.query(UserIdentity).filter(func.lower(UserIdentity.email) == email.lower()).first()

        if identity:
            user_id = identity.user_id
            identity.oid = oid or identity.oid
            identity.first_name = first_name or identity.first_name
            identity.last_name = last_name or identity.last_name
            identity.auth_provider = "azure_ad"
            identity.last_azure_login_at = datetime.now(timezone.utc)
            identity.tenant_id = matched_inv.tenant_id
        else:
            user_id = _uuid.uuid4()
            identity = UserIdentity(
                user_id=user_id,
                tenant_id=matched_inv.tenant_id,
                email=email,
                oid=oid,
                auth_provider="azure_ad",
                first_name=first_name,
                last_name=last_name,
                last_azure_login_at=datetime.now(timezone.utc),
            )
            db.add(identity)

        # Create or update User row
        user = db.query(User).filter(User.user_id == user_id).first()
        if not user:
            user = User(
                user_id=user_id,
                tenant_id=matched_inv.tenant_id,
                is_active=True,
                display_name=f"{first_name} {last_name}".strip(),
                last_login_at=datetime.now(timezone.utc),
            )
            db.add(user)
        else:
            user.tenant_id = matched_inv.tenant_id
            user.is_active = True
            user.last_login_at = datetime.now(timezone.utc)

        # Mark invitation as accepted
        matched_inv.status = "accepted"
        matched_inv.accepted_by = user_id
        matched_inv.accepted_at = datetime.now(timezone.utc)

        # Assign role if specified
        if matched_inv.role_code:
            role = db.query(Role).filter(Role.code == matched_inv.role_code).first()
            if role:
                existing_role = db.query(UserRole).filter(
                    UserRole.user_id == user_id, UserRole.role_id == role.role_id
                ).first()
                if not existing_role:
                    db.add(UserRole(id=_uuid.uuid4(), tenant_id=matched_inv.tenant_id, user_id=user_id, role_id=role.role_id))

        db.commit()
        db.refresh(user)
        db.refresh(identity)

        # Resolve roles
        roles_query = db.query(Role.code).join(UserRole, Role.role_id == UserRole.role_id)\
            .filter(UserRole.user_id == user.user_id).all()
        tenant_roles_query = db.query(TenantRole.code)\
            .join(TenantUserRole, TenantRole.role_id == TenantUserRole.tenant_role_id)\
            .filter(TenantUserRole.user_id == user.user_id).all()
        roles = [r[0] for r in roles_query if r and r[0]]
        tenant_roles = [r[0] for r in tenant_roles_query if r and r[0]]
        all_roles = roles + tenant_roles

        perm_list = _resolve_roles_and_permissions(db, user.user_id, roles)

        token, jwt_expires_at = _issue_internal_jwt(
            str(user.user_id), identity.email, str(user.tenant_id), all_roles, perm_list,
            auth_method="azure_ad", azure_oid=oid,
        )
        refresh_token = issue_refresh_token(user, db)

        logger.info(f"Invitation accepted: {identity.email} joined tenant {user.tenant_id}")

        try:
            create_outbox_event(db, user.tenant_id, "user.invitation_accepted", {
                "user_id": str(user.user_id), "email": identity.email,
                "invitation_id": str(matched_inv.invitation_id),
            })
            db.commit()
        except Exception as _oe:
            logger.warning(f"Outbox failed for user.invitation_accepted: {_oe}")

        return _build_login_response(db, user, identity, token, jwt_expires_at, refresh_token, all_roles, perm_list)

    # ── Direct path (no invitation) ──────────────────────────────────

    # 2. Look up existing user identity
    identity = db.query(UserIdentity).filter(func.lower(UserIdentity.email) == email.lower()).first()

    if identity:
        # ── Existing user: update info, issue JWT ─────────────────
        identity.oid = oid or identity.oid
        identity.first_name = first_name or identity.first_name
        identity.last_name = last_name or identity.last_name
        identity.auth_provider = "azure_ad"
        identity.last_azure_login_at = datetime.now(timezone.utc)

        user = db.query(User).filter(User.user_id == identity.user_id).first()
        if not user:
            # Identity exists but no User row yet — needs onboarding
            identity.oid = oid or identity.oid
            identity.first_name = first_name or identity.first_name
            identity.last_name = last_name or identity.last_name
            identity.last_azure_login_at = datetime.now(timezone.utc)
            db.commit()
            return {
                "status": "pending_onboarding",
                "user_id": str(identity.user_id),
                "email": identity.email,
                "first_name": identity.first_name,
                "last_name": identity.last_name,
                "detail": "Identity confirmed. Complete onboarding to create your tenant and account.",
            }

        if not user.is_active:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User account is inactive")

        user.last_login_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(user)
        db.refresh(identity)

        tenant_id = str(user.tenant_id)
        user_id = str(user.user_id)

        # Resolve roles
        roles_query = db.query(Role.code).join(UserRole, Role.role_id == UserRole.role_id)\
            .filter(UserRole.user_id == user.user_id).all()
        tenant_roles_query = db.query(TenantRole.code)\
            .join(TenantUserRole, TenantRole.role_id == TenantUserRole.tenant_role_id)\
            .filter(TenantUserRole.user_id == user.user_id).all()
        roles = [r[0] for r in roles_query if r and r[0]]
        tenant_roles = [r[0] for r in tenant_roles_query if r and r[0]]
        all_roles = roles + tenant_roles

        perm_list = _resolve_roles_and_permissions(db, user.user_id, roles)

        token, jwt_expires_at = _issue_internal_jwt(
            user_id, identity.email, tenant_id, all_roles, perm_list,
            auth_method="azure_ad", azure_oid=oid,
        )
        refresh_token = issue_refresh_token(user, db)

        logger.info(f"Azure SSO login for existing user {identity.email} (tenant {tenant_id})")

        # Outbox audit event
        try:
            create_outbox_event(db, user.tenant_id, "user.azure_sso_login", {
                "user_id": user_id,
                "email": identity.email,
                "azure_oid": oid,
            })
            db.commit()
        except Exception as _oe:
            logger.warning(f"Outbox failed for user.azure_sso_login: {_oe}")

        return _build_login_response(db, user, identity, token, jwt_expires_at, refresh_token, all_roles, perm_list)

    else:
        # ── Brand new identity: create UserIdentity only, no User row yet ──
        new_user_id = _uuid.uuid4()

        identity = UserIdentity(
            user_id=new_user_id,
            tenant_id=None,  # no tenant yet — assigned during onboarding
            email=email,
            oid=oid,
            auth_provider="azure_ad",
            first_name=first_name,
            last_name=last_name,
            last_azure_login_at=datetime.now(timezone.utc),
        )
        db.add(identity)
        db.commit()
        db.refresh(identity)

        logger.info(f"New UserIdentity created: {identity.email} (pending onboarding)")

        return {
            "status": "pending_onboarding",
            "user_id": str(identity.user_id),
            "email": identity.email,
            "first_name": identity.first_name,
            "last_name": identity.last_name,
            "detail": "Identity confirmed. Complete onboarding to create your tenant and account.",
        }


# ── REFRESH JWT ───────────────────────────────────────────────────────

@router.post("/refresh-jwt", response_model=RefreshJwtResponse, status_code=200)
async def refresh_jwt(req: RefreshJwtRequest, db: Session = Depends(get_db)):
    """
    Exchange a valid refresh token for a new JWT.
    Requires: user_id and the refresh_token string returned at login.
    Rotates the refresh token on success.
    """
    user = db.query(User).filter(User.user_id == req.user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    if not getattr(user, "refresh_token", None) or not getattr(user, "refresh_token_expires_at", None):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No refresh token configured")

    if user.refresh_token_expires_at and user.refresh_token_expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token expired")

    try:
        valid = bcrypt.checkpw(req.refresh_token.encode("utf-8"), user.refresh_token.encode("utf-8"))
    except Exception:
        valid = False

    if not valid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    # Get email from UserIdentity
    identity = db.query(UserIdentity).filter(UserIdentity.user_id == user.user_id).first()
    email = identity.email if identity else ""

    roles_query = db.query(Role.code).join(UserRole, Role.role_id == UserRole.role_id)\
        .filter(UserRole.user_id == user.user_id).all()
    roles: List[str] = [r[0] for r in roles_query if r and r[0]]

    jwt_exp_minutes = getattr(SETTINGS, "JWT_EXPIRY_MINUTES", 60)
    jwt_algorithm = getattr(SETTINGS, "JWT_ALGORITHM", "HS256")
    jwt_secret = getattr(SETTINGS, "JWT_SECRET", "jwt_secret")
    if not jwt_secret:
        raise HTTPException(status_code=500, detail="Server configuration error")

    now = datetime.now(timezone.utc)
    jwt_expires_at = now + timedelta(minutes=jwt_exp_minutes)
    payload = {
        "sub": str(user.user_id),
        "email": email,
        "tenant_id": str(user.tenant_id) if user.tenant_id else None,
        "roles": roles,
        "iat": int(now.timestamp()),
        "exp": int(jwt_expires_at.timestamp()),
        "iss": getattr(SETTINGS, "JWT_ISSUER", "http://mock-idp"),
        "aud": getattr(SETTINGS, "JWT_AUDIENCE", "zeroque-api"),
    }
    token = jwt.encode(payload, jwt_secret, algorithm=jwt_algorithm)

    new_refresh_token = issue_refresh_token(user, db)

    logger.info(f"Refresh token used for user {email}, new JWT issued")
    return RefreshJwtResponse(
        token=token,
        expiring_at=jwt_expires_at.isoformat(),
        refresh_token=new_refresh_token,
        roles=roles,
    )


# ── LOGOUT ────────────────────────────────────────────────────────────

@router.post("/logout", status_code=200)
async def logout(user_id: str, db: Session = Depends(get_db)):
    """
    Log out a user: set last_logout_at, revoke stored refresh token.
    """
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid user")

    user.last_logout_at = datetime.now(timezone.utc)
    revoke_refresh_token(user, db)

    identity = db.query(UserIdentity).filter(UserIdentity.user_id == user.user_id).first()
    email = identity.email if identity else "unknown"
    logger.info(f"User {email} logged out and refresh token revoked")

    try:
        create_outbox_event(db, user.tenant_id, "user.logged_out", {
            "user_id": str(user.user_id),
            "email": email,
        })
        db.commit()
    except Exception as _oe:
        logger.warning(f"Outbox failed for user.logged_out: {_oe}")

    return {"message": "Logged out successfully"}


# ── WHOAMI ────────────────────────────────────────────────────────────

@router.get("/whoami", status_code=200)
async def whoami(
    db: Session = Depends(get_db),
    ctx=Depends(decode_jwt_with_settings),
):
    """
    Return full status check for the authenticated user: subscription,
    limits, balance, tenant info, and RBAC context.
    """
    tenant_id = _uuid.UUID(ctx["tenant_id"]) if isinstance(ctx, dict) else ctx.tenant_id
    user_id = _uuid.UUID(ctx["sub"]) if isinstance(ctx, dict) else getattr(ctx, 'sub', None)

    sub_ctx = build_subscription_context(db, tenant_id)
    tenant_ctx = build_tenant_context(db, tenant_id)
    balance_ctx = build_balance_context(db, user_id, tenant_id)

    roles = ctx.get("roles", []) if isinstance(ctx, dict) else []
    permissions = ctx.get("permissions", []) if isinstance(ctx, dict) else []
    rbac_ctx = build_rbac_context(
        roles=roles,
        permissions=permissions,
        feature_codes=sub_ctx.features if sub_ctx else [],
    )

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

    # Get email/name from UserIdentity
    identity = db.query(UserIdentity).filter(UserIdentity.user_id == user_id).first()

    return {
        "user_id": str(user_id),
        "tenant_id": str(tenant_id),
        "email": identity.email if identity else None,
        "display_name": (identity.first_name + " " + identity.last_name) if identity else None,
        "subscription": sub_ctx.model_dump() if sub_ctx else None,
        "tenant": tenant_ctx.model_dump() if tenant_ctx else None,
        "balance": balance_ctx.model_dump() if balance_ctx else None,
        "rbac": rbac_ctx.model_dump() if rbac_ctx else None,
        "catalog_price": price,
    }


# ── PUBLIC CONFIG (no auth) ──────────────────────────────────────────

@router.get("/config")
async def public_config():
    """Return non-sensitive frontend configuration."""
    return {
        "stripe_publishable_key": getattr(SETTINGS, "STRIPE_PUBLISHABLE_KEY", "") or os.getenv("STRIPE_PUBLISHABLE_KEY", ""),
        "azure_client_id": getattr(SETTINGS, "AZURE_AD_CLIENT_ID", "") or getattr(SETTINGS, "AZURE_AD_B2C_CLIENT_ID", ""),
        "azure_tenant_id": getattr(SETTINGS, "AZURE_AD_TENANT_ID", ""),
    }


import os

# ── HEALTHCHECK ───────────────────────────────────────────────────────

@router.get("/healthcheck")
async def auth_test(user=Depends(check_user_authorization('tenant.admin'))):
    return user
