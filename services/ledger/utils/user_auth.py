# =============================================================================
# AUTHENTICATION & AUTHORIZATION
# =============================================================================
from typing import Optional, Dict, Any
import jwt
from fastapi import HTTPException, Header

from core.config import get_settings
from services.ledger.utils.ledger_logger import logger

# Configuration
ALLOW_DEMO = get_settings().ALLOW_DEMO
JWT_SECRET_KEY = get_settings().JWT_SECRET_KEY
JWT_ALGORITHM = get_settings().JWT_ALGORITHM


def get_user_context(authorization: Optional[str] = Header(None), x_api_key: Optional[str] = Header(None)) -> Dict[str, Any]:
    """Get user context from JWT or API key"""
    # Try API key first (simplified for Ledger service)
    if x_api_key:
        if ALLOW_DEMO or x_api_key.startswith('zq_'):
            return {
                "user_id": "demo_user",
                "tenant_id": "demo_tenant",
                "permissions": ["ledger.create", "ledger.view", "ledger.admin"]
            }
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

    # Demo mode (dev only)
    if ALLOW_DEMO:
        logger.warning("Using demo mode - not for production!")
        return {"tenant_id": "demo", "user_id": "demo", "permissions": ["*"]}

    raise HTTPException(status_code=401, detail="Authentication required")

def check_permission(required_permission: str, user_context: Dict[str, Any]) -> bool:
    """Check if user has required permission"""
    permissions = user_context.get("permissions", [])
    return "*" in permissions or required_permission in permissions