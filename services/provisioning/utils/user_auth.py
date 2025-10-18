from fastapi import HTTPException, Header
import secrets
import jwt

from ..repositories.user_repository import get_user_from_key
from ..schemas import *
from core.config import get_settings
from ..utils.provisioning_logger import logger

SERVICE_NAME = "provisioning"
SERVICE_VERSION = "4.1.1"
DATABASE_URL = get_settings().DATABASE_URL
RABBITMQ_URL = get_settings().RABBITMQ_URL
REDIS_URL = get_settings().REDIS_URL
SUBSCRIPTIONS_SERVICE_URL = get_settings().SUBSCRIPTIONS_SERVICE_URL
JWT_SECRET_KEY = get_settings().JWT_SECRET_KEY
JWT_ALGORITHM = get_settings().JWT_ALGORITHM
JWT_EXPIRATION_HOURS = get_settings().JWT_EXPIRATION_HOURS
ALLOW_DEMO = get_settings().ALLOW_DEMO
SERVICE_PORT = get_settings().SERVICE_PORT


# Auth
def gen_api_key():
    return f"zq_{secrets.token_urlsafe(32)}"


def verify_api_key(key):
    try:
        u = get_user_from_key(key)
        return {"user_id": str(u.user_id), "tenant_id": str(u.tenant_id),
                "permissions": u.permissions or ["*"]} if u else None
    except Exception as e:
        logger.error(f"API key verify: {e}")
        return None


def get_user_context(authorization: Optional[str] = Header(None), x_api_key: Optional[str] = Header(None)):
    # Demo mode (dev only) - check first for demo API key
    if ALLOW_DEMO and x_api_key == "zq_demo_key_for_testing":
        logger.warning("Using demo API key - not for production!")
        return {"tenant_id": "demo", "user_id": "demo", "permissions": ["*"]}

    # Try API key first
    if x_api_key:
        ctx = verify_api_key(x_api_key)
        if ctx:
            return ctx
        raise HTTPException(status_code=401, detail="Invalid API key")

    # Try JWT
    if authorization and "Bearer " in authorization:
        try:
            token = authorization.replace("Bearer ", "")
            claims = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
            return claims
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Token expired")
        except jwt.InvalidTokenError:
            raise HTTPException(status_code=401, detail="Invalid JWT")

    # Demo mode fallback (dev only)
    if ALLOW_DEMO:
        logger.warning("Using demo mode - not for production!")
        return {"tenant_id": "demo", "user_id": "demo", "permissions": ["*"]}

    raise HTTPException(status_code=401, detail="Authentication required")


def check_permission(uctx: Dict, required_permission: str):
    """Check if user has required permission"""
    permissions = uctx.get("permissions", [])

    # Wildcard permission (demo mode or superadmin)
    if "*" in permissions:
        return True

    # Exact match
    if required_permission in permissions:
        return True

    # Check permission hierarchy (e.g., "provisioning.*" grants "provisioning.bulk_import")
    permission_parts = required_permission.split(".")
    for i in range(len(permission_parts)):
        wildcard_perm = ".".join(permission_parts[:i + 1]) + ".*"
        if wildcard_perm in permissions:
            return True

    raise HTTPException(
        status_code=403,
        detail=f"Permission denied: {required_permission} required"
    )