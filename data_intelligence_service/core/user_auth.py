# ==================================================================================
# AUTHENTICATION — JWT decoding (mirrors provisioning_service/core/user_auth.py)
# ==================================================================================
# Tokens are issued by provisioning_service POST /authentication/* endpoints.
# This service only DECODES and validates them — it never issues tokens.
#
# The decoded claims carry: sub (user_id), tenant_id, roles, permissions, email.
# Downstream code reads request.state.user_claims (set by the middleware).
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx
import jwt
from jose import JWTError

from data_intelligence_service.core.config import SETTINGS
from data_intelligence_service.core.logger import logger

JWKS_CACHE: Dict[str, Any] = {}
JWKS_CACHE_EXPIRES_AT: float = 0.0


async def fetch_jwks() -> Optional[Dict[str, Any]]:
    global JWKS_CACHE_EXPIRES_AT
    if not SETTINGS.JWT_JWKS_URL:
        return None

    now_ts = datetime.utcnow().timestamp()
    if JWKS_CACHE and JWKS_CACHE_EXPIRES_AT > now_ts:
        return JWKS_CACHE

    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(SETTINGS.JWT_JWKS_URL)
        resp.raise_for_status()
        JWKS_CACHE.clear()
        JWKS_CACHE.update(resp.json())
        JWKS_CACHE_EXPIRES_AT = now_ts + SETTINGS.JWT_CACHE_SECONDS
        return JWKS_CACHE


async def decode_jwt_token(token: str) -> Dict[str, Any]:
    """Decode and validate a provisioning-issued JWT. Raises on any failure."""
    if SETTINGS.JWT_ALGORITHM.upper().startswith("HS"):
        if not SETTINGS.JWT_SECRET:
            raise RuntimeError("JWT_SECRET must be configured for HS algorithms")
        claims = jwt.decode(
            token,
            SETTINGS.JWT_SECRET,
            algorithms=[SETTINGS.JWT_ALGORITHM],
            audience=SETTINGS.JWT_AUDIENCE,
            issuer=SETTINGS.JWT_ISSUER,
        )
    else:
        jwks = await fetch_jwks()
        if not jwks:
            raise RuntimeError("JWKS URL must be configured for asymmetric algorithms")
        claims = jwt.decode(
            token,
            jwks,
            algorithms=[SETTINGS.JWT_ALGORITHM],
            audience=SETTINGS.JWT_AUDIENCE,
            issuer=SETTINGS.JWT_ISSUER,
        )

    _check_expiry(claims)
    return claims


def _check_expiry(claims: Dict[str, Any]) -> None:
    """Same age/expiry rules as provisioning_service decode_jwt_with_settings."""
    jwt_exp_minutes = int(getattr(SETTINGS, "JWT_EXPIRY_MINUTES", 60))
    now_ts = int(datetime.now(timezone.utc).timestamp())

    iat = claims.get("iat")
    if iat is not None:
        try:
            iat_ts = int(iat)
        except Exception:
            raise ValueError("Invalid iat claim")
        if now_ts - iat_ts > jwt_exp_minutes * 60:
            raise ValueError("JWT expired (age exceeds configured expiry)")
    elif "exp" in claims:
        try:
            exp_ts = int(claims["exp"])
        except Exception:
            raise ValueError("Invalid exp claim")
        if now_ts > exp_ts:
            raise ValueError("JWT expired")
    else:
        raise ValueError("JWT missing iat/exp claims")


async def decode_bearer_token(authorization: str) -> Dict[str, Any]:
    """Extract and decode the Bearer token from an Authorization header value."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise ValueError("Authorization header missing or not Bearer")
    raw = authorization.split(" ", 1)[1].strip()
    if not raw:
        raise ValueError("Empty bearer token")
    try:
        return await decode_jwt_token(raw)
    except (JWTError, jwt.ExpiredSignatureError, jwt.InvalidTokenError) as exc:
        raise ValueError(str(exc)) from exc
