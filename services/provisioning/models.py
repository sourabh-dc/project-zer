# services/provisioning/models.py
"""
ORM Models for Provisioning Service

This module contains all the ORM models for the provisioning service
to avoid circular imports.
"""

from typing import Optional
from datetime import datetime
from sqlalchemy import String, Boolean, DateTime, func, JSON, Numeric, Integer, BigInteger, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID

from zeroque_common.db.session import Base

class TenantV2(Base):
    __tablename__ = "tenants_new"
    tenant_id: Mapped[str] = mapped_column(UUID, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    type: Mapped[str] = mapped_column(String(50), default="customer")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    scenario_id: Mapped[Optional[str]] = mapped_column(UUID, nullable=True)

class SiteV2(Base):
    __tablename__ = "sites_new"
    site_id: Mapped[str] = mapped_column(UUID, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(UUID, ForeignKey("tenants_new.tenant_id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    site_type: Mapped[str] = mapped_column(String(50), default="retail")
    geo: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

class StoreV2(Base):
    __tablename__ = "stores_new"
    store_id: Mapped[str] = mapped_column(UUID, primary_key=True)
    site_id: Mapped[str] = mapped_column(UUID, ForeignKey("sites_new.site_id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    store_type: Mapped[str] = mapped_column(String(50), default="cashierless")
    geo: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

class UserV2(Base):
    __tablename__ = "users_new"
    user_id: Mapped[str] = mapped_column(UUID, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    display_name: Mapped[str] = mapped_column(String(200))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

class RoleV2(Base):
    __tablename__ = "roles_new"
    role_id: Mapped[str] = mapped_column(UUID, primary_key=True)
    code: Mapped[str] = mapped_column(String(100), unique=True)
    description: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class PermissionV2(Base):
    __tablename__ = "permissions_new"
    permission_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    code: Mapped[str] = mapped_column(String(100), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class RolePermissionV2(Base):
    __tablename__ = "role_permissions_new"
    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    role_id: Mapped[str] = mapped_column(String(255))
    permission_id: Mapped[str] = mapped_column(String(255))
    granted: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class RoleAssignmentV2(Base):
    __tablename__ = "role_assignments"
    id: Mapped[str] = mapped_column(UUID, primary_key=True)
    user_id: Mapped[str] = mapped_column(UUID)
    role_id: Mapped[str] = mapped_column(UUID)
    scope_type: Mapped[str] = mapped_column(String(50), default="GLOBAL")
    scope_id: Mapped[Optional[str]] = mapped_column(UUID, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class PermissionGrantV2(Base):
    __tablename__ = "permission_grants"
    grant_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    grantee_type: Mapped[str] = mapped_column(String(50))
    grantee_id: Mapped[str] = mapped_column(String(255))
    permission_id: Mapped[str] = mapped_column(String(255))
    scope_type: Mapped[str] = mapped_column(String(50))
    scope_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=1000)
    is_granted: Mapped[bool] = mapped_column(Boolean, default=True)
    granted_by: Mapped[str] = mapped_column(String(255))
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class VendorV2(Base):
    __tablename__ = "vendors"
    vendor_id: Mapped[str] = mapped_column(UUID, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(UUID)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    rating: Mapped[Optional[float]] = mapped_column(Numeric(3, 2), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

class VendorOnboardingV2(Base):
    __tablename__ = "vendor_onboarding"
    onboarding_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    vendor_id: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(50), default="pending")
    requirements: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    approver_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

class TenantSiteV2(Base):
    __tablename__ = "tenant_sites"
    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(255))
    site_id: Mapped[str] = mapped_column(String(255))
    role_type: Mapped[str] = mapped_column(String(50), default="manager")
    rights_expire_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class SiteStoreV2(Base):
    __tablename__ = "site_stores"
    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    site_id: Mapped[str] = mapped_column(String(255))
    store_id: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class TenantStoreAdminV2(Base):
    __tablename__ = "tenant_store_admins"
    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(255))
    store_id: Mapped[str] = mapped_column(String(255))
    role_code: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class StoreVendorV2(Base):
    __tablename__ = "store_vendors"
    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    store_id: Mapped[str] = mapped_column(String(255))
    vendor_id: Mapped[str] = mapped_column(String(255))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

class TenantLinkV2(Base):
    __tablename__ = "tenant_links_new"
    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    parent_tenant_id: Mapped[str] = mapped_column(String(255))
    child_tenant_id: Mapped[str] = mapped_column(String(255))
    relationship: Mapped[str] = mapped_column(String(50), default="distributor")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class ScenarioV2(Base):
    """Scenario definitions for different use cases"""
    __tablename__ = "scenarios"
    
    id: Mapped[str] = mapped_column(UUID, primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    config: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class ErpIntegrationV2(Base):
    """ERP/CRM integration configurations"""
    __tablename__ = "erp_integrations"
    
    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    tenant_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    vendor_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    type: Mapped[str] = mapped_column(String(20))
    config: Mapped[dict] = mapped_column(JSON)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_sync_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

class AccessControlV2(Base):
    """Access control device configurations"""
    __tablename__ = "access_controls"
    
    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    site_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    store_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    type: Mapped[str] = mapped_column(String(20))
    config: Mapped[dict] = mapped_column(JSON)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

class UserAccessGrantV2(Base):
    """User access grants for devices"""
    __tablename__ = "user_access_grants"
    
    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(255))
    access_control_id: Mapped[str] = mapped_column(String(255))
    grant_type: Mapped[str] = mapped_column(String(20), default="permanent")
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    valid_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class PermissionResolutionCacheV2(Base):
    """Permission resolution cache for performance"""
    __tablename__ = "permission_resolution_cache"
    
    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(255))
    permission_id: Mapped[str] = mapped_column(String(255))
    scope_type: Mapped[str] = mapped_column(String(50))
    scope_id: Mapped[str] = mapped_column(String(255))
    is_granted: Mapped[bool] = mapped_column(Boolean)
    resolution_path: Mapped[dict] = mapped_column(JSON)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
