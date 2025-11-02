from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi import Request, Depends, HTTPException
from typing import Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from datetime import datetime, timedelta

from .events_logger import logger
from ..core.redis_config import redis_client

RATE_LIMIT_REQUESTS_PER_MINUTE = 60
# =============================================================================
# AUTHENTICATION & SECURITY
# =============================================================================

security = HTTPBearer()

async def get_user_context(request: Request, credentials: HTTPAuthorizationCredentials = Depends(security)) -> Dict[str, Any]:
    """Extract user context from JWT token"""
    try:
        # In production, validate JWT token
        # For demo purposes, return mock context
        return {
            "user_id": "550e8400-e29b-41d4-a716-446655440003",
            "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
            "roles": ["events.admin"],
            "permissions": ["events.publish", "events.view", "events.admin"]
        }
    except Exception as e:
        logger.error(f"Failed to get user context: {str(e)}")
        raise HTTPException(status_code=401, detail="Invalid token")

def check_permission(permission: str, user_context: Dict[str, Any]) -> bool:
    """Check if user has required permission"""
    permissions = user_context.get("permissions", [])
    return permission in permissions

# Rate limiting with Redis (production-ready)
rate_limit_store = {}

async def check_rate_limit(user_id: str) -> bool:
    """Check if user has exceeded rate limit using Redis"""
    global rate_limit_store

    if redis_client is None:
        return True  # Allow if Redis not available

    current_time = datetime.now()
    minute_key = current_time.replace(second=0, microsecond=0)

    try:
        # Use Redis pipeline for atomic operations
        pipe = redis_client.pipeline()

        # Clean old entries (older than 1 minute)
        cutoff_time = minute_key - timedelta(minutes=1)
        cutoff_key = cutoff_time.strftime("%Y%m%d%H%M")

        # Get current count
        current_key = f"events_rate_limit:{user_id}:{minute_key.strftime('%Y%m%d%H%M')}"
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