import os
from typing import Optional, Dict, Any

import jwt
from fastapi import HTTPException, Header

from core.config import get_settings
from ..utils.pricing_logger import logger

JWT_SECRET_KEY = get_settings().JWT_SECRET_KEY
JWT_ALGORITHM = get_settings().JWT_ALGORITHM

def get_user_context(authorization: Optional[str] = Header(None), x_api_key: Optional[str] = Header(None)):
    """Get user context from JWT or API key"""
    # Try API key first (simplified for demo)
    if x_api_key:
        allow_demo = os.getenv("ALLOW_DEMO", "false").lower() == "true"
        if allow_demo or x_api_key.startswith('zq_'):
            return {
                "user_id": "550e8400-e29b-41d4-a716-446655440004",  # Valid UUID
                "tenant_id": "550e8400-e29b-41d4-a716-446655440000",  # Valid UUID
                "permissions": ["payments.create", "payments.refund", "payments.adjust", "pricing.create",
                                "pricing.calculate"]
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
    allow_demo_mode = os.getenv("ALLOW_DEMO", "false").lower() == "true"
    if allow_demo_mode:
        logger.warning("Using demo mode - not for production!")
        return {"tenant_id": "550e8400-e29b-41d4-a716-446655440000", "user_id": "550e8400-e29b-41d4-a716-446655440004",
                "permissions": ["*"]}

    raise HTTPException(status_code=401, detail="Authentication required")

def check_permission(permission: str, user_context: Dict[str, Any]) -> bool:
    """Check if user has required permission"""
    permissions = user_context.get("permissions", [])
    return "*" in permissions or permission in permissions