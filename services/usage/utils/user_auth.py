from typing import Optional, Dict
from fastapi import Header, HTTPException

from core.config import get_settings

# JWT Configuration
JWT_SECRET_KEY = get_settings().JWT_SECRET_KEY
JWT_ALGORITHM = get_settings().JWT_ALGORITHM
ALLOW_DEMO = get_settings().ALLOW_DEMO


def get_user_context(authorization: Optional[str] = Header(None), x_api_key: Optional[str] = Header(None)):
    """Get user context from JWT or API key"""
    # Try API key first
    if x_api_key:
        if ALLOW_DEMO or x_api_key.startswith('zq_'):
            return {
                "user_id": "demo_user",
                "tenant_id": "demo_tenant",
                "permissions": ["usage.create", "usage.view", "usage.admin"]
            }
        raise HTTPException(status_code=401, detail="Invalid API key")

    # Try JWT
    if authorization and "Bearer " in authorization:
        try:
            import jwt
            token = authorization.replace("Bearer ", "")
            claims = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
            return claims
        except Exception:
            raise HTTPException(status_code=401, detail="Invalid JWT")

    # Demo mode
    if ALLOW_DEMO:
        return {"tenant_id": "demo", "user_id": "demo", "permissions": ["*"]}

    raise HTTPException(status_code=401, detail="Authentication required")


def check_permission(user_context: Dict, permission: str) -> bool:
    """Check if user has required permission"""
    permissions = user_context.get("permissions", [])
    return "*" in permissions or permission in permissions