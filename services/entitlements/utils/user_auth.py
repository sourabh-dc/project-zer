from typing import Dict, Any
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from core.config import get_settings
from .entitlements_logger import logger

JWT_SECRET_KEY = get_settings().JWT_SECRET_KEY
JWT_ALGORITHM = get_settings().JWT_ALGORITHM

security = HTTPBearer()

def get_user_context(authorization: HTTPAuthorizationCredentials = Depends(security)) -> Dict[str, Any]:
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

def check_permission(required_permission: str, user_context: Dict[str, Any]) -> bool:
    permissions = user_context.get("permissions", [])
    if "*" in permissions:
        return True
    return required_permission in permissions