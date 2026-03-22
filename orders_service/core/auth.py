from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

import jwt
from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from starlette import status

from orders_service.Models import Permission, Role, RolePermission
from orders_service.core.config import SETTINGS
from orders_service.core.db_config import SessionLocal
from orders_service.utils.logger import logger

bearer = HTTPBearer(auto_error=True)

DEFAULT_PERMISSIONS: List[Tuple[str, str]] = [
    ("orders.place", "Create purchase requests"),
    ("orders.view", "View purchase requests"),
    ("orders.approve", "Approve or reject tasks"),
    ("orders.manage", "Issue PO and manage order lifecycle"),
]


async def decode_jwt_token(token: str) -> Dict[str, Any]:
    try:
        return jwt.decode(
            token,
            SETTINGS.JWT_SECRET,
            algorithms=[SETTINGS.JWT_ALGORITHM],
            audience=SETTINGS.JWT_AUDIENCE,
            issuer=SETTINGS.JWT_ISSUER,
        )
    except JWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


async def decode_jwt_with_settings(
    creds: HTTPAuthorizationCredentials = Security(bearer),
) -> Dict[str, Any]:
    if not creds or not creds.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authorization header missing")
    claims = await decode_jwt_token(creds.credentials)

    now_ts = int(datetime.now(timezone.utc).timestamp())
    iat = claims.get("iat")
    exp = claims.get("exp")
    if iat is not None:
        if now_ts - int(iat) > int(SETTINGS.JWT_EXPIRY_MINUTES) * 60:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="JWT expired")
    elif exp is not None:
        if now_ts > int(exp):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="JWT expired")
    else:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="JWT missing iat/exp claims")
    return claims


def check_user_authorization(permission: str):
    async def dependency(claims: Dict[str, Any] = Security(decode_jwt_with_settings)):
        try:
            claim_perms = claims.get("permissions")
            if isinstance(claim_perms, list) and ("*" in claim_perms or permission in claim_perms):
                claims["user_id"] = claims.get("sub")
                return claims

            roles = claims.get("roles") or claims.get("role") or []
            if isinstance(roles, str):
                roles = [roles]
            elif not isinstance(roles, list):
                try:
                    roles = list(roles)
                except Exception:
                    roles = []

            if not roles:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No roles available in token")

            with SessionLocal() as db:
                match_count = (
                    db.query(RolePermission)
                    .join(Role, RolePermission.role_code == Role.code)
                    .join(Permission, RolePermission.permission_code == Permission.code)
                    .filter(Role.code.in_(roles), Permission.code == permission)
                    .count()
                )
            if match_count and match_count > 0:
                claims["user_id"] = claims.get("sub")
                return claims
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        except HTTPException:
            raise
        except Exception as exc:
            logger.error(f"Authorization error: {exc}")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authorization token")

    return dependency

