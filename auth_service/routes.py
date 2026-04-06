"""
auth_service.routes
-------------------
Auth API endpoints.

Endpoints:
    POST /auth/login             — Authenticate (Azure AD ROPC or local) → JWT
    GET  /auth/me                — Get current user context from JWT
    POST /auth/forgot-password   — Trigger password reset (Azure AD)
    POST /auth/change-password   — Change own password (Azure AD)
    POST /auth/invite            — Invite user to org (admin only)
    GET  /auth/org/members       — List org members (admin only)
    GET  /auth/org/info          — Get organization info

In azure_ad mode: Azure AD handles identity, we issue our own JWTs.
In local mode: in-memory store + same JWT issuance.
"""
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException

from auth_service.config import AUTH_MODE, JWT_EXPIRY_SECONDS
from auth_service.schemas import (
    LoginRequest, TokenResponse, UserContext, OrgInfo,
    ForgotPasswordRequest, ChangePasswordRequest, InviteUserRequest,
)
from auth_service.middleware import require_auth, require_tenant, require_role
from auth_service.token import issue_token

logger = logging.getLogger("auth_service.routes")

router = APIRouter(prefix="/auth", tags=["Authentication"])


# ── Login ─────────────────────────────────────────────────────────────

@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest):
    """Authenticate → validate credentials → issue platform JWT.

    In azure_ad mode: validates via Azure AD ROPC, looks up groups/roles.
    In local mode: validates against local store.
    """
    if AUTH_MODE == "azure_ad":
        from auth_service import management as mgmt

        try:
            ad_user = await mgmt.authenticate_user(req.email, req.password)
        except ValueError as exc:
            raise HTTPException(status_code=401, detail=str(exc))

        ad_user_id = ad_user["id"]
        groups = await mgmt.get_user_groups(ad_user_id)

        org_id = None
        if req.org_id:
            org_id = req.org_id
        elif groups:
            org_id = groups[0]["id"]

        roles = ["org_admin"] if groups else []

        token = issue_token(
            user_id=ad_user_id,
            email=req.email,
            org_id=org_id or "",
            roles=roles,
        )
        return TokenResponse(
            access_token=token,
            expires_in=JWT_EXPIRY_SECONDS,
            org_id=org_id,
            user_id=ad_user_id,
        )
    else:
        from auth_service import local_store as store

        user = store.verify_password(req.email, req.password)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid email or password")

        org_id = req.org_id
        roles = []

        if not org_id:
            for oid, members in store._memberships.items():
                if user["user_id"] in members:
                    org_id = oid
                    roles = members[user["user_id"]]
                    break
        else:
            roles = store.get_member_roles(org_id, user["user_id"])

        token = issue_token(
            user_id=user["user_id"],
            email=user["email"],
            org_id=org_id or "",
            roles=roles,
        )
        return TokenResponse(
            access_token=token,
            expires_in=JWT_EXPIRY_SECONDS,
            org_id=org_id,
            user_id=user["user_id"],
        )


# ── Me ────────────────────────────────────────────────────────────────

@router.get("/me")
async def get_me(user: UserContext = Depends(require_auth)):
    return {
        "user_id": user.user_id,
        "email": user.email,
        "org_id": user.org_id,
        "roles": user.roles,
        "permissions": user.permissions,
        "is_admin": user.is_admin,
        "is_manager": user.is_manager,
    }


# ── Forgot Password ──────────────────────────────────────────────────

@router.post("/forgot-password")
async def forgot_password(req: ForgotPasswordRequest):
    """Trigger a password reset. In azure_ad mode, resets via Graph API."""
    if AUTH_MODE == "azure_ad":
        from auth_service import management as mgmt

        ad_user = await mgmt.get_user_by_email(req.email)
        if not ad_user:
            return {"status": "ok", "message": "If the email exists, a reset link has been sent"}

        temp_password = f"Zq!{uuid.uuid4().hex[:12]}"
        await mgmt.reset_password(ad_user["id"], temp_password)
        logger.info(f"Password reset for {req.email} — temp password generated")
        return {
            "status": "ok",
            "message": "Password has been reset. Check your email for the temporary password.",
        }
    else:
        return {"status": "ok", "message": "If the email exists, a reset link has been sent"}


# ── Change Password ──────────────────────────────────────────────────

@router.post("/change-password")
async def change_password(
    req: ChangePasswordRequest,
    user: UserContext = Depends(require_auth),
):
    """Change the authenticated user's password."""
    if AUTH_MODE == "azure_ad":
        from auth_service import management as mgmt

        try:
            await mgmt.authenticate_user(user.email, req.current_password)
        except ValueError:
            raise HTTPException(status_code=401, detail="Current password is incorrect")

        await mgmt.reset_password(user.user_id, req.new_password)
        return {"status": "ok", "message": "Password changed successfully"}
    else:
        return {"status": "ok", "message": "Password changed (local mode — no-op)"}


# ── Invite User ───────────────────────────────────────────────────────

@router.post("/invite", status_code=201)
async def invite_user(
    req: InviteUserRequest,
    user: UserContext = Depends(require_role("org_admin", "org_manager")),
):
    """Invite a new user to the organization."""
    if AUTH_MODE == "azure_ad":
        from auth_service import management as mgmt

        temp_password = f"Zq!{uuid.uuid4().hex[:12]}"
        ad_user = await mgmt.create_user(req.email, temp_password, req.name)
        await mgmt.add_member(user.org_id, ad_user["id"])
        return {
            "status": "invited",
            "user_id": ad_user["id"],
            "email": req.email,
        }
    else:
        from auth_service import local_store as store
        invitation = store.invite_member(user.org_id, req.email, req.roles, user.email or "Admin")
        return {"status": "invited", "invitation_id": invitation["id"], "email": req.email}


# ── Organization Members ──────────────────────────────────────────────

@router.get("/org/members")
async def list_org_members(user: UserContext = Depends(require_role("org_admin", "org_manager"))):
    if AUTH_MODE == "azure_ad":
        from auth_service import management as mgmt
        members = await mgmt.list_members(user.org_id)
        return {"org_id": user.org_id, "members": members}
    else:
        from auth_service import local_store as store
        members = store.list_members(user.org_id)
        return {"org_id": user.org_id, "members": members}


# ── Organization Info ─────────────────────────────────────────────────

@router.get("/org/info")
async def get_org_info(user: UserContext = Depends(require_tenant)):
    if AUTH_MODE == "azure_ad":
        from auth_service import management as mgmt
        org = await mgmt.get_organization(user.org_id)
        members = await mgmt.list_members(user.org_id)
        return OrgInfo(
            org_id=org["id"],
            name=org.get("mailNickname", ""),
            display_name=org.get("displayName"),
            member_count=len(members),
        )
    else:
        from auth_service import local_store as store
        org = store.get_organization(user.org_id)
        if not org:
            raise HTTPException(404, "Organization not found")
        members = store.list_members(user.org_id)
        return OrgInfo(
            org_id=org["id"],
            name=org["name"],
            display_name=org.get("display_name"),
            member_count=len(members),
        )
