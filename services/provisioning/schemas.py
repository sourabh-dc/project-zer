from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
# ---------------- V2 Payload Models ----------------
class TenantV2Payload(BaseModel):
    name: str = Field(..., description="Human-friendly tenant name")
    type: str = Field(default="customer", description="Tenant type: customer, marketplace, vendor_org, partner, end_user, retailer, distributor")
    scenario_id: Optional[str] = Field(None, description="Scenario ID for tenant")

class SiteV2Payload(BaseModel):
    name: str = Field(..., description="Site name")
    site_type: str = Field(default="retail", description="Site type: onsite, retail, distributor")
    geo: Optional[dict] = Field(None, description="Geographic information")

class StoreV2Payload(BaseModel):
    name: str = Field(..., description="Store name")
    store_type: str = Field(default="cashierless", description="Store type: cashierless, vending, kiosk, traditional, custom")
    geo: Optional[dict] = Field(None, description="Geographic information")
    timezone: Optional[str] = Field(None, description="Store timezone")

class UserV2Payload(BaseModel):
    email: str = Field(..., description="User email")
    display_name: str = Field(..., description="User display name")
    active: bool = Field(default=True, description="User active status")

class RoleV2Payload(BaseModel):
    code: str = Field(..., description="Role code")
    description: str = Field(default="", description="Role description")

class PermissionV2Payload(BaseModel):
    code: str = Field(..., description="Permission code")
    name: str = Field(..., description="Permission name")
    description: Optional[str] = Field(None, description="Permission description")
    category: Optional[str] = Field(None, description="Permission category")

class RoleAssignmentV2Payload(BaseModel):
    user_id: str = Field(..., description="User ID")
    role_id: str = Field(..., description="Role ID")
    scope_type: str = Field(default="GLOBAL", description="Scope type: GLOBAL, TENANT, SITE, STORE")
    scope_id: Optional[str] = Field(None, description="Scope ID")

class VendorV2Payload(BaseModel):
    tenant_id: str = Field(..., description="Tenant ID")
    name: str = Field(..., description="Vendor name")
    description: Optional[str] = Field(None, description="Vendor description")
    rating: Optional[float] = Field(None, description="Vendor rating (0-5)")

class TenantSiteV2Payload(BaseModel):
    tenant_id: str = Field(..., description="Tenant ID")
    site_id: str = Field(..., description="Site ID")
    role_type: str = Field(default="manager", description="Role type")
    rights_expire_at: Optional[datetime] = Field(None, description="Rights expiration")

class SiteStoreV2Payload(BaseModel):
    site_id: str = Field(..., description="Site ID")
    store_id: str = Field(..., description="Store ID")

class StoreVendorV2Payload(BaseModel):
    store_id: str = Field(..., description="Store ID")
    vendor_id: str = Field(..., description="Vendor ID")

class TenantLinkV2Payload(BaseModel):
    parent_tenant_id: str = Field(..., description="Parent tenant ID")
    child_tenant_id: str = Field(..., description="Child tenant ID")
    relationship: str = Field(default="distributor", description="Relationship type")

class ErpIntegrationPayload(BaseModel):
    tenant_id: Optional[str] = Field(None, description="Tenant ID")
    vendor_id: Optional[str] = Field(None, description="Vendor ID")
    type: str = Field(..., description="Integration type: ERP or CRM")
    config: dict = Field(..., description="Integration configuration")

class AccessControlPayload(BaseModel):
    site_id: Optional[str] = Field(None, description="Site ID")
    store_id: Optional[str] = Field(None, description="Store ID")
    type: str = Field(..., description="Access control type: gate, RFID, lock, card_reader")
    config: dict = Field(..., description="Access control configuration")

class UserAccessGrantPayload(BaseModel):
    user_id: str = Field(..., description="User ID")
    access_control_id: str = Field(..., description="Access control ID")
    grant_type: str = Field(default="permanent", description="Grant type: permanent or temporary")
    valid_until: Optional[datetime] = Field(None, description="Grant expiration")

class ScenarioPayload(BaseModel):
    code: str = Field(..., description="Scenario code")
    name: str = Field(..., description="Scenario name")
    config: Optional[dict] = Field(None, description="Scenario configuration")

class ZeroqueRailPayload(BaseModel):
    type: str = Field(..., description="Rail type: payments, cv, marketplace")
    config: dict = Field(..., description="Rail configuration")