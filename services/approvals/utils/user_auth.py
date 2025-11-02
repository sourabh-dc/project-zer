from datetime import timedelta, datetime
from typing import Optional

import jwt
from fastapi import Depends, Header
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from core.config import get_settings
from services.approvals.schemas import UserContext
from services.approvals.utils.approvals_logger import log, logger
from ..core.redis_config import redis_client

# Security Dependencies
security = HTTPBearer(auto_error=False)
RATE_LIMIT_REQUESTS_PER_MINUTE = 100
JWT_SECRET_KEY = get_settings().JWT_SECRET_KEY
JWT_ALGORITHM = get_settings().JWT_ALGORITHM

async def validate_jwt_token(token: str) -> Optional[UserContext]:
    """Validate JWT token and extract user context"""
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])

        # Extract user context from JWT payload
        user_context = UserContext(
            user_id=payload.get("user_id", ""),
            tenant_id=payload.get("tenant_id", ""),
            roles=payload.get("roles", []),
            permissions=payload.get("permissions", []),
            site_id=payload.get("site_id"),
            store_id=payload.get("store_id")
        )

        return user_context

    except jwt.ExpiredSignatureError:
        log.warning("JWT token expired")
        return None
    except jwt.InvalidTokenError:
        log.warning("Invalid JWT token")
        return None
    except Exception as e:
        log.error(f"JWT validation error: {str(e)}")
        return None


async def get_user_context(
        authorization: Optional[HTTPAuthorizationCredentials] = Depends(security),
        x_api_key: Optional[str] = Header(None, alias="X-API-Key")
) -> UserContext:
    """Extract user context from request"""

    # For demo purposes, create a default user context
    # In production, this would validate JWT or API key
    if authorization and authorization.credentials:
        user_context = await validate_jwt_token(authorization.credentials)
        if user_context:
            return user_context

    # Fallback for demo/testing - create a default context
    log.warning("No valid authentication provided, using demo context")
    return UserContext(
        user_id="550e8400-e29b-41d4-a716-446655440004",
        tenant_id="550e8400-e29b-41d4-a716-446655440000",
        roles=["admin", "approver"],
        permissions=["approval.create", "approval.approve", "approval.view"],
        site_id="550e8400-e29b-41d4-a716-446655440001",
        store_id="550e8400-e29b-41d4-a716-446655440002"
    )

async def check_rate_limit(user_id: str) -> bool:
    """Check if user has exceeded rate limit using Redis"""
    current_time = datetime.now()
    minute_key = current_time.replace(second=0, microsecond=0)

    try:
        # Use Redis pipeline for atomic operations
        pipe = redis_client.pipeline()

        # Clean old entries (older than 1 minute)
        cutoff_time = minute_key - timedelta(minutes=1)
        cutoff_key = cutoff_time.strftime("%Y%m%d%H%M")

        # Remove old minute keys for this user
        old_keys = redis_client.keys(f"rate_limit:{user_id}:*")
        for key in old_keys:
            if key < f"rate_limit:{user_id}:{cutoff_key}":
                pipe.delete(key)

        # Get current count
        current_key = f"rate_limit:{user_id}:{minute_key.strftime('%Y%m%d%H%M')}"
        pipe.incr(current_key)
        pipe.expire(current_key, 60)  # Expire after 60 seconds

        results = pipe.execute()
        current_count = results[-2]  # The INCR result

        if current_count > RATE_LIMIT_REQUESTS_PER_MINUTE:
            return False

        return True

    except Exception as e:
        logger.warning(f"Redis rate limit check failed, allowing request: {e}")
        return True  # Fail open for rate limiting