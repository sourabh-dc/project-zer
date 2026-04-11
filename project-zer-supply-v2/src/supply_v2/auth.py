from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from urllib.request import urlopen
import json

from fastapi import Depends, Header, HTTPException

from supply_v2.config import get_settings


@dataclass
class AuthContext:
    tenant_id: str
    user_id: str
    role: str
    roles: Optional[list[str]] = None
    permissions: Optional[list[str]] = None
    scopes: Optional[list[str]] = None


def _decode_bearer_token(token: str) -> dict:
    settings = get_settings()
    try:
        import jwt
    except ImportError as exc:
        raise HTTPException(500, "jwt sdk not installed") from exc
    if settings.auth_mode == "entra":
        tenant_id = settings.entra_tenant_id or settings.jwt_issuer or "common"
        authority = settings.entra_authority.rstrip("/")
        openid_url = f"{authority}/{tenant_id}/v2.0/.well-known/openid-configuration"
        if settings.entra_jwks_url:
            jwks_uri = settings.entra_jwks_url
            issuer = f"{authority}/{tenant_id}/v2.0"
        else:
            with urlopen(openid_url) as response:
                metadata = json.loads(response.read().decode("utf-8"))
            jwks_uri = metadata["jwks_uri"]
            issuer = metadata["issuer"]
        audience = settings.entra_client_id or settings.jwt_audience
        jwk_client = jwt.PyJWKClient(jwks_uri)
        signing_key = jwk_client.get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=audience,
            issuer=issuer,
            options={"require": ["exp", "iat", "iss", "aud"]},
        )
    if not settings.jwt_secret:
        raise HTTPException(401, "missing jwt secret")
    return jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=["HS256"],
        audience=settings.jwt_audience,
        issuer=settings.jwt_issuer,
    )


def get_auth_context(
    x_tenant_id: str = Header(default="tenant_demo"),
    x_user_id: str = Header(default="user_demo"),
    x_role: str = Header(default="admin"),
    authorization: Optional[str] = Header(default=None),
) -> AuthContext:
    settings = get_settings()
    if settings.auth_mode == "jwt":
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(401, "missing bearer token")
        claims = _decode_bearer_token(authorization.split(" ", 1)[1])
        return AuthContext(
            tenant_id=claims["tenant_id"],
            user_id=claims["sub"],
            role=claims.get("role", "viewer"),
            roles=claims.get("roles", []),
            permissions=claims.get("permissions", []),
            scopes=claims.get("scopes", []),
        )
    if settings.auth_mode == "entra":
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(401, "missing bearer token")
        claims = _decode_bearer_token(authorization.split(" ", 1)[1])
        return AuthContext(
            tenant_id=claims.get("tenant_id") or claims.get("tid", ""),
            user_id=claims.get("oid") or claims.get("preferred_username") or claims.get("sub"),
            role=claims.get("role", "viewer"),
            roles=claims.get("roles", []),
            permissions=claims.get("permissions", []),
            scopes=(claims.get("scp", "") or "").split(" ") if isinstance(claims.get("scp"), str) else claims.get("scopes", []),
        )
    if not x_tenant_id:
        raise HTTPException(401, "missing tenant")
    return AuthContext(
        tenant_id=x_tenant_id,
        user_id=x_user_id,
        role=x_role,
        roles=[x_role],
        permissions=[],
        scopes=[],
    )


def require_roles(*allowed_roles: str):
    def dependency(auth: AuthContext = Depends(get_auth_context)) -> AuthContext:
        if auth.role not in allowed_roles:
            raise HTTPException(403, "forbidden")
        return auth

    return dependency


def require_internal_service(
    x_internal_api_key: Optional[str] = Header(default=None),
) -> bool:
    settings = get_settings()
    if x_internal_api_key != settings.internal_api_key:
        raise HTTPException(401, "invalid internal api key")
    return True
