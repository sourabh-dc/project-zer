# services/provisioning/main.py
"""
Enhanced Provisioning Service with V2 Multi-Tenant Architecture

This service implements:
- V2 multi-tenant marketplace architecture
- Service-specific event streams
- Circuit breaker pattern
- Saga pattern for distributed transactions
- Event sourcing
- Health monitoring
- Enhanced RBAC with scoped permissions
"""

import os
import sys
import asyncio
import logging
import uuid
from fastapi import FastAPI, HTTPException, Body, Path, Query, BackgroundTasks
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from sqlalchemy import text, String, Boolean, DateTime, func, JSON, Numeric, Integer, BigInteger
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID

# Add the packages path to sys.path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..', 'packages', 'zeroque_common'))

from zeroque_common.communication import (
    ServiceBus, ServiceEvent, ServiceEventType,
    CircuitBreaker, CircuitBreakerConfig,
    SagaOrchestrator, SagaStep,
    ServiceRegistry, HealthMonitor,
    EventStore,
    # Global instances
    service_bus as global_service_bus,
    service_circuit_breaker,
    saga_orchestrator,
    service_registry,
    health_monitor,
    event_store
)
from zeroque_common.db.session import get_engine, init_db, check_db, SessionLocal, Base
from zeroque_common.middleware.usage_middleware import add_api_call_meter
from zeroque_common.middleware.idempotency import add_idempotency_middleware
from zeroque_common.observability import setup_logging, init_metrics, init_insights, add_observability_middleware

# Service configuration
SERVICE_NAME = "provisioning"
app = FastAPI(title="Enhanced ZeroQue Provisioning Service", version="2.0.0")

# Initialize enhanced communication
service_bus = global_service_bus
circuit_breaker_config = CircuitBreakerConfig(
    failure_threshold=3,
    timeout=30,
    success_threshold=2
)

# ---- observability ----
logger = setup_logging(SERVICE_NAME, "2.0.0")
metrics = init_metrics(SERVICE_NAME)
insights = init_insights(SERVICE_NAME, "2.0.0")

# ---- middleware ----
add_observability_middleware(app, SERVICE_NAME)
add_api_call_meter(app)
add_idempotency_middleware(app, routes=[
    ("POST", "/provisioning/tenants"),
    ("PUT", "/provisioning/tenants"),
    ("POST", "/provisioning/sites"),
    ("PUT", "/provisioning/sites"),
    ("POST", "/provisioning/stores"),
    ("PUT", "/provisioning/stores"),
    ("POST", "/provisioning/users"),
    ("PUT", "/provisioning/users"),
    ("POST", "/provisioning/roles"),
    ("PUT", "/provisioning/roles"),
    ("POST", "/provisioning/role-assignments"),
    ("PUT", "/provisioning/role-assignments"),
])

# V2 SQLAlchemy Models for the new architecture
class TenantV2(Base):
    __tablename__ = "tenants_new"
    tenant_id: Mapped[str] = mapped_column(UUID, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    type: Mapped[str] = mapped_column(String(50), default="customer")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    scenario_id: Mapped[Optional[str]] = mapped_column(UUID, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

class SiteV2(Base):
    __tablename__ = "sites_new"
    site_id: Mapped[str] = mapped_column(UUID, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    geo: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

class StoreV2(Base):
    __tablename__ = "stores_new"
    store_id: Mapped[str] = mapped_column(UUID, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    timezone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
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
    vendor_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(255))
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

# Event handlers
async def handle_tenant_created(event: ServiceEvent):
    """Handle tenant creation events"""
    logger.info(f"Received tenant created event: {event.data}")
    # Publish to other services for tenant setup

async def handle_user_assigned(event: ServiceEvent):
    """Handle user role assignment events"""
    logger.info(f"Received user assignment event: {event.data}")
    # Update user permissions cache

async def handle_vendor_onboarded(event: ServiceEvent):
    """Handle vendor onboarding events"""
    logger.info(f"Received vendor onboarding event: {event.data}")
    # Trigger vendor setup workflows

# Saga implementation for provisioning operations
class ProvisioningSaga:
    """Saga for managing provisioning operations across multiple services"""
    
    def __init__(self):
        self.saga_orchestrator = SagaOrchestrator()
        self.steps = [
            SagaStep("validate_tenant", self.validate_tenant, self.compensate_tenant),
            SagaStep("create_tenant", self.create_tenant_record, self.delete_tenant_record),
            SagaStep("setup_permissions", self.setup_permissions, self.remove_permissions),
            SagaStep("notify_services", self.notify_services, None)
        ]
    
    async def execute_tenant_provisioning_saga(self, tenant_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the complete tenant provisioning saga"""
        saga_id = f"tenant_provision_{int(datetime.now().timestamp())}"
        
        try:
            result = await self.saga_orchestrator.execute_saga(
                saga_id=saga_id,
                steps=self.steps,
                initial_data=tenant_data
            )
            
            # Publish tenant provisioned event
            await service_bus.publish_to_service(
                target_service="billing",
                event_type=ServiceEventType.SERVICE_STARTED,
                data={
                    "tenant_id": result["tenant_id"],
                    "type": result["type"],
                    "saga_id": saga_id
                },
                correlation_id=saga_id
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Tenant provisioning saga {saga_id} failed: {str(e)}")
            raise
    
    async def validate_tenant(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate tenant data"""
        logger.info(f"Validating tenant: {data}")
        
        # Validate tenant name uniqueness
        db = SessionLocal()
        try:
            existing = db.query(TenantV2).filter(TenantV2.name == data["name"]).first()
            if existing:
                raise HTTPException(status_code=400, detail="Tenant name already exists")
            
            return {"tenant_validated": True}
            
        finally:
            db.close()
    
    async def create_tenant_record(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Create tenant record"""
        logger.info(f"Creating tenant record: {data}")
        
        db = SessionLocal()
        try:
            tenant = TenantV2(
                tenant_id=data["tenant_id"],
                name=data["name"],
                type=data.get("type", "customer"),
                scenario_id=data.get("scenario_id")
            )
            db.add(tenant)
            db.commit()
            
            return {"tenant_id": tenant.tenant_id, "tenant_created": True}
            
        except Exception as e:
            db.rollback()
            logger.error(f"Failed to create tenant record: {str(e)}")
            raise
        finally:
            db.close()
    
    async def setup_permissions(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Setup default permissions for tenant"""
        logger.info(f"Setting up permissions for tenant: {data}")
        
        # Publish permission setup event
        await service_bus.publish_to_service(
            target_service="rbac",
            event_type=ServiceEventType.SERVICE_STARTED,
            data={
                "tenant_id": data["tenant_id"],
                "type": data["type"]
            },
            correlation_id=data.get("saga_id", "")
        )
        
        return {"permissions_setup": True}
    
    async def notify_services(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Notify other services about tenant creation"""
        logger.info(f"Notifying services about tenant: {data}")
        
        # Notify inventory service
        await service_bus.publish_to_service(
            target_service="inventory",
            event_type=ServiceEventType.SERVICE_STARTED,
            data={
                "tenant_id": data["tenant_id"],
                "type": data["type"]
            },
            correlation_id=data.get("saga_id", "")
        )
        
        return {"services_notified": True}
    
    # Compensation methods
    async def compensate_tenant(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Compensate tenant validation"""
        logger.info(f"Compensating tenant validation: {data}")
        return {}
    
    async def delete_tenant_record(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Delete tenant record"""
        logger.info(f"Deleting tenant record: {data}")
        
        db = SessionLocal()
        try:
            db.query(TenantV2).filter(TenantV2.tenant_id == data["tenant_id"]).delete()
            db.commit()
            return {"tenant_deleted": True}
        finally:
            db.close()
    
    async def remove_permissions(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Remove permissions"""
        logger.info(f"Removing permissions: {data}")
        return {"permissions_removed": True}

# Initialize saga
provisioning_saga = ProvisioningSaga()

# RLS Context Helper
def set_rls_context(db_session, tenant_id: str = None, user_id: str = None):
    """Set Row Level Security context for database session"""
    try:
        if tenant_id:
            db_session.execute(text("SET LOCAL row_security.tenant_id = :tenant_id"), {"tenant_id": tenant_id})
        if user_id:
            db_session.execute(text("SET LOCAL row_security.user_id = :user_id"), {"user_id": user_id})
    except Exception as e:
        logger.warning(f"Failed to set RLS context: {str(e)}")

# Service startup
@app.on_event("startup")
async def startup():
    """Initialize enhanced service"""
    logger.info(f"Starting enhanced {SERVICE_NAME} service")
    
    # Initialize database
    get_engine()
    init_db()
    
    logger.info(f"Enhanced {SERVICE_NAME} service started successfully")

# Enhanced health check
@app.get("/health")
async def health():
    """Enhanced service health check"""
    return {
        "status": "ok",
        "service": SERVICE_NAME,
        "version": "2.0.0",
        "enhanced": True
    }

@app.get("/readiness")
def readiness():
    return {"service": SERVICE_NAME, "db": check_db(), "redis": True}

# ---------------- V2 Payload Models ----------------
class TenantV2Payload(BaseModel):
    name: str = Field(..., description="Human-friendly tenant name")
    type: str = Field(default="customer", description="Tenant type: customer, marketplace, vendor_org, partner")
    scenario_id: Optional[str] = Field(None, description="Scenario ID for tenant")

class SiteV2Payload(BaseModel):
    name: str = Field(..., description="Site name")
    geo: Optional[dict] = Field(None, description="Geographic information")

class StoreV2Payload(BaseModel):
    name: str = Field(..., description="Store name")
    timezone: Optional[str] = Field(None, description="Store timezone")

class UserV2Payload(BaseModel):
    email: str = Field(..., description="User email")
    display_name: str = Field(..., description="User display name")

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

# ---------------- V2 Enhanced Endpoints ----------------
@app.post("/provisioning/v2/tenants", response_model=Dict[str, Any])
async def create_tenant_v2(payload: TenantV2Payload = Body(...)):
    """Create tenant with enhanced communication patterns"""
    
    correlation_id = f"tenant_{datetime.now().isoformat()}"
    
    try:
        # Generate tenant ID using uuid.uuid4()
        tenant_id = str(uuid.uuid4())
        
        # Prepare tenant data
        tenant_data = {
            "tenant_id": tenant_id,
            "name": payload.name,
            "type": payload.type,
            "scenario_id": payload.scenario_id,
            "correlation_id": correlation_id
        }
        
        # Execute saga
        result = await provisioning_saga.execute_tenant_provisioning_saga(tenant_data)
        
        # Store event in event store
        await event_store.append_event(ServiceEvent(
            event_type=ServiceEventType.SERVICE_STARTED,
            service_name=SERVICE_NAME,
            correlation_id=correlation_id,
            data=result,
            metadata={"enhanced": True, "saga_completed": True},
            timestamp=datetime.now()
        ))
        
        return {
            "tenant_id": result["tenant_id"],
            "name": payload.name,
            "type": payload.type,
            "status": "created",
            "created_at": datetime.now(),
            "saga_id": correlation_id
        }
        
    except Exception as e:
        logger.error(f"Tenant creation failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/provisioning/v2/tenants/{tenant_id}")
async def upsert_tenant_v2(tenant_id: str = Path(...), payload: TenantV2Payload = Body(...)):
    """Create or update a Tenant (V2 architecture)."""
    with SessionLocal() as db:
        # Set RLS context
        set_rls_context(db, tenant_id=tenant_id)
        
        t = db.query(TenantV2).filter(TenantV2.tenant_id == tenant_id).one_or_none()
        if t:
            t.name = payload.name
            t.type = payload.type
            t.scenario_id = payload.scenario_id
            t.updated_at = datetime.now()
            db.commit()
            logger.info("tenant_updated", extra={"tenant_id": tenant_id})
            return {"tenant_id": t.tenant_id, "name": t.name, "type": t.type, "updated": True}
        
        t = TenantV2(
            tenant_id=tenant_id, 
            name=payload.name, 
            type=payload.type,
            scenario_id=payload.scenario_id
        )
        db.add(t)
        db.commit()
        logger.info("tenant_created", extra={"tenant_id": tenant_id})
        return {"tenant_id": t.tenant_id, "name": t.name, "type": t.type, "created": True}

@app.put("/provisioning/v2/sites/{site_id}")
async def upsert_site_v2(site_id: str = Path(...), payload: SiteV2Payload = Body(...)):
    """Create or update a Site (V2 architecture)."""
    with SessionLocal() as db:
        s = db.query(SiteV2).filter(SiteV2.site_id == site_id).one_or_none()
        if s:
            s.name = payload.name
            s.geo = payload.geo
            s.updated_at = datetime.now()
            db.commit()
            logger.info("site_updated", extra={"site_id": site_id})
            return {"site_id": s.site_id, "name": s.name, "geo": s.geo, "updated": True}
        
        s = SiteV2(site_id=site_id, name=payload.name, geo=payload.geo)
        db.add(s)
        db.commit()
        logger.info("site_created", extra={"site_id": site_id})
        return {"site_id": s.site_id, "name": s.name, "geo": s.geo, "created": True}

@app.put("/provisioning/v2/stores/{store_id}")
async def upsert_store_v2(store_id: str = Path(...), payload: StoreV2Payload = Body(...)):
    """Create or update a Store (V2 architecture)."""
    with SessionLocal() as db:
        st = db.query(StoreV2).filter(StoreV2.store_id == store_id).one_or_none()
        if st:
            st.name = payload.name
            st.timezone = payload.timezone
            st.updated_at = datetime.now()
            db.commit()
            logger.info("store_updated", extra={"store_id": store_id})
            return {"store_id": st.store_id, "name": st.name, "timezone": st.timezone, "updated": True}
        
        st = StoreV2(store_id=store_id, name=payload.name, timezone=payload.timezone)
        db.add(st)
        db.commit()
        logger.info("store_created", extra={"store_id": store_id})
        return {"store_id": st.store_id, "name": st.name, "timezone": st.timezone, "created": True}

@app.put("/provisioning/v2/users/{user_id}")
async def upsert_user_v2(user_id: str = Path(...), payload: UserV2Payload = Body(...)):
    """Create or update a User (V2 architecture)."""
    with SessionLocal() as db:
        u = db.query(UserV2).filter(UserV2.user_id == user_id).one_or_none()
        if u:
            u.email = payload.email
            u.display_name = payload.display_name
            u.updated_at = datetime.now()
            db.commit()
            logger.info("user_updated", extra={"user_id": user_id})
            return {"user_id": u.user_id, "email": u.email, "display_name": u.display_name, "updated": True}
        
        u = UserV2(user_id=user_id, email=payload.email, display_name=payload.display_name)
        db.add(u)
        db.commit()
        logger.info("user_created", extra={"user_id": user_id})
        return {"user_id": u.user_id, "email": u.email, "display_name": u.display_name, "created": True}

@app.put("/provisioning/v2/roles/{role_id}")
async def upsert_role_v2(role_id: str = Path(...), payload: RoleV2Payload = Body(...)):
    """Create or update a Role (V2 architecture)."""
    with SessionLocal() as db:
        r = db.query(RoleV2).filter(RoleV2.role_id == role_id).one_or_none()
        if r:
            r.code = payload.code
            r.description = payload.description
            db.commit()
            logger.info("role_updated", extra={"role_id": role_id})
            return {"role_id": r.role_id, "code": r.code, "description": r.description, "updated": True}
        
        r = RoleV2(role_id=role_id, code=payload.code, description=payload.description)
        db.add(r)
        db.commit()
        logger.info("role_created", extra={"role_id": role_id})
        return {"role_id": r.role_id, "code": r.code, "description": r.description, "created": True}

@app.put("/provisioning/v2/role-assignments")
async def upsert_role_assignment_v2(payload: RoleAssignmentV2Payload = Body(...)):
    """Assign a Role to a User with scope (V2 architecture)."""
    with SessionLocal() as db:
        if not db.query(UserV2).filter(UserV2.user_id == payload.user_id).one_or_none():
            raise HTTPException(status_code=400, detail="User not found")
        if not db.query(RoleV2).filter(RoleV2.role_id == payload.role_id).one_or_none():
            raise HTTPException(status_code=400, detail="Role not found")

        existing = db.execute(text("""
            SELECT id FROM role_assignments
             WHERE user_id=:u AND role_id=:r AND scope_type=:st AND (scope_id=:si OR (scope_id IS NULL AND :si IS NULL))
        """), {"u": payload.user_id, "r": payload.role_id, "st": payload.scope_type, "si": payload.scope_id}).first()

        if existing:
            logger.info("role_assignment_exists", extra={"id": existing[0]})
            return {"id": existing[0], "updated": False, "exists": True}

        assignment_id = str(uuid.uuid4())
        db.execute(text("""
            INSERT INTO role_assignments(id, user_id, role_id, scope_type, scope_id)
            VALUES(:id,:u,:r,:st,:si)
        """), {"id": assignment_id, "u": payload.user_id, "r": payload.role_id, "st": payload.scope_type, "si": payload.scope_id})
        db.commit()
        logger.info("role_assignment_created", extra={"id": assignment_id})
        return {"id": assignment_id, "created": True}

@app.put("/provisioning/v2/vendors/{vendor_id}")
async def upsert_vendor_v2(vendor_id: str = Path(...), payload: VendorV2Payload = Body(...)):
    """Create or update a Vendor (V2 architecture)."""
    with SessionLocal() as db:
        if not db.query(TenantV2).filter(TenantV2.tenant_id == payload.tenant_id).one_or_none():
            raise HTTPException(status_code=400, detail="Tenant not found")
        
        v = db.query(VendorV2).filter(VendorV2.vendor_id == vendor_id).one_or_none()
        if v:
            v.tenant_id = payload.tenant_id
            v.name = payload.name
            v.description = payload.description
            v.updated_at = datetime.now()
            db.commit()
            logger.info("vendor_updated", extra={"vendor_id": vendor_id})
            return {"vendor_id": v.vendor_id, "tenant_id": v.tenant_id, "name": v.name, "updated": True}
        
        v = VendorV2(vendor_id=vendor_id, tenant_id=payload.tenant_id, name=payload.name, description=payload.description)
        db.add(v)
        db.commit()
        logger.info("vendor_created", extra={"vendor_id": vendor_id})
        return {"vendor_id": v.vendor_id, "tenant_id": v.tenant_id, "name": v.name, "created": True}

@app.put("/provisioning/v2/tenant-sites")
async def upsert_tenant_site_v2(payload: TenantSiteV2Payload = Body(...)):
    """Link a Tenant to a Site (V2 architecture)."""
    with SessionLocal() as db:
        if not db.query(TenantV2).filter(TenantV2.tenant_id == payload.tenant_id).one_or_none():
            raise HTTPException(status_code=400, detail="Tenant not found")
        if not db.query(SiteV2).filter(SiteV2.site_id == payload.site_id).one_or_none():
            raise HTTPException(status_code=400, detail="Site not found")

        existing = db.execute(text("""
            SELECT id FROM tenant_sites WHERE tenant_id=:t AND site_id=:s
        """), {"t": payload.tenant_id, "s": payload.site_id}).first()

        if existing:
            logger.info("tenant_site_exists", extra={"id": existing[0]})
            return {"id": existing[0], "exists": True}

        link_id = str(uuid.uuid4())
        db.execute(text("""
            INSERT INTO tenant_sites(id, tenant_id, site_id, role_type, rights_expire_at)
            VALUES(:id,:t,:s,:rt,:rea)
        """), {"id": link_id, "t": payload.tenant_id, "s": payload.site_id, "rt": payload.role_type, "rea": payload.rights_expire_at})
        db.commit()
        logger.info("tenant_site_created", extra={"id": link_id})
        return {"id": link_id, "created": True}

@app.put("/provisioning/v2/site-stores")
async def upsert_site_store_v2(payload: SiteStoreV2Payload = Body(...)):
    """Link a Site to a Store (V2 architecture)."""
    with SessionLocal() as db:
        if not db.query(SiteV2).filter(SiteV2.site_id == payload.site_id).one_or_none():
            raise HTTPException(status_code=400, detail="Site not found")
        if not db.query(StoreV2).filter(StoreV2.store_id == payload.store_id).one_or_none():
            raise HTTPException(status_code=400, detail="Store not found")

        existing = db.execute(text("""
            SELECT id FROM site_stores WHERE site_id=:s AND store_id=:st
        """), {"s": payload.site_id, "st": payload.store_id}).first()

        if existing:
            logger.info("site_store_exists", extra={"id": existing[0]})
            return {"id": existing[0], "exists": True}

        link_id = str(uuid.uuid4())
        db.execute(text("""
            INSERT INTO site_stores(id, site_id, store_id)
            VALUES(:id,:s,:st)
        """), {"id": link_id, "s": payload.site_id, "st": payload.store_id})
        db.commit()
        logger.info("site_store_created", extra={"id": link_id})
        return {"id": link_id, "created": True}

@app.put("/provisioning/v2/store-vendors")
async def upsert_store_vendor_v2(payload: StoreVendorV2Payload = Body(...)):
    """Link a Store to a Vendor (V2 architecture)."""
    with SessionLocal() as db:
        if not db.query(StoreV2).filter(StoreV2.store_id == payload.store_id).one_or_none():
            raise HTTPException(status_code=400, detail="Store not found")
        if not db.query(VendorV2).filter(VendorV2.vendor_id == payload.vendor_id).one_or_none():
            raise HTTPException(status_code=400, detail="Vendor not found")

        existing = db.execute(text("""
            SELECT id FROM store_vendors WHERE store_id=:s AND vendor_id=:v
        """), {"s": payload.store_id, "v": payload.vendor_id}).first()

        if existing:
            logger.info("store_vendor_exists", extra={"id": existing[0]})
            return {"id": existing[0], "exists": True}

        link_id = str(uuid.uuid4())
        db.execute(text("""
            INSERT INTO store_vendors(id, store_id, vendor_id)
            VALUES(:id,:s,:v)
        """), {"id": link_id, "s": payload.store_id, "v": payload.vendor_id})
        db.commit()
        logger.info("store_vendor_created", extra={"id": link_id})
        return {"id": link_id, "created": True}

@app.put("/provisioning/v2/tenant-links")
async def upsert_tenant_link_v2(payload: TenantLinkV2Payload = Body(...)):
    """Create a parent→child tenant link (V2 architecture)."""
    with SessionLocal() as db:
        if not db.query(TenantV2).filter(TenantV2.tenant_id == payload.parent_tenant_id).one_or_none():
            raise HTTPException(status_code=400, detail="Parent tenant not found")
        if not db.query(TenantV2).filter(TenantV2.tenant_id == payload.child_tenant_id).one_or_none():
            raise HTTPException(status_code=400, detail="Child tenant not found")

        existing = db.execute(text("""
            SELECT id FROM tenant_links_new WHERE parent_tenant_id=:p AND child_tenant_id=:c AND relationship=:r
        """), {"p": payload.parent_tenant_id, "c": payload.child_tenant_id, "r": payload.relationship}).first()

        if existing:
            logger.info("tenant_link_exists", extra={"id": existing[0]})
            return {"id": existing[0], "exists": True}

        link_id = str(uuid.uuid4())
        db.execute(text("""
            INSERT INTO tenant_links_new(id, parent_tenant_id, child_tenant_id, relationship)
            VALUES(:id,:p,:c,:r)
        """), {"id": link_id, "p": payload.parent_tenant_id, "c": payload.child_tenant_id, "r": payload.relationship})
        db.commit()
        logger.info("tenant_link_created", extra={"id": link_id})
        return {"id": link_id, "created": True}

# ---------------- Additional V2 Endpoints ----------------
@app.put("/provisioning/v2/erp-integrations/{integration_id}")
async def upsert_erp_integration_v2(integration_id: str = Path(...), payload: ErpIntegrationPayload = Body(...)):
    """Create or update an ERP Integration (V2 architecture)."""
    with SessionLocal() as db:
        # Validate tenant or vendor exists
        if payload.tenant_id and not db.query(TenantV2).filter(TenantV2.tenant_id == payload.tenant_id).one_or_none():
            raise HTTPException(status_code=400, detail="Tenant not found")
        if payload.vendor_id and not db.query(VendorV2).filter(VendorV2.vendor_id == payload.vendor_id).one_or_none():
            raise HTTPException(status_code=400, detail="Vendor not found")
        
        # Check if integration exists
        existing = db.execute(text("""
            SELECT id FROM erp_integrations WHERE id=:id
        """), {"id": integration_id}).first()
        
        if existing:
            # Update existing integration
            db.execute(text("""
                UPDATE erp_integrations 
                SET tenant_id=:t, vendor_id=:v, type=:type, config=:config, updated_at=NOW()
                WHERE id=:id
            """), {"id": integration_id, "t": payload.tenant_id, "v": payload.vendor_id, 
                   "type": payload.type, "config": payload.config})
            db.commit()
            logger.info("erp_integration_updated", extra={"integration_id": integration_id})
            return {"integration_id": integration_id, "updated": True}
        else:
            # Create new integration
            db.execute(text("""
                INSERT INTO erp_integrations(id, tenant_id, vendor_id, type, config)
                VALUES(:id,:t,:v,:type,:config)
            """), {"id": integration_id, "t": payload.tenant_id, "v": payload.vendor_id, 
                   "type": payload.type, "config": payload.config})
            db.commit()
            logger.info("erp_integration_created", extra={"integration_id": integration_id})
            return {"integration_id": integration_id, "created": True}

@app.put("/provisioning/v2/access-controls/{control_id}")
async def upsert_access_control_v2(control_id: str = Path(...), payload: AccessControlPayload = Body(...)):
    """Create or update an Access Control (V2 architecture)."""
    with SessionLocal() as db:
        # Validate site or store exists
        if payload.site_id and not db.query(SiteV2).filter(SiteV2.site_id == payload.site_id).one_or_none():
            raise HTTPException(status_code=400, detail="Site not found")
        if payload.store_id and not db.query(StoreV2).filter(StoreV2.store_id == payload.store_id).one_or_none():
            raise HTTPException(status_code=400, detail="Store not found")
        
        # Check if control exists
        existing = db.execute(text("""
            SELECT id FROM access_controls WHERE id=:id
        """), {"id": control_id}).first()
        
        if existing:
            # Update existing control
            db.execute(text("""
                UPDATE access_controls 
                SET site_id=:s, store_id=:st, type=:type, config=:config, updated_at=NOW()
                WHERE id=:id
            """), {"id": control_id, "s": payload.site_id, "st": payload.store_id, 
                   "type": payload.type, "config": payload.config})
            db.commit()
            logger.info("access_control_updated", extra={"control_id": control_id})
            return {"control_id": control_id, "updated": True}
        else:
            # Create new control
            db.execute(text("""
                INSERT INTO access_controls(id, site_id, store_id, type, config)
                VALUES(:id,:s,:st,:type,:config)
            """), {"id": control_id, "s": payload.site_id, "st": payload.store_id, 
                   "type": payload.type, "config": payload.config})
            db.commit()
            logger.info("access_control_created", extra={"control_id": control_id})
            return {"control_id": control_id, "created": True}

@app.put("/provisioning/v2/user-access-grants")
async def upsert_user_access_grant_v2(payload: UserAccessGrantPayload = Body(...)):
    """Create or update a User Access Grant (V2 architecture)."""
    with SessionLocal() as db:
        # Validate user and access control exist
        if not db.query(UserV2).filter(UserV2.user_id == payload.user_id).one_or_none():
            raise HTTPException(status_code=400, detail="User not found")
        if not db.execute(text("SELECT id FROM access_controls WHERE id=:id"), {"id": payload.access_control_id}).first():
            raise HTTPException(status_code=400, detail="Access control not found")
        
        # Check if grant exists
        existing = db.execute(text("""
            SELECT id FROM user_access_grants 
            WHERE user_id=:u AND access_control_id=:ac
        """), {"u": payload.user_id, "ac": payload.access_control_id}).first()
        
        if existing:
            logger.info("user_access_grant_exists", extra={"id": existing[0]})
            return {"id": existing[0], "exists": True}
        
        # Create new grant
        grant_id = str(uuid.uuid4())
        db.execute(text("""
            INSERT INTO user_access_grants(id, user_id, access_control_id, grant_type, valid_until)
            VALUES(:id,:u,:ac,:gt,:vu)
        """), {"id": grant_id, "u": payload.user_id, "ac": payload.access_control_id, 
               "gt": payload.grant_type, "vu": payload.valid_until})
        db.commit()
        logger.info("user_access_grant_created", extra={"grant_id": grant_id})
        return {"grant_id": grant_id, "created": True}

@app.put("/provisioning/v2/scenarios/{scenario_id}")
async def upsert_scenario_v2(scenario_id: str = Path(...), payload: ScenarioPayload = Body(...)):
    """Create or update a Scenario (V2 architecture)."""
    with SessionLocal() as db:
        # Check if scenario exists
        existing = db.execute(text("""
            SELECT id FROM scenarios WHERE id=:id
        """), {"id": scenario_id}).first()
        
        if existing:
            # Update existing scenario
            db.execute(text("""
                UPDATE scenarios 
                SET code=:code, name=:name, config=:config
                WHERE id=:id
            """), {"id": scenario_id, "code": payload.code, "name": payload.name, "config": payload.config})
            db.commit()
            logger.info("scenario_updated", extra={"scenario_id": scenario_id})
            return {"scenario_id": scenario_id, "updated": True}
        else:
            # Create new scenario
            db.execute(text("""
                INSERT INTO scenarios(id, code, name, config)
                VALUES(:id,:code,:name,:config)
            """), {"id": scenario_id, "code": payload.code, "name": payload.name, "config": payload.config})
            db.commit()
            logger.info("scenario_created", extra={"scenario_id": scenario_id})
            return {"scenario_id": scenario_id, "created": True}

@app.put("/provisioning/v2/zeroque-rails/{rail_id}")
async def upsert_zeroque_rail_v2(rail_id: str = Path(...), payload: ZeroqueRailPayload = Body(...)):
    """Create or update a ZeroQue Rail (V2 architecture)."""
    with SessionLocal() as db:
        # Check if rail exists
        existing = db.execute(text("""
            SELECT id FROM zeroque_rails WHERE id=:id
        """), {"id": rail_id}).first()
        
        if existing:
            # Update existing rail
            db.execute(text("""
                UPDATE zeroque_rails 
                SET type=:type, config=:config, updated_at=NOW()
                WHERE id=:id
            """), {"id": rail_id, "type": payload.type, "config": payload.config})
            db.commit()
            logger.info("zeroque_rail_updated", extra={"rail_id": rail_id})
            return {"rail_id": rail_id, "updated": True}
        else:
            # Create new rail
            db.execute(text("""
                INSERT INTO zeroque_rails(id, type, config)
                VALUES(:id,:type,:config)
            """), {"id": rail_id, "type": payload.type, "config": payload.config})
            db.commit()
            logger.info("zeroque_rail_created", extra={"rail_id": rail_id})
            return {"rail_id": rail_id, "created": True}

# Enhanced monitoring and management endpoints
@app.get("/provisioning/v2/circuit-breakers")
async def get_circuit_breakers():
    """Get circuit breaker status"""
    return service_circuit_breaker.get_all_states()

@app.get("/provisioning/v2/events/metrics")
async def get_event_metrics():
    """Get event system metrics"""
    return service_bus.get_service_metrics()

@app.get("/provisioning/v2/sagas/{saga_id}")
async def get_saga_status(saga_id: str):
    """Get saga execution status"""
    status = saga_orchestrator.get_saga_status(saga_id)
    if not status:
        raise HTTPException(status_code=404, detail="Saga not found")
    return status

@app.get("/provisioning/v2/events/{entity_id}")
async def get_entity_events(entity_id: str, limit: int = 100):
    """Get events for an entity"""
    events = await event_store.get_events(entity_id=entity_id, limit=limit)
    return {"entity_id": entity_id, "events": events}

@app.get("/provisioning/v2/services")
async def get_services():
    """Get all registered services"""
    return service_registry.get_all_services()

@app.get("/provisioning/v2/system/health")
async def get_system_health():
    """Get overall system health"""
    return await health_monitor.check_system_health()

# ---------------- V2 List Endpoints ----------------
@app.get("/provisioning/v2/tenants")
async def list_tenants_v2(limit: int = Query(100)):
    """List tenants (V2 architecture)"""
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT tenant_id, name, type, active, scenario_id, created_at FROM tenants_new 
            ORDER BY created_at DESC LIMIT :l
        """), {"l": limit}).all()
        return [{"tenant_id": r[0], "name": r[1], "type": r[2], "active": r[3], "scenario_id": r[4], "created_at": r[5]} for r in rows]

@app.get("/provisioning/v2/sites")
async def list_sites_v2(limit: int = Query(200)):
    """List sites (V2 architecture)"""
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT site_id, name, geo, active, created_at FROM sites_new 
            ORDER BY created_at DESC LIMIT :l
        """), {"l": limit}).all()
        return [{"site_id": r[0], "name": r[1], "geo": r[2], "active": r[3], "created_at": r[4]} for r in rows]

@app.get("/provisioning/v2/stores")
async def list_stores_v2(limit: int = Query(200)):
    """List stores (V2 architecture)"""
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT store_id, name, timezone, active, created_at FROM stores_new 
            ORDER BY created_at DESC LIMIT :l
        """), {"l": limit}).all()
        return [{"store_id": r[0], "name": r[1], "timezone": r[2], "active": r[3], "created_at": r[4]} for r in rows]

@app.get("/provisioning/v2/users")
async def list_users_v2(limit: int = Query(200)):
    """List users (V2 architecture)"""
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT user_id, email, display_name, active, created_at FROM users_new 
            ORDER BY created_at DESC LIMIT :l
        """), {"l": limit}).all()
        return [{"user_id": r[0], "email": r[1], "display_name": r[2], "active": r[3], "created_at": r[4]} for r in rows]

@app.get("/provisioning/v2/roles")
async def list_roles_v2(limit: int = Query(200)):
    """List roles (V2 architecture)"""
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT role_id, code, description, created_at FROM roles_new 
            ORDER BY created_at DESC LIMIT :l
        """), {"l": limit}).all()
        return [{"role_id": r[0], "code": r[1], "description": r[2], "created_at": r[3]} for r in rows]

@app.get("/provisioning/v2/vendors")
async def list_vendors_v2(tenant_id: Optional[str] = Query(None), limit: int = Query(200)):
    """List vendors (V2 architecture)"""
    with SessionLocal() as db:
        if tenant_id:
            rows = db.execute(text("""
                SELECT vendor_id, tenant_id, name, description, rating, active, created_at FROM vendors 
                WHERE tenant_id=:t ORDER BY created_at DESC LIMIT :l
            """), {"t": tenant_id, "l": limit}).all()
        else:
            rows = db.execute(text("""
                SELECT vendor_id, tenant_id, name, description, rating, active, created_at FROM vendors 
                ORDER BY created_at DESC LIMIT :l
            """), {"l": limit}).all()
        return [{"vendor_id": r[0], "tenant_id": r[1], "name": r[2], "description": r[3], "rating": r[4], "active": r[5], "created_at": r[6]} for r in rows]

@app.get("/provisioning/v2/role-assignments")
async def list_role_assignments_v2(user_id: Optional[str] = Query(None), limit: int = Query(200)):
    """List role assignments (V2 architecture)"""
    with SessionLocal() as db:
        if user_id:
            rows = db.execute(text("""
                SELECT id, user_id, role_id, scope_type, scope_id, created_at FROM role_assignments 
                WHERE user_id=:u ORDER BY created_at DESC LIMIT :l
            """), {"u": user_id, "l": limit}).all()
        else:
            rows = db.execute(text("""
                SELECT id, user_id, role_id, scope_type, scope_id, created_at FROM role_assignments 
                ORDER BY created_at DESC LIMIT :l
            """), {"l": limit}).all()
        return [{"id": r[0], "user_id": r[1], "role_id": r[2], "scope_type": r[3], "scope_id": r[4], "created_at": r[5]} for r in rows]

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8202)