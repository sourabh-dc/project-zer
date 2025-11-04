import time
from typing import Any, Dict, Optional
from fastapi import HTTPException, Request

from services.identity.repositories.db_config import AsyncSessionLocal, set_rls_context_async
from services.identity.repositories.user_creation_saga import UserCreationSaga
from services.identity.schemas import UserCreateRequest, UserResponse
from services.identity.repositories.database_ops import fetch_user_roles, fetch_users
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
