# =============================================================================
# PYDANTIC MODELS
# =============================================================================
from typing import Optional, List, Dict, Any

from pydantic import BaseModel, Field


class UserCreateRequest(BaseModel):
    tenant_id: str
    email: str
    name: Optional[str] = None
    primary_cost_centre_id: Optional[str] = None
    role_ids: List[str] = Field(default=[], description="List of role IDs to assign")
    user_metadata: Optional[Dict[str, Any]] = None

class UserUpdateRequest(BaseModel):
    name: Optional[str] = None
    primary_cost_centre_id: Optional[str] = None
    user_metadata: Optional[Dict[str, Any]] = None

class RoleCreateRequest(BaseModel):
    tenant_id: str
    name: str
    description: Optional[str] = None
    permissions: List[str] = Field(description="List of permission strings")

class RoleUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    permissions: Optional[List[str]] = None

class RoleAssignmentRequest(BaseModel):
    tenant_id: str
    user_id: str
    role_id: str

class TokenRequest(BaseModel):
    tenant_id: str
    token_type: str = Field(description="'guest' or 'loyalty'")
    user_id: Optional[str] = Field(default=None, description="Required for loyalty tokens")
    guest_info: Optional[Dict[str, Any]] = Field(default=None, description="Guest-specific information")

class OAuthProviderCreateRequest(BaseModel):
    """Create OAuth provider configuration - Pro/Enterprise feature"""
    tenant_id: str
    provider_type: str = Field(description="'azure_ad', 'google', 'okta', 'auth0'")
    provider_name: str = Field(description="Display name for the provider")
    client_id: str
    client_secret: str
    tenant_domain: Optional[str] = None  # For Azure AD
    discovery_url: Optional[str] = None  # OIDC discovery endpoint
    scopes: List[str] = ['openid', 'profile', 'email']
    config_metadata: Optional[Dict[str, Any]] = None

class OAuthProviderUpdateRequest(BaseModel):
    provider_name: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    tenant_domain: Optional[str] = None
    discovery_url: Optional[str] = None
    scopes: Optional[List[str]] = None
    enabled: Optional[bool] = None
    config_metadata: Optional[Dict[str, Any]] = None

class OAuthInitiateRequest(BaseModel):
    """Initiate OAuth/SSO flow"""
    tenant_id: str
    provider_id: str
    redirect_uri: str = Field(description="Where to redirect after auth")

class OAuthCallbackRequest(BaseModel):
    """OAuth callback payload"""
    state: str
    code: str
    error: Optional[str] = None
    error_description: Optional[str] = None

class ReportRequest(BaseModel):
    tenant_id: str
    report_type: str = Field(description="'users', 'roles', 'active_users', 'role_counts'")
    period_start: Optional[str] = Field(default=None, description="ISO date string")
    period_end: Optional[str] = Field(default=None, description="ISO date string")
    filters: Optional[Dict[str, Any]] = Field(default=None, description="Additional filters")

class UserResponse(BaseModel):
    id: str
    tenant_id: str
    email: str
    name: Optional[str]
    primary_cost_centre_id: Optional[str]
    metadata: Optional[Dict[str, Any]]
    created_at: str
    updated_at: Optional[str]
    roles: List[Dict[str, Any]] = Field(default=[], description="Assigned roles")

class RoleResponse(BaseModel):
    id: str
    tenant_id: str
    name: str
    description: Optional[str]
    permissions: List[str]
    created_at: str
    updated_at: Optional[str]
    user_count: int = Field(default=0, description="Number of users with this role")

class TokenResponse(BaseModel):
    token: str
    token_type: str
    expires_at: str
    user_id: Optional[str] = None
    permissions: List[str] = Field(default=[])

class ReportResponse(BaseModel):
    report_type: str
    tenant_id: str
    generated_at: str
    period: Optional[Dict[str, str]]
    summary: Dict[str, Any]
    data: List[Dict[str, Any]]