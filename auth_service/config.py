"""
auth_service.config
-------------------
Authentication configuration — Azure AD (Entra ID) or local mode.

Azure AD setup:
  1. App Registration in your Azure AD tenant
  2. Client secret created
  3. API permissions: User.ReadWrite.All, Group.ReadWrite.All,
     GroupMember.ReadWrite.All (application, with admin consent)
  4. Public client flows enabled (for ROPC login)
"""
import os
from dotenv import load_dotenv

load_dotenv()

# Auth mode: "azure_ad" (production) or "local" (testing without Azure AD)
AUTH_MODE: str = os.getenv("AUTH_MODE", "local")

# Azure AD (Entra ID) configuration
AZURE_AD_TENANT_ID: str = os.getenv("AZURE_AD_TENANT_ID", "")
AZURE_AD_CLIENT_ID: str = os.getenv("AZURE_AD_CLIENT_ID", "")
AZURE_AD_CLIENT_SECRET: str = os.getenv("AZURE_AD_CLIENT_SECRET", "")
AZURE_AD_ONMICROSOFT_DOMAIN: str = os.getenv("AZURE_AD_ONMICROSOFT_DOMAIN", "")

AZURE_AD_AUTHORITY: str = f"https://login.microsoftonline.com/{AZURE_AD_TENANT_ID}" if AZURE_AD_TENANT_ID else ""
AZURE_AD_GRAPH_URL: str = "https://graph.microsoft.com/v1.0"
AZURE_AD_GRAPH_SCOPE: str = "https://graph.microsoft.com/.default"

# JWT configuration (our own tokens — issued after Azure AD authentication)
JWT_SECRET: str = os.getenv("JWT_SECRET", "zeroque-local-dev-secret-do-not-use-in-production")
JWT_ISSUER: str = os.getenv("JWT_ISSUER", "https://api.zeroque.io")
JWT_AUDIENCE: str = os.getenv("JWT_AUDIENCE", "https://api.zeroque.io")
JWT_EXPIRY_SECONDS: int = int(os.getenv("JWT_EXPIRY_SECONDS", "3600"))

# Default org-level roles (created in our Postgres, not in Azure AD)
DEFAULT_ORG_ROLES = {
    "org_admin": "Full tenant administration — manage users, settings, billing",
    "org_manager": "Manage team members, approve orders, view reports",
    "org_member": "Standard user — place orders, view catalog",
    "org_viewer": "Read-only access to tenant data",
}
