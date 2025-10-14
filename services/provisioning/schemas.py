from typing import Optional, List, Dict, Any
from pydantic import BaseModel

# Payloads
class TenantRequest(BaseModel):
    name: str
    tenant_type: str = "customer"

    def __init__(self, **data):
        super().__init__(**data)
        if not self.name or not self.name.strip():
            raise ValueError("Tenant name cannot be empty")


class SiteRequest(BaseModel):
    name: str
    site_type: str = "office"
    geo: Optional[Dict] = None
    device_metadata: Optional[Dict] = None  # Phase 2: Site Registry - device tracking


class StoreRequest(BaseModel):
    name: str
    store_type: str = "retail"
    geo: Optional[Dict] = None


class UserRequest(BaseModel):
    email: str
    display_name: str
    tenant_id: str
    generate_api_key: bool = False
    permissions: Optional[List[str]] = None


class BulkUserRequest(BaseModel):
    """Bulk user import for self-service provisioning (Pro/Ent feature)"""
    tenant_id: str
    users: List[Dict[str, Any]]  # [{"email": "...", "display_name": "...", "permissions": [...]}, ...]
    notify_users: bool = True
    auto_generate_api_keys: bool = False


class RoleRequest(BaseModel):
    code: str
    name: Optional[str] = None
    description: Optional[str] = None


class VendorRequest(BaseModel):
    tenant_id: str
    name: str
    contact_email: Optional[str] = None
    description: Optional[str] = None


class CostCentreRequest(BaseModel):
    tenant_id: str
    name: str
    budget_minor: int = 0