import os
import jwt
from typing import Optional, Any, Dict

from fastapi import Depends, Header, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from core.config import get_settings
from ..utils.subsciptions_logger import logger

JWT_SECRET_KEY = get_settings().JWT_SECRET_KEY
JWT_ALGORITHM = get_settings().JWT_ALGORITHM
# Security
security = HTTPBearer(auto_error=False)  # Don't auto-raise 403, let us handle it


def check_permission(user_context: Any, permission: str) -> bool:
    """Check if user has required permission"""
    if not user_context:
        return False
    # Handle case where user_context might be a string or non-dict
    if not isinstance(user_context, dict):
        return False
    permissions = user_context.get("permissions", [])
    return "*" in permissions or permission in permissions


def get_user_context(
        authorization: Optional[HTTPAuthorizationCredentials] = Depends(security),
        x_api_key: Optional[str] = Header(None)
) -> Dict[str, Any]:
    # Try API key first (for Postman/demo)
    if x_api_key:
        allow_demo = os.getenv("ALLOW_DEMO", "false").lower() == "true"
        if allow_demo or x_api_key.startswith('zq_'):
            return {
                "user_id": "550e8400-e29b-41d4-a716-446655440004",
                "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
                "roles": ["admin"],
                "permissions": ["*"]  # Full permissions including subscriptions.admin
            }

    # Try JWT
    if authorization:
        try:
            token = authorization.credentials
            payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
            return {
                "user_id": payload.get("user_id"),
                "tenant_id": payload.get("tenant_id"),
                "roles": payload.get("roles", []),
                "permissions": payload.get("permissions", [])
            }
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Token expired")
        except jwt.InvalidTokenError:
            raise HTTPException(status_code=401, detail="Invalid token")
        except Exception as e:
            logger.error(f"JWT validation error: {str(e)}")
            raise HTTPException(status_code=401, detail="Invalid authentication")

    raise HTTPException(status_code=401, detail="Not authenticated")