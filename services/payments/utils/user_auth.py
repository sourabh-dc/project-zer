from typing import Optional

import jwt
from fastapi import Header, HTTPException

from core.config import get_settings
from .payments_logger import logger

ALLOW_DEMO = get_settings().ALLOW_DEMO
JWT_SECRET_KEY = get_settings().JWT_SECRET_KEY
JWT_ALGORITHM = get_settings().JWT_ALGORITHM

def get_user_context(authorization: Optional[str] = Header(None), x_api_key: Optional[str] = Header(None)):
    """Get user context from JWT or API key"""
    # Try API key first (simplified for demo)
    if x_api_key:
        if ALLOW_DEMO or x_api_key.startswith('zq_'):
            return {
                "user_id": "demo_user",
                "tenant_id": "demo_tenant",
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
    if ALLOW_DEMO:
        logger.warning("Using demo mode - not for production!")
        return {"tenant_id": "demo", "user_id": "demo", "permissions": ["*"]}

    raise HTTPException(status_code=401, detail="Authentication required")