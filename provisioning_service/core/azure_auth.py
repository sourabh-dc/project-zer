"""
provisioning_service/core/azure_auth.py
---------------------------------------
Azure AD B2C / Entra ID token validation.

Validates tokens issued by Azure AD B2C (or Entra ID) using the OpenID
Connect discovery document and JWKS endpoint.  Extracts tenant_id and
role claims so the rest of the stack can enforce multi-tenant isolation.

Usage:
    from provisioning_service.core.azure_auth import (
        validate_azure_token,
        AzureTokenClaims,
    )

    claims = await validate_azure_token(raw_bearer_token)
    # claims.oid    -> Azure object ID
    # claims.email  -> user email
    # claims.tenant_id -> mapped internal tenant_id (custom claim)
"""

import time
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx
import jwt as pyjwt
from jwt import PyJWKClient, PyJWK
from fastapi import HTTPException
from starlette import status

from provisioning_service.core.config import SETTINGS

logger = logging.getLogger("azure_auth")

# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------

def _b2c_authority() -> Optional[str]:
    """Build the Azure AD B2C authority URL from settings."""
    tenant = getattr(SETTINGS, "AZURE_AD_B2C_TENANT", None)
    policy = getattr(SETTINGS, "AZURE_AD_B2C_POLICY", None)
    if tenant and policy:
        return (
            f"https://{tenant}.b2clogin.com/"
            f"{tenant}.onmicrosoft.com/{policy}/v2.0"
        )
    return None


def _entra_authority() -> Optional[str]:
    """Build the Entra ID (Azure AD v2) authority URL from settings."""
    tenant_id = getattr(SETTINGS, "AZURE_AD_TENANT_ID", None)
    if tenant_id:
        return f"https://login.microsoftonline.com/{tenant_id}/v2.0"
    return None


def _ciam_authority() -> Optional[str]:
    """Build the Azure CIAM authority URL from settings."""
    tenant_id = getattr(SETTINGS, "AZURE_AD_TENANT_ID", None)
    if not tenant_id:
        return None
    is_ciam = getattr(SETTINGS, "AZURE_AD_CIAM", False)
    if is_ciam or getattr(SETTINGS, "AZURE_AD_AUTHORITY", "").startswith("ciam"):
        hostname = getattr(SETTINGS, "AZURE_AD_CIAM_HOSTNAME", None) or f"{tenant_id}.ciamlogin.com"
        return f"https://{hostname}/{tenant_id}/v2.0"
    return None


def _get_authority() -> Optional[str]:
    """Return the first configured authority (CIAM > B2C > Entra)."""
    return _ciam_authority() or _b2c_authority() or _entra_authority()


def _get_client_ids() -> list:
    """Return all valid Azure AD application (client) IDs as audience values."""
    ids = []
    for attr in ("AZURE_AD_CLIENT_ID", "AZURE_AD_SPA_CLIENT_ID", "AZURE_AD_B2C_CLIENT_ID"):
        val = getattr(SETTINGS, attr, None)
        if val:
            ids.append(val)
    return ids


def _get_primary_client_id() -> Optional[str]:
    """Return the primary client ID (first configured)."""
    ids = _get_client_ids()
    return ids[0] if ids else None


# ---------------------------------------------------------------------------
# JWKS + OIDC discovery cache
# ---------------------------------------------------------------------------

_OIDC_CACHE: Dict[str, Any] = {}
_OIDC_CACHE_AT: float = 0.0
_JWKS_CLIENT: Optional[PyJWKClient] = None
_JWKS_CLIENT_AT: float = 0.0

CACHE_TTL = getattr(SETTINGS, "JWT_CACHE_SECONDS", 300)


async def _fetch_oidc_config(authority: str) -> Dict[str, Any]:
    """Fetch and cache the OpenID Connect discovery document."""
    global _OIDC_CACHE, _OIDC_CACHE_AT

    now = time.time()
    if _OIDC_CACHE and (now - _OIDC_CACHE_AT) < CACHE_TTL:
        return _OIDC_CACHE

    well_known = f"{authority.rstrip('/')}/.well-known/openid-configuration"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(well_known)
        resp.raise_for_status()
        _OIDC_CACHE.clear()
        _OIDC_CACHE.update(resp.json())
        _OIDC_CACHE_AT = now
        logger.info(f"Refreshed OIDC config from {well_known}")
        return _OIDC_CACHE


def _get_jwks_client(jwks_uri: str) -> PyJWKClient:
    """Return a cached PyJWKClient (refreshes after CACHE_TTL)."""
    global _JWKS_CLIENT, _JWKS_CLIENT_AT

    now = time.time()
    if _JWKS_CLIENT and (now - _JWKS_CLIENT_AT) < CACHE_TTL:
        return _JWKS_CLIENT

    _JWKS_CLIENT = PyJWKClient(jwks_uri, cache_keys=True)
    _JWKS_CLIENT_AT = now
    return _JWKS_CLIENT


# ---------------------------------------------------------------------------
# Decoded claims model
# ---------------------------------------------------------------------------

@dataclass
class AzureTokenClaims:
    """Parsed and validated claims from an Azure AD token."""

    # Standard OIDC claims
    sub: str = ""                          # subject (unique per user+policy)
    oid: str = ""                          # Azure object ID (stable across policies)
    email: str = ""
    name: str = ""
    given_name: str = ""
    family_name: str = ""

    # Multi-tenant claims (custom or extension attributes)
    tenant_id: Optional[str] = None        # mapped internal tenant_id
    roles: List[str] = field(default_factory=list)
    permissions: List[str] = field(default_factory=list)

    # Token metadata
    iss: str = ""
    aud: str = ""
    iat: int = 0
    exp: int = 0
    azp: str = ""                          # authorised party (client_id)

    # Raw claims dict for anything not explicitly mapped
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_jwt(cls, claims: Dict[str, Any]) -> "AzureTokenClaims":
        """Build from a decoded JWT claims dictionary."""
        # Azure B2C can put email in multiple places
        email = (
            claims.get("email")
            or claims.get("emails", [None])[0]  # B2C custom policy
            or claims.get("preferred_username", "")
            or claims.get("upn", "")
        )

        # Roles can come from app roles or custom claims
        roles = claims.get("roles", [])
        if isinstance(roles, str):
            roles = [roles]

        # tenant_id: look in extension attributes, custom claims, then tid
        tenant_id = (
            claims.get("extension_tenant_id")     # B2C extension attribute
            or claims.get("tenant_id")             # custom claim
            or claims.get("tid")                   # Entra ID directory tenant
        )

        return cls(
            sub=claims.get("sub", ""),
            oid=claims.get("oid", ""),
            email=email,
            name=claims.get("name", ""),
            given_name=claims.get("given_name", ""),
            family_name=claims.get("family_name", ""),
            tenant_id=str(tenant_id) if tenant_id else None,
            roles=roles,
            permissions=claims.get("permissions", []),
            iss=claims.get("iss", ""),
            aud=claims.get("aud", ""),
            iat=claims.get("iat", 0),
            exp=claims.get("exp", 0),
            azp=claims.get("azp", ""),
            raw=claims,
        )


# ---------------------------------------------------------------------------
# Token validation
# ---------------------------------------------------------------------------

async def validate_azure_token(token: str) -> AzureTokenClaims:
    """
    Validate an Azure AD B2C / Entra ID access or ID token.

    Steps:
      1. Fetch OIDC discovery doc to get jwks_uri and issuer.
      2. Retrieve the signing key from JWKS.
      3. Decode + verify signature, audience, issuer, and expiry.
      4. Return structured claims.

    Raises HTTPException(401) on any validation failure.
    """
    authority = _get_authority()
    client_ids = _get_client_ids()
    if not authority or not client_ids:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Azure AD not configured (missing tenant/client settings)",
        )

    try:
        oidc = await _fetch_oidc_config(authority)
        jwks_uri = oidc["jwks_uri"]
        issuer = oidc["issuer"]

        # Get signing key for this token
        jwks_client = _get_jwks_client(jwks_uri)
        signing_key = jwks_client.get_signing_key_from_jwt(token)

        # Decode and verify — accept any configured client ID as audience
        logger.info(f"Validating Azure token — client_ids={client_ids}, issuer={issuer}")
        claims = pyjwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=client_ids,  # accept multiple valid audiences
            issuer=issuer,
            options={
                "verify_exp": True,
                "verify_iat": True,
                "verify_aud": True,
                "verify_iss": True,
            },
        )

        parsed = AzureTokenClaims.from_jwt(claims)
        logger.debug(f"Azure token validated: sub={parsed.sub}, email={parsed.email}")
        return parsed

    except pyjwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Azure token expired",
        )
    except pyjwt.InvalidAudienceError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Azure token audience mismatch",
        )
    except pyjwt.InvalidIssuerError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Azure token issuer mismatch",
        )
    except pyjwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid Azure token: {exc}",
        )
    except httpx.HTTPError as exc:
        logger.error(f"Failed to fetch Azure OIDC/JWKS: {exc}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not reach Azure AD for token validation",
        )
    except Exception as exc:
        logger.error(f"Azure token validation failed: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Azure token validation failed",
        )


def is_azure_auth_configured() -> bool:
    """Return True if Azure AD settings are present and non-empty."""
    return bool(_get_authority() and _get_client_ids())
