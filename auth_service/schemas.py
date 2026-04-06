"""
auth_service.schemas
--------------------
Pydantic models for auth requests, responses, and user context.
"""
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# ── Request Schemas ───────────────────────────────────────────────────

class LoginRequest(BaseModel):
    """Authenticate with email + password. Works in both azure_ad and local mode."""
    email: str
    password: str
    org_id: Optional[str] = None

class ForgotPasswordRequest(BaseModel):
    email: str

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=8, max_length=128)

class InviteUserRequest(BaseModel):
    email: str = Field(..., min_length=5)
    name: str = Field(..., min_length=2)
    roles: List[str] = Field(default=["org_member"])


# ── Response Schemas ──────────────────────────────────────────────────

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int
    org_id: Optional[str] = None
    user_id: Optional[str] = None


class UserContext(BaseModel):
    """Extracted from a validated JWT — available in every API request."""
    user_id: str
    email: Optional[str] = None
    org_id: Optional[str] = None
    tenant_id: Optional[str] = None
    roles: List[str] = []
    permissions: List[str] = []
    is_authenticated: bool = True

    @property
    def is_admin(self) -> bool:
        return "org_admin" in self.roles

    @property
    def is_manager(self) -> bool:
        return "org_admin" in self.roles or "org_manager" in self.roles


class OrgMember(BaseModel):
    user_id: str
    email: Optional[str] = None
    name: Optional[str] = None
    roles: List[str] = []


class OrgInfo(BaseModel):
    org_id: str
    name: str
    display_name: Optional[str] = None
    member_count: int = 0
    metadata: Optional[Dict[str, Any]] = None
