import time
from typing import Any, Dict, Optional, List
from fastapi import HTTPException, Request

from services.identity.repositories.db_config import AsyncSessionLocal, set_rls_context_async
from services.identity.repositories.user_creation_saga import UserCreationSaga
from services.identity.schemas import UserCreateRequest, UserResponse, RoleCreateRequest, RoleResponse, \
    RoleAssignmentRequest
from services.identity.repositories.database_ops import fetch_user_roles, fetch_users, create_role_db, list_roles_db, \
    assign_role_db
from services.identity.utils.identity_logger import logger
from services.identity.utils.user_auth import check_permission


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
