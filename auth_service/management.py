"""
auth_service.management
-----------------------
Microsoft Graph API client for Azure AD (Entra ID) user and group management.

Replaces Auth0 Management API. Uses client_credentials flow for backend operations.

Key mappings from Auth0 → Azure AD:
  Auth0 Organization  →  Azure AD Security Group
  Auth0 User          →  Azure AD User (with UPN on onmicrosoft.com domain)
  Auth0 Role          →  Stored in our Postgres (not Azure AD app roles)
"""
import logging
import re
import time
import uuid
from typing import Any, Dict, List, Optional

import httpx

from auth_service.config import (
    AZURE_AD_TENANT_ID, AZURE_AD_CLIENT_ID, AZURE_AD_CLIENT_SECRET,
    AZURE_AD_AUTHORITY, AZURE_AD_GRAPH_URL, AZURE_AD_GRAPH_SCOPE,
    AZURE_AD_ONMICROSOFT_DOMAIN,
)

logger = logging.getLogger("auth_service.management")

_graph_token: Optional[str] = None
_graph_token_expires: float = 0


async def _get_graph_token() -> str:
    """Get a client_credentials access token for Microsoft Graph API."""
    global _graph_token, _graph_token_expires

    if _graph_token and time.time() < _graph_token_expires - 60:
        return _graph_token

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{AZURE_AD_AUTHORITY}/oauth2/v2.0/token",
            data={
                "grant_type": "client_credentials",
                "client_id": AZURE_AD_CLIENT_ID,
                "client_secret": AZURE_AD_CLIENT_SECRET,
                "scope": AZURE_AD_GRAPH_SCOPE,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        _graph_token = data["access_token"]
        _graph_token_expires = time.time() + data.get("expires_in", 3600)
        logger.info("Graph API token refreshed")
        return _graph_token


async def _graph_request(method: str, path: str, **kwargs) -> Dict[str, Any]:
    """Make an authenticated request to Microsoft Graph API."""
    token = await _get_graph_token()
    url = f"{AZURE_AD_GRAPH_URL}{path}"

    async with httpx.AsyncClient() as client:
        resp = await client.request(
            method, url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            **kwargs,
        )
        if resp.status_code >= 400:
            logger.error(f"Graph API error: {resp.status_code} {resp.text[:500]}")
            resp.raise_for_status()
        if resp.status_code == 204:
            return {}
        return resp.json() if resp.text else {}


# ── Organization (Azure AD Group) ─────────────────────────────────────

async def create_organization(
    name: str,
    display_name: str,
    *,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Create an Azure AD Security Group to represent a SaaS tenant.

    Returns dict with 'id' (group object ID) and 'displayName'.
    """
    slug = re.sub(r"[^a-z0-9-]", "-", name.lower().strip())[:50]
    mail_nickname = f"zer-{slug}"[:60]

    group = await _graph_request("POST", "/groups", json={
        "displayName": f"ZeroQue: {display_name}",
        "description": display_name,
        "mailEnabled": False,
        "mailNickname": mail_nickname,
        "securityEnabled": True,
        "groupTypes": [],
    })
    logger.info(f"Created Azure AD group: {group.get('id')} ({display_name})")
    return group


async def get_organization(org_id: str) -> Dict[str, Any]:
    return await _graph_request("GET", f"/groups/{org_id}")


async def list_organizations() -> List[Dict[str, Any]]:
    result = await _graph_request(
        "GET", "/groups",
        params={"$filter": "startswith(mailNickname,'zer-')", "$top": "100"},
    )
    return result.get("value", [])


# ── User Management ───────────────────────────────────────────────────

async def create_user(
    email: str,
    password: str,
    name: str,
) -> Dict[str, Any]:
    """Create an Azure AD user for the SaaS platform.

    UPN is auto-generated on the onmicrosoft.com domain.
    The user's actual email is stored in the 'mail' attribute.
    """
    mail_nick = re.sub(r"[^a-z0-9.-]", "", email.split("@")[0].lower())
    unique_suffix = uuid.uuid4().hex[:6]
    upn = f"zer-{mail_nick}-{unique_suffix}@{AZURE_AD_ONMICROSOFT_DOMAIN}"

    user = await _graph_request("POST", "/users", json={
        "accountEnabled": True,
        "displayName": name,
        "mailNickname": f"zer-{mail_nick}-{unique_suffix}",
        "userPrincipalName": upn,
        "mail": email,
        "passwordProfile": {
            "forceChangePasswordNextSignIn": False,
            "password": password,
        },
        "usageLocation": "GB",
    })
    logger.info(f"Created Azure AD user: {user.get('id')} ({email}) UPN={upn}")
    return user


async def get_user(user_id: str) -> Dict[str, Any]:
    return await _graph_request("GET", f"/users/{user_id}")


async def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    """Find a user by their actual email (stored in 'mail' attribute)."""
    result = await _graph_request(
        "GET", "/users",
        params={"$filter": f"mail eq '{email}'", "$select": "id,displayName,mail,userPrincipalName"},
    )
    users = result.get("value", [])
    return users[0] if users else None


# ── Group Membership ──────────────────────────────────────────────────

async def add_member(org_id: str, user_id: str) -> None:
    """Add a user to an Azure AD group (organization membership)."""
    await _graph_request(
        "POST", f"/groups/{org_id}/members/$ref",
        json={"@odata.id": f"https://graph.microsoft.com/v1.0/directoryObjects/{user_id}"},
    )
    logger.info(f"Added member {user_id} to group {org_id}")


async def remove_member(org_id: str, user_id: str) -> None:
    await _graph_request("DELETE", f"/groups/{org_id}/members/{user_id}/$ref")
    logger.info(f"Removed member {user_id} from group {org_id}")


async def list_members(org_id: str) -> List[Dict[str, Any]]:
    result = await _graph_request(
        "GET", f"/groups/{org_id}/members",
        params={"$select": "id,displayName,mail,userPrincipalName"},
    )
    return result.get("value", [])


async def get_user_groups(user_id: str) -> List[Dict[str, Any]]:
    """Get groups a user belongs to (filtered to ZeroQue groups)."""
    result = await _graph_request(
        "GET", f"/users/{user_id}/memberOf",
        params={"$select": "id,displayName,mailNickname"},
    )
    groups = result.get("value", [])
    return [g for g in groups if g.get("mailNickname", "").startswith("zer-")]


# ── Authentication (ROPC) ─────────────────────────────────────────────

async def authenticate_user(email: str, password: str) -> Dict[str, Any]:
    """Authenticate a user via ROPC (Resource Owner Password Credentials).

    1. Find user by email → get UPN
    2. Authenticate with Azure AD using UPN + password
    3. Return user info on success

    Raises httpx.HTTPStatusError on failure.
    """
    user = await get_user_by_email(email)
    if not user:
        raise ValueError(f"User not found: {email}")

    upn = user["userPrincipalName"]

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{AZURE_AD_AUTHORITY}/oauth2/v2.0/token",
            data={
                "grant_type": "password",
                "client_id": AZURE_AD_CLIENT_ID,
                "client_secret": AZURE_AD_CLIENT_SECRET,
                "username": upn,
                "password": password,
                "scope": "openid profile email",
            },
        )
        if resp.status_code != 200:
            error_data = resp.json()
            error_desc = error_data.get("error_description", "Authentication failed")
            raise ValueError(f"Authentication failed: {error_desc.split('.')[0]}")

    return user


# ── Password Management ───────────────────────────────────────────────

async def reset_password(user_id: str, new_password: str) -> None:
    """Reset a user's password (admin action)."""
    await _graph_request("PATCH", f"/users/{user_id}", json={
        "passwordProfile": {
            "forceChangePasswordNextSignIn": False,
            "password": new_password,
        },
    })
    logger.info(f"Password reset for user {user_id}")


async def disable_user(user_id: str) -> None:
    await _graph_request("PATCH", f"/users/{user_id}", json={"accountEnabled": False})
    logger.info(f"Disabled user {user_id}")


async def enable_user(user_id: str) -> None:
    await _graph_request("PATCH", f"/users/{user_id}", json={"accountEnabled": True})
    logger.info(f"Enabled user {user_id}")


async def delete_user(user_id: str) -> None:
    await _graph_request("DELETE", f"/users/{user_id}")
    logger.info(f"Deleted user {user_id}")
