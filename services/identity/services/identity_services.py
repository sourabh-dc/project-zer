import os
import secrets
import time
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, List

import jwt
from fastapi import HTTPException, Request

from core.config import get_settings
from services.identity.repositories.db_config import AsyncSessionLocal, set_rls_context_async
from services.identity.repositories.user_creation_saga import UserCreationSaga
from services.identity.schemas import UserCreateRequest, UserResponse, RoleCreateRequest, RoleResponse, \
    RoleAssignmentRequest, TokenRequest, TokenResponse, ReportResponse, OAuthProviderCreateRequest
from services.identity.repositories.database_ops import fetch_user_roles, fetch_users, create_role_db, list_roles_db, \
    assign_role_db, get_user_permissions_db, get_reports_db, create_oauth_provider_db, list_oauth_providers_db, \
    initiate_oauth_flow_db, finalize_oauth_callback_db, get_oauth_session_and_provider_db
from services.identity.utils.identity_logger import logger
from services.identity.utils.user_auth import check_permission, generate_guest_token, generate_jwt_token


settings = get_settings()
JWT_SECRET = settings.JWT_SECRET_KEY
JWT_ALGORITHM = settings.JWT_ALGORITHM
OAUTH_JWT_TTL_HOURS = 24

OAUTH_SESSION_TTL_MINUTES = 10

async def create_user(payload: UserCreateRequest, request: Request, user_context: Dict[str, Any]):
    """Create user with role assignments"""
    start_time = time.time()

    try:
        # Check permissions
        if not check_permission("identity.create_user", user_context):
            raise HTTPException(status_code=403, detail="Insufficient permissions")

        # Execute saga
        async with AsyncSessionLocal() as db:
            await set_rls_context_async(db, payload.tenant_id, user_context["user_id"])
            saga = UserCreationSaga(db)
            user = await saga.execute_create_user(payload, user_context)

        # Get user with roles
        async with AsyncSessionLocal() as db:
            await set_rls_context_async(db, payload.tenant_id, user_context["user_id"])
            roles = await fetch_user_roles(db, str(user.id), str(payload.tenant_id))

        pass  # Metrics disabled - start_time)

        return UserResponse(
            id=str(user.id),
            tenant_id=str(user.tenant_id),
            email=user.email,
            name=user.name,
            primary_cost_centre_id=str(user.primary_cost_centre_id) if user.primary_cost_centre_id else None,
            metadata=user.user_metadata,
            created_at=user.created_at.isoformat(),
            updated_at=user.updated_at.isoformat() if user.updated_at else None,
            roles=roles
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create user: {str(e)}")
        pass  # Metrics disabled
        pass  # Metrics disabled - start_time)
        raise HTTPException(status_code=500, detail=str(e))


async def get_users(tenant_id: str, email_filter: Optional[str], role_filter: Optional[str], user_context: Dict[str, Any]
):
    """List users with optional filters"""
    start_time = time.time()

    try:
        # Check permissions
        if not check_permission("identity.view_user", user_context):
            raise HTTPException(status_code=403, detail="Insufficient permissions")

        async with AsyncSessionLocal() as db:
            await set_rls_context_async(db, tenant_id, user_context["user_id"])
            users_data = await fetch_users(db, tenant_id, email_filter, role_filter)

        users = [
            UserResponse(
                id=u["id"],
                tenant_id=u["tenant_id"],
                email=u["email"],
                name=u["name"],
                primary_cost_centre_id=u["primary_cost_centre_id"],
                metadata=u["user_metadata"],
                created_at=u["created_at"],
                updated_at=u["updated_at"],
                roles=u["roles"]
            )
            for u in users_data
        ]
        pass  # Metrics disabled - start_time)

        return users

    except Exception as e:
        logger.error(f"Failed to list users: {str(e)}")
        pass  # Metrics disabled
        pass  # Metrics disabled - start_time)
        raise HTTPException(status_code=500, detail=str(e))


async def create_role(payload: RoleCreateRequest, request: Request, user_context: Dict[str, Any]) -> RoleResponse:
    """
    Business logic for creating a role
    """
    start_time = time.time()

    try:
        if not check_permission("identity.admin", user_context):
            raise HTTPException(status_code=403, detail="Insufficient permissions")

        async with AsyncSessionLocal() as db:
            await set_rls_context_async(db, payload.tenant_id, user_context["user_id"])
            role = await create_role_db(db, payload, user_context["user_id"])

        # Map to response
        return RoleResponse(
            id=str(role.id),
            tenant_id=str(role.tenant_id),
            name=role.name,
            description=role.description,
            permissions=role.permissions,
            created_at=role.created_at.isoformat(),
            updated_at=role.updated_at.isoformat() if role.updated_at else None,
            user_count=0
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create role: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


async def get_roles(tenant_id: str, user_context: Dict[str, Any]) -> List[RoleResponse]:
    """
    Business logic for listing roles:
    """
    start_time = time.time()
    try:
        if not check_permission("identity.view_role", user_context):
            raise HTTPException(status_code=403, detail="Insufficient permissions")

        async with AsyncSessionLocal() as db:
            await set_rls_context_async(db, tenant_id, user_context["user_id"])
            roles_data = await list_roles_db(db, tenant_id)

        roles = [
            RoleResponse(
                id=r["id"],
                tenant_id=r["tenant_id"],
                name=r["name"],
                description=r["description"],
                permissions=r["permissions"],
                created_at=r["created_at"],
                updated_at=r["updated_at"],
                user_count=r["user_count"]
            )
            for r in roles_data
        ]

        return roles

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to list roles: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


async def assign_role(payload: RoleAssignmentRequest, request: Request, user_context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Business logic for assigning a role:
    - Check permissions
    - Open DB session and set RLS
    - Delegate DB writes to repository
    - Return simple confirmation
    """
    start_time = time.time()
    try:
        if not check_permission("identity.admin", user_context):
            raise HTTPException(status_code=403, detail="Insufficient permissions")

        async with AsyncSessionLocal() as db:
            await set_rls_context_async(db, payload.tenant_id, user_context["user_id"])
            result = await assign_role_db(db, payload, user_context["user_id"])

        return {"ok": True, "message": "Role assigned successfully", "assignment_id": result["assignment_id"]}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to assign role: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# Read env defaults here in service to avoid importing main module
GUEST_TOKEN_TTL_HOURS = int(os.getenv("GUEST_TOKEN_TTL_HOURS", "24"))
JWT_EXPIRY_MINUTES = int(os.getenv("JWT_EXPIRY_MINUTES", "60"))

async def generate_token_service(payload: TokenRequest, request: Request, user_context: Dict[str, Any]) -> TokenResponse:
    """
    Business logic for token generation:
    - permission check
    - guest: generate guest token
    - loyalty: validate user, fetch permissions via repository, generate JWT
    """
    start_time = time.time()
    try:
        if not check_permission("identity.generate_token", user_context):
            raise HTTPException(status_code=403, detail="Insufficient permissions")

        if payload.token_type == "guest":
            token = generate_guest_token(payload.tenant_id, payload.guest_info)
            expires_at = datetime.utcnow() + timedelta(hours=GUEST_TOKEN_TTL_HOURS)
            permissions = ["guest.access"]
            user_id = None

        elif payload.token_type == "loyalty":
            if not payload.user_id:
                raise HTTPException(status_code=400, detail="user_id required for loyalty tokens")

            async with AsyncSessionLocal() as db:
                await set_rls_context_async(db, payload.tenant_id, user_context["user_id"])
                user_info = await get_user_permissions_db(db, payload.tenant_id, payload.user_id)

            if not user_info:
                raise HTTPException(status_code=404, detail="User not found")

            permissions = user_info["permissions"]
            user_id = user_info["user_id"]

            token = generate_jwt_token(user_id, payload.tenant_id, permissions, "loyalty")
            expires_at = datetime.utcnow() + timedelta(minutes=JWT_EXPIRY_MINUTES)

        else:
            raise HTTPException(status_code=400, detail="Invalid token_type. Must be 'guest' or 'loyalty'")

        return TokenResponse(
            token=token,
            token_type=payload.token_type,
            expires_at=expires_at.isoformat(),
            user_id=user_id,
            permissions=permissions
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to generate token: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

async def get_reports_service(
    tenant_id: str,
    report_type: str,
    period_start: Optional[str],
    period_end: Optional[str],
    user_context: Dict[str, Any]
) -> ReportResponse:
    """
    Business logic for reports:
    - permission check
    - set RLS
    - delegate SQL to repository
    - map to ReportResponse
    """
    start_time = time.time()
    try:
        if not check_permission("identity.view_reports", user_context):
            raise HTTPException(status_code=403, detail="Insufficient permissions")

        async with AsyncSessionLocal() as db:
            await set_rls_context_async(db, tenant_id, user_context["user_id"])
            result = await get_reports_db(db, tenant_id, report_type, period_start, period_end)

        return ReportResponse(
            report_type=report_type,
            tenant_id=tenant_id,
            generated_at=datetime.utcnow().isoformat(),
            period={"start": period_start, "end": period_end} if period_start and period_end else None,
            summary=result["summary"],
            data=result["data"]
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get reports: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


async def create_oauth_provider_service(req: OAuthProviderCreateRequest, user_context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Business logic for creating OAuth provider:
    - permission check
    - set RLS
    - delegate persistence to repository
    - return minimal response
    """
    start_time = time.time()
    try:
        if not check_permission("identity.oauth_admin", user_context):
            raise HTTPException(status_code=403, detail="Insufficient permissions - OAuth configuration requires Pro or Enterprise plan")

        async with AsyncSessionLocal() as db:
            await set_rls_context_async(db, req.tenant_id, user_context["user_id"])
            res = await create_oauth_provider_db(db, req, user_context["user_id"])

        return {
            "provider_id": res["provider_id"],
            "tenant_id": req.tenant_id,
            "provider_type": req.provider_type,
            "provider_name": req.provider_name,
            "enabled": res["enabled"],
            "created_at": res["created_at"]
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create OAuth provider: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def list_oauth_providers_service(tenant_id: str, user_context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Business logic for listing OAuth providers:
    - permission check
    - set RLS
    - delegate data fetch to repository
    """
    start_time = time.time()
    try:
        if not check_permission("identity.view_oauth_provider", user_context):
            raise HTTPException(status_code=403, detail="Insufficient permissions")

        async with AsyncSessionLocal() as db:
            await set_rls_context_async(db, tenant_id, user_context["user_id"])
            providers = await list_oauth_providers_db(db, tenant_id)

        return {"tenant_id": tenant_id, "providers": providers}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to list OAuth providers: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def initiate_oauth_flow_service(req, user_context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Business logic:
    - permission check
    - open DB session, set RLS
    - generate state & PKCE verifier
    - delegate persistence to repository
    - build authorization URL and return minimal response
    """
    try:
        if not check_permission("identity.view_oauth_provider", user_context):
            raise HTTPException(status_code=403, detail="Insufficient permissions")

        state = secrets.token_urlsafe(32)
        code_verifier = secrets.token_urlsafe(64)

        async with AsyncSessionLocal() as db:
            await set_rls_context_async(db, req.tenant_id, user_context["user_id"])
            res = await initiate_oauth_flow_db(
                db,
                tenant_id=req.tenant_id,
                provider_id=req.provider_id,
                state=state,
                code_verifier=code_verifier,
                redirect_uri=req.redirect_uri,
                ttl_minutes=OAUTH_SESSION_TTL_MINUTES
            )

        if not res:
            raise HTTPException(status_code=404, detail="OAuth provider not found or disabled")

        provider = res["provider"]
        session = res["session"]

        # Build authorization URL (keep same logic as original)
        auth_url = ""
        if provider["provider_type"] == "azure_ad":
            auth_url = f"https://login.microsoftonline.com/{provider['tenant_domain']}/oauth2/v2.0/authorize"
        elif provider["provider_type"] == "google":
            auth_url = "https://accounts.google.com/o/oauth2/v2/auth"
        elif provider.get("discovery_url"):
            auth_url = provider["discovery_url"].replace("/.well-known/openid-configuration", "/authorize")
        else:
            raise HTTPException(status_code=400, detail="Provider configuration incomplete")

        scopes_str = " ".join(provider.get("scopes", []))
        full_auth_url = (
            f"{auth_url}"
            f"?client_id={provider['client_id']}"
            f"&response_type=code"
            f"&redirect_uri={req.redirect_uri}"
            f"&scope={scopes_str}"
            f"&state={session['state']}"
        )

        logger.info(f"OAuth flow initiated for provider {provider['provider_name']}, session {session['session_id']}")

        return {
            "session_id": session["session_id"],
            "authorization_url": full_auth_url,
            "state": session["state"],
            "expires_at": session["expires_at"]
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to initiate OAuth flow: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def oauth_callback_service(req, user_context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Service handling OAuth callback:
    - fetch session+provider from DB (repo)
    - validate expiry
    - perform token exchange (simulated here)
    - delegate persistence (repo) to create/find user and update session
    - generate JWT for the user and return minimal response
    """
    try:
        async with AsyncSessionLocal() as db:
            res = await get_oauth_session_and_provider_db(db, req.state)

            if not res:
                raise HTTPException(status_code=404, detail="Invalid or expired OAuth session")

            session = res["session"]
            provider = res["provider"]

            # expiry check
            if session.expires_at and session.expires_at < datetime.utcnow():
                session.status = "failed"
                await db.commit()
                raise HTTPException(status_code=400, detail="OAuth session expired")

            # Determine token endpoint (kept simple / mirrored from original)
            token_url = ""
            if provider.provider_type == "azure_ad":
                token_url = f"https://login.microsoftonline.com/{provider.tenant_domain}/oauth2/v2.0/token"
            elif provider.provider_type == "google":
                token_url = "https://oauth2.googleapis.com/token"
            elif provider.discovery_url:
                token_url = provider.discovery_url.replace("/.well-known/openid-configuration", "/token")

            # Simulate token exchange / user info fetch (replace with real HTTP exchange in prod)
            external_user_id = f"{provider.provider_type}_user_{secrets.token_hex(8)}"
            external_email = f"user@{provider.provider_type}.example.com"

            # Persist user and update session via repo
            persisted = await finalize_oauth_callback_db(
                db,
                session_id=session.id,
                external_user_id=external_user_id,
                external_email=external_email,
                provider_name=provider.provider_name
            )

            # Generate JWT for the user
            token_payload = {
                "user_id": persisted["user_id"],
                "tenant_id": persisted["tenant_id"],
                "email": persisted["email"],
                "exp": datetime.utcnow() + timedelta(hours=OAUTH_JWT_TTL_HOURS)
            }
            jwt_token = jwt.encode(token_payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

            logger.info(f"OAuth callback successful, user {persisted['user_id']} authenticated via {persisted['provider_name']}")

            return {
                "success": True,
                "user_id": persisted["user_id"],
                "email": persisted["email"],
                "token": jwt_token,
                "provider": persisted["provider_name"]
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"OAuth callback service failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
