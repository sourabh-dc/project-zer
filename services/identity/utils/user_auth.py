import os
from datetime import timedelta, datetime
from typing import Optional, Any, Dict, List

import jwt
from fastapi import Depends, Header, Request, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from core.config import get_settings
from services.identity.utils.identity_logger import logger

ALLOW_DEMO = get_settings().ALLOW_DEMO
JWT_SECRET = get_settings().JWT_SECRET_KEY
JWT_ALGORITHM = get_settings().JWT_ALGORITHM
JWT_EXPIRY_MINUTES = int(os.getenv("JWT_EXPIRY_MINUTES", "60"))
GUEST_TOKEN_TTL_HOURS = int(os.getenv("GUEST_TOKEN_TTL_HOURS", "24"))
RATE_LIMIT_REQUESTS_PER_MINUTE = 60

security = HTTPBearer(auto_error=False)  # Don't auto-error, we'll check API key fallback

# =============================================================================
# AUTHENTICATION & SECURITY
# =============================================================================
async def get_user_context(
        request: Request,
        credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
        x_api_key: Optional[str] = Header(None)
) -> Dict[str, Any]:
    """Get user context from JWT token or API key"""

    # Demo mode - check API key first
    if ALLOW_DEMO and x_api_key == "zq_demo_key_for_testing":
        return {
            "user_id": "demo-user",
            "tenant_id": "demo-tenant",
            "roles": ["identity.admin"],
            "permissions": ["*"]  # Wildcard for demo mode
        }

    # Try Bearer token
    if credentials:
        try:
            token = credentials.credentials
            payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
            return payload
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Token expired")
        except jwt.InvalidTokenError:
            raise HTTPException(status_code=401, detail="Invalid token")

    # Demo mode fallback
    if ALLOW_DEMO:
        return {
            "user_id": "demo-user",
            "tenant_id": "demo-tenant",
            "permissions": ["*"]
        }

    raise HTTPException(status_code=401, detail="Not authenticated")


def check_permission(required_permission: str, user_context: Dict[str, Any]) -> bool:
    """Check if user has required permission"""
    user_permissions = user_context.get("permissions", [])

    # Wildcard permission (demo mode or superadmin)
    if "*" in user_permissions:
        return True

    # Exact match
    if required_permission in user_permissions:
        return True

    # Check permission hierarchy
    permission_parts = required_permission.split(".")
    for i in range(len(permission_parts)):
        wildcard_perm = ".".join(permission_parts[:i + 1]) + ".*"
        if wildcard_perm in user_permissions:
            return True

    return False

# Rate limiting with Redis (production-ready)
async def check_rate_limit(user_id: str) -> bool:
    """Check if user has exceeded rate limit using Redis"""
    global redis_client

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
        current_key = f"identity_rate_limit:{user_id}:{minute_key.strftime('%Y%m%d%H%M')}"
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



# =============================================================================
# JWT TOKEN MANAGEMENT
# =============================================================================

def generate_jwt_token(user_id: str, tenant_id: str, permissions: List[str], token_type: str = "loyalty") -> str:
    """Generate JWT token"""
    now = datetime.utcnow()
    expiry = now + timedelta(minutes=JWT_EXPIRY_MINUTES)

    payload = {
        "user_id": user_id,
        "tenant_id": tenant_id,
        "permissions": permissions,
        "token_type": token_type,
        "iat": now,
        "exp": expiry
    }

    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def generate_guest_token(tenant_id: str, guest_info: Optional[Dict[str, Any]] = None) -> str:
    """Generate guest JWT token"""
    now = datetime.utcnow()
    expiry = now + timedelta(hours=GUEST_TOKEN_TTL_HOURS)

    payload = {
        "tenant_id": tenant_id,
        "permissions": ["guest.access"],
        "token_type": "guest",
        "guest_info": guest_info or {},
        "iat": now,
        "exp": expiry
    }

    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)