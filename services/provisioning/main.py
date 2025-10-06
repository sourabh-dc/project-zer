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
import time
from fastapi import FastAPI, HTTPException, Body, Path, Query, BackgroundTasks, Depends
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from sqlalchemy import text, String, Boolean, DateTime, func, JSON, Numeric, Integer, BigInteger, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship, Session
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

# Import service layer and repositories
from .services import ServiceFactory
from .repositories import RepositoryFactory, ProvisioningError, ValidationError, NotFoundError, DuplicateError
from .models import *

# Service configuration
SERVICE_NAME = "provisioning"
app = FastAPI(title="Enhanced ZeroQue Provisioning Service", version="2.0.0")

# Dependency injection for database sessions
def get_db() -> Session:
    """Get database session with proper lifecycle management"""
    db = SessionLocal()
    try:
        yield db
    except Exception as e:
        db.rollback()
        logger.error(f"Database session error: {e}")
        raise e
    finally:
        try:
            db.close()
        except Exception as e:
            logger.error(f"Error closing database session: {e}")

# Custom exception handlers
@app.exception_handler(ValidationError)
async def validation_exception_handler(request, exc: ValidationError):
    """Handle validation errors"""
    logger.warning(f"Validation error: {exc}")
    return HTTPException(status_code=400, detail=str(exc))

@app.exception_handler(NotFoundError)
async def not_found_exception_handler(request, exc: NotFoundError):
    """Handle not found errors"""
    logger.warning(f"Not found error: {exc}")
    return HTTPException(status_code=404, detail=str(exc))

@app.exception_handler(DuplicateError)
async def duplicate_exception_handler(request, exc: DuplicateError):
    """Handle duplicate errors"""
    logger.warning(f"Duplicate error: {exc}")
    return HTTPException(status_code=409, detail=str(exc))

@app.exception_handler(ProvisioningError)
async def provisioning_exception_handler(request, exc: ProvisioningError):
    """Handle general provisioning errors"""
    logger.error(f"Provisioning error: {exc}")
    return HTTPException(status_code=500, detail="Internal provisioning error")

# Initialize enhanced communication
service_bus = global_service_bus
circuit_breaker_config = CircuitBreakerConfig(
    failure_threshold=3,
    timeout=30,
    success_threshold=2
)

# ---- observability ----
logger = setup_logging(SERVICE_NAME, "2.0.0")

# Enhanced observability and monitoring
init_metrics(SERVICE_NAME)
init_insights(SERVICE_NAME, "2.0.0")
add_observability_middleware(app, SERVICE_NAME)

# Custom metrics for provisioning service
from zeroque_common.observability import get_metrics

def record_provisioning_metric(operation: str, status: str, tenant_id: str = None):
    """Record custom provisioning metrics"""
    try:
        metrics = get_metrics()
        metrics.counter(
            "provisioning_operations_total",
            labels={"operation": operation, "status": status, "tenant_id": tenant_id or "unknown"}
        ).inc()
    except Exception as e:
        logger.error(f"Error recording provisioning metric: {e}")

def record_subscription_limit_check(tenant_id: str, operation: str, allowed: bool):
    """Record subscription limit check metrics"""
    try:
        metrics = get_metrics()
        metrics.counter(
            "subscription_limit_checks_total",
            labels={"tenant_id": tenant_id, "operation": operation, "allowed": str(allowed)}
        ).inc()
    except Exception as e:
        logger.error(f"Error recording subscription limit metric: {e}")

def record_database_operation(operation: str, table: str, status: str, duration_ms: float):
    """Record database operation metrics"""
    try:
        metrics = get_metrics()
        metrics.histogram(
            "database_operations_duration_seconds",
            labels={"operation": operation, "table": table, "status": status}
        ).observe(duration_ms / 1000.0)
    except Exception as e:
        logger.error(f"Error recording database operation metric: {e}")
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

# Import existing models from zeroque_common and alias them for V2 use
# Note: We'll use the _new tables directly

# Subscription limits enforcement
class SubscriptionLimits:
    """Enforce subscription limits for tenant operations"""
    
    @staticmethod
    async def check_tenant_limits(tenant_id: str, operation: str, db: Session) -> bool:
        """Check if tenant can perform operation based on subscription limits"""
        try:
            # Get tenant's current usage
            current_usage = await get_tenant_usage(tenant_id, db)
            
            # Get tenant's subscription limits
            limits = await get_tenant_limits(tenant_id, db)
            
            # Check specific operation limits
            if operation == "create_site":
                return current_usage.get("sites", 0) < limits.get("max_sites", 5)
            elif operation == "create_store":
                return current_usage.get("stores", 0) < limits.get("max_stores", 20)
            elif operation == "create_user":
                return current_usage.get("users", 0) < limits.get("max_users", 100)
            
            return True
        except Exception as e:
            logger.error(f"Error checking subscription limits: {e}")
            return False
    
    @staticmethod
    async def enforce_limits(tenant_id: str, operation: str, db: Session):
        """Enforce subscription limits, raise exception if exceeded"""
        if not await SubscriptionLimits.check_tenant_limits(tenant_id, operation, db):
            raise ValidationError(f"Subscription limit exceeded for operation: {operation}")

async def get_tenant_usage(tenant_id: str, db: Session) -> Dict[str, int]:
    """Get current usage for tenant"""
    try:
        # Count sites
        sites_count = db.query(SiteV2).filter(SiteV2.tenant_id == tenant_id).count()
        
        # Count stores (through sites)
        stores_count = db.query(StoreV2).join(SiteV2).filter(SiteV2.tenant_id == tenant_id).count()
        
        # Count users (this would need to be implemented based on your user management)
        users_count = 0  # Placeholder
        
        return {
            "sites": sites_count,
            "stores": stores_count,
            "users": users_count
        }
    except Exception as e:
        logger.error(f"Error getting tenant usage: {e}")
        return {"sites": 0, "stores": 0, "users": 0}

async def get_tenant_limits(tenant_id: str, db: Session) -> Dict[str, int]:
    """Get subscription limits for tenant"""
    # This would integrate with subscription service
    # For now, return default limits
    return {
        "max_sites": 5,
        "max_stores": 20,
        "max_users": 100
    }

# Event handlers
async def handle_tenant_created(event: ServiceEvent):
    """Handle tenant creation events"""
    logger.info(f"Received tenant created event: {event.data}")
    try:
        # Automatically set up subscription for new tenant
        await setup_tenant_subscription(event.data.get("tenant_id"))
        
        # Publish to other services for tenant setup
        await publish_tenant_provisioned_event(event.data)
    except Exception as e:
        logger.error(f"Error handling tenant created event: {e}")

async def setup_tenant_subscription(tenant_id: str):
    """Automatically set up subscription for new tenant"""
    try:
        # Call subscription service to create default subscription
        subscription_data = {
            "tenant_id": tenant_id,
            "plan": "basic",
            "features": ["provisioning", "basic_analytics"],
            "limits": {
                "max_sites": 5,
                "max_stores": 20,
                "max_users": 100
            }
        }
        
        # This would integrate with the subscription service
        logger.info(f"Setting up subscription for tenant {tenant_id}: {subscription_data}")
        
    except Exception as e:
        logger.error(f"Error setting up subscription for tenant {tenant_id}: {e}")

async def publish_tenant_provisioned_event(tenant_data: dict):
    """Publish tenant provisioned event to other services"""
    try:
        event = ServiceEvent(
            event_type="tenant.provisioned",
            service_name="provisioning",
            data=tenant_data,
            correlation_id=f"tenant_provision_{int(time.time())}"
        )
        
        # Publish to event bus
        await event_bus.publish(event)
        logger.info(f"Published tenant provisioned event: {tenant_data}")
        
    except Exception as e:
        logger.error(f"Error publishing tenant provisioned event: {e}")

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
            
            return {"tenant_id": str(tenant.tenant_id), "tenant_created": True}
            
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

# ---------------- V2 Enhanced Endpoints ----------------
@app.post("/provisioning/tenants", response_model=Dict[str, Any])
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

@app.put("/provisioning/tenants/{tenant_id}")
async def upsert_tenant_v2(tenant_id: str = Path(...), payload: TenantV2Payload = Body(...), db: Session = Depends(get_db)):
    """Create or update a Tenant (V2 architecture)."""
    try:
        # Convert string tenant_id to UUID if needed
        try:
            tenant_uuid = uuid.UUID(tenant_id)
        except ValueError:
            # If not a valid UUID, generate a new one
            tenant_uuid = uuid.uuid4()
        
        # Set RLS context
        set_rls_context(db, tenant_id=str(tenant_uuid))
        
        # Check if tenant exists
        tenant_repo = RepositoryFactory.get_tenant_repository()
        existing = tenant_repo.get_by_id(db, str(tenant_uuid))
        
        if existing:
            # Update existing tenant
            tenant_repo.update(db, str(tenant_uuid),
                             name=payload.name,
                             type=payload.type)
            logger.info("tenant_updated", extra={"tenant_id": str(tenant_uuid)})
            record_provisioning_metric("update_tenant", "success", str(tenant_uuid))
            return {"tenant_id": str(tenant_uuid), "name": payload.name, "type": payload.type, "updated": True}
        else:
            # Create new tenant
            tenant_repo.create_tenant(db, payload.name, payload.type, payload.scenario_id)
            logger.info("tenant_created", extra={"tenant_id": str(tenant_uuid)})
            record_provisioning_metric("create_tenant", "success", str(tenant_uuid))
            return {"tenant_id": str(tenant_uuid), "name": payload.name, "type": payload.type, "created": True}
    except ValidationError as e:
        record_provisioning_metric("create_tenant", "validation_error", tenant_id)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Tenant operation failed: {str(e)}")
        record_provisioning_metric("create_tenant", "error", tenant_id)
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@app.put("/provisioning/sites/{site_id}")
async def upsert_site_v2(site_id: str = Path(...), payload: SiteV2Payload = Body(...), tenant_id: str = Query(...)):
    """Create or update a Site (V2 architecture)."""
    with SessionLocal() as db:
        # Convert string IDs to UUIDs if needed
        try:
            site_uuid = uuid.UUID(site_id)
        except ValueError:
            site_uuid = uuid.uuid4()
        
        try:
            tenant_uuid = uuid.UUID(tenant_id)
        except ValueError:
            tenant_uuid = uuid.uuid4()
        
        # Enforce subscription limits
        try:
            await SubscriptionLimits.enforce_limits(tenant_id, "create_site", db)
        except ValidationError as e:
            record_provisioning_metric("create_site", "limit_exceeded", tenant_id)
            raise HTTPException(status_code=400, detail=str(e))
        
        # Validate tenant exists
        if not db.query(TenantV2).filter(TenantV2.tenant_id == tenant_uuid).one_or_none():
            record_provisioning_metric("create_site", "tenant_not_found", tenant_id)
            raise HTTPException(status_code=400, detail="Tenant not found")
        
        s = db.query(SiteV2).filter(SiteV2.site_id == site_uuid).one_or_none()
        if s:
            s.name = payload.name
            s.site_type = payload.site_type
            s.geo = payload.geo
            db.commit()
            logger.info("site_updated", extra={"site_id": str(site_uuid)})
            record_provisioning_metric("update_site", "success", tenant_id)
            return {"site_id": str(s.site_id), "name": s.name, "site_type": s.site_type, "geo": s.geo, "updated": True}
        
        s = SiteV2(site_id=site_uuid, tenant_id=tenant_uuid, name=payload.name, site_type=payload.site_type, geo=payload.geo)
        db.add(s)
        db.commit()
        logger.info("site_created", extra={"site_id": str(site_uuid)})
        record_provisioning_metric("create_site", "success", tenant_id)
        return {"site_id": str(s.site_id), "name": s.name, "site_type": s.site_type, "geo": s.geo, "created": True}

@app.put("/provisioning/stores/{store_id}")
async def upsert_store_v2(store_id: str = Path(...), payload: StoreV2Payload = Body(...), site_id: str = Query(...)):
    """Create or update a Store (V2 architecture)."""
    with SessionLocal() as db:
        # Convert string IDs to UUIDs if needed
        try:
            store_uuid = uuid.UUID(store_id)
        except ValueError:
            store_uuid = uuid.uuid4()
        
        try:
            site_uuid = uuid.UUID(site_id)
        except ValueError:
            site_uuid = uuid.uuid4()
        
        # Validate site exists
        if not db.query(SiteV2).filter(SiteV2.site_id == site_uuid).one_or_none():
            raise HTTPException(status_code=400, detail="Site not found")
        
        st = db.query(StoreV2).filter(StoreV2.store_id == store_uuid).one_or_none()
        if st:
            st.name = payload.name
            st.store_type = payload.store_type
            st.geo = payload.geo
            db.commit()
            logger.info("store_updated", extra={"store_id": str(store_uuid)})
            return {"store_id": str(st.store_id), "name": st.name, "store_type": st.store_type, "geo": st.geo, "updated": True}
        
        st = StoreV2(store_id=store_uuid, site_id=site_uuid, name=payload.name, store_type=payload.store_type, geo=payload.geo)
        db.add(st)
        db.commit()
        logger.info("store_created", extra={"store_id": str(store_uuid)})
        return {"store_id": str(st.store_id), "name": st.name, "store_type": st.store_type, "geo": st.geo, "created": True}

@app.put("/provisioning/users/{user_id}")
async def upsert_user_v2(user_id: str = Path(...), payload: UserV2Payload = Body(...)):
    """Create or update a User (V2 architecture)."""
    with SessionLocal() as db:
        try:
            # Convert string user_id to UUID if needed
            try:
                user_uuid = uuid.UUID(user_id)
            except ValueError:
                user_uuid = uuid.uuid4()
            
            u = db.query(UserV2).filter(UserV2.user_id == user_uuid).one_or_none()
            if u:
                u.email = payload.email
                u.display_name = payload.display_name
                u.active = payload.active
                u.updated_at = datetime.now()
                db.commit()
                logger.info("user_updated", extra={"user_id": str(user_uuid)})
                return {"user_id": str(u.user_id), "email": u.email, "display_name": u.display_name, "updated": True}
            
            # Check if email already exists for a different user
            existing_user = db.query(UserV2).filter(UserV2.email == payload.email).first()
            if existing_user:
                raise HTTPException(status_code=400, detail=f"Email {payload.email} already exists for user {existing_user.user_id}")
            
            u = UserV2(user_id=user_uuid, email=payload.email, display_name=payload.display_name, active=payload.active)
            db.add(u)
            db.commit()
            logger.info("user_created", extra={"user_id": str(user_uuid)})
            return {"user_id": str(u.user_id), "email": u.email, "display_name": u.display_name, "created": True}
            
        except HTTPException:
            raise
        except Exception as e:
            db.rollback()
            logger.error(f"User creation/update failed: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@app.put("/provisioning/roles/{role_id}")
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

@app.put("/provisioning/role-assignments")
async def upsert_role_assignment_v2(payload: RoleAssignmentV2Payload = Body(...), db: Session = Depends(get_db)):
    """Assign a Role to a User with scope (V2 architecture)."""
    try:
        role_assignment_repo = RepositoryFactory.get_role_assignment_repository()
        
        assignment = role_assignment_repo.assign_role(
            db=db,
            user_id=payload.user_id,
            role_id=payload.role_id,
            scope_type=payload.scope_type,
            scope_id=payload.scope_id
        )
        
        logger.info("role_assignment_created", extra={"id": assignment.id})
        return {"id": assignment.id, "created": True}
        
    except Exception as e:
        logger.error(f"Role assignment failed: {str(e)}")
        if "not found" in str(e).lower():
            raise HTTPException(status_code=400, detail=str(e))
        elif "already exists" in str(e).lower():
            return {"id": str(e).split("'")[1] if "'" in str(e) else "unknown", "exists": True}
        else:
            raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@app.put("/provisioning/vendors/{vendor_id}")
async def upsert_vendor_v2(vendor_id: str = Path(...), payload: VendorV2Payload = Body(...)):
    """Create or update a Vendor (V2 architecture)."""
    with SessionLocal() as db:
        # Convert string IDs to UUIDs if needed
        try:
            vendor_uuid = uuid.UUID(vendor_id)
        except ValueError:
            vendor_uuid = uuid.uuid4()
        
        try:
            tenant_uuid = uuid.UUID(payload.tenant_id)
        except ValueError:
            tenant_uuid = uuid.uuid4()
        
        if not db.query(TenantV2).filter(TenantV2.tenant_id == tenant_uuid).one_or_none():
            raise HTTPException(status_code=400, detail="Tenant not found")
        
        v = db.query(VendorV2).filter(VendorV2.vendor_id == vendor_uuid).one_or_none()
        if v:
            v.tenant_id = tenant_uuid
            v.name = payload.name
            v.description = payload.description
            if payload.rating is not None:
                v.rating = payload.rating
            v.updated_at = datetime.now()
            db.commit()
            logger.info("vendor_updated", extra={"vendor_id": str(vendor_uuid)})
            return {"vendor_id": str(v.vendor_id), "tenant_id": str(v.tenant_id), "name": v.name, "updated": True}
        
        v = VendorV2(vendor_id=vendor_uuid, tenant_id=tenant_uuid, name=payload.name, description=payload.description, rating=payload.rating)
        db.add(v)
        db.commit()
        logger.info("vendor_created", extra={"vendor_id": str(vendor_uuid)})
        return {"vendor_id": str(v.vendor_id), "tenant_id": str(v.tenant_id), "name": v.name, "created": True}

@app.put("/provisioning/tenant-sites")
async def upsert_tenant_site_v2(payload: TenantSiteV2Payload = Body(...), db: Session = Depends(get_db)):
    """Link a Tenant to a Site (V2 architecture)."""
    try:
        # Validate tenant and site exist
        tenant_repo = RepositoryFactory.get_tenant_repository()
        site_repo = RepositoryFactory.get_site_repository()
        
        if not tenant_repo.get_by_id(db, payload.tenant_id):
            raise HTTPException(status_code=400, detail="Tenant not found")
        if not site_repo.get_by_id(db, payload.site_id):
            raise HTTPException(status_code=400, detail="Site not found")

        # Check if link already exists
        existing = db.execute(text("""
            SELECT id FROM tenant_sites WHERE tenant_id=:t AND site_id=:s
        """), {"t": payload.tenant_id, "s": payload.site_id}).first()

        if existing:
            logger.info("tenant_site_exists", extra={"id": existing[0]})
            return {"id": existing[0], "exists": True}

        # Create new link
        link_id = str(uuid.uuid4())
        db.execute(text("""
            INSERT INTO tenant_sites(id, tenant_id, site_id, role_type, rights_expire_at)
            VALUES(:id,:t,:s,:rt,:rea)
        """), {"id": link_id, "t": payload.tenant_id, "s": payload.site_id, "rt": payload.role_type, "rea": payload.rights_expire_at})
        db.commit()
        logger.info("tenant_site_created", extra={"id": link_id})
        return {"id": link_id, "created": True}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Tenant-site linking failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@app.put("/provisioning/site-stores")
async def upsert_site_store_v2(payload: SiteStoreV2Payload = Body(...), db: Session = Depends(get_db)):
    """Link a Site to a Store (V2 architecture)."""
    try:
        # Validate site and store exist
        site_repo = RepositoryFactory.get_site_repository()
        store_repo = RepositoryFactory.get_store_repository()
        
        if not site_repo.get_by_id(db, payload.site_id):
            raise HTTPException(status_code=400, detail="Site not found")
        if not store_repo.get_by_id(db, payload.store_id):
            raise HTTPException(status_code=400, detail="Store not found")

        # Check if link already exists
        existing = db.execute(text("""
            SELECT id FROM site_stores WHERE site_id=:s AND store_id=:st
        """), {"s": payload.site_id, "st": payload.store_id}).first()

        if existing:
            logger.info("site_store_exists", extra={"id": existing[0]})
            return {"id": existing[0], "exists": True}

        # Create new link
        link_id = str(uuid.uuid4())
        db.execute(text("""
            INSERT INTO site_stores(id, site_id, store_id)
            VALUES(:id,:s,:st)
        """), {"id": link_id, "s": payload.site_id, "st": payload.store_id})
        db.commit()
        logger.info("site_store_created", extra={"id": link_id})
        return {"id": link_id, "created": True}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Site-store linking failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@app.put("/provisioning/store-vendors")
async def upsert_store_vendor_v2(payload: StoreVendorV2Payload = Body(...), db: Session = Depends(get_db)):
    """Link a Store to a Vendor (V2 architecture)."""
    try:
        # Validate store and vendor exist
        store_repo = RepositoryFactory.get_store_repository()
        vendor_repo = RepositoryFactory.get_vendor_repository()
        
        if not store_repo.get_by_id(db, payload.store_id):
            raise HTTPException(status_code=400, detail="Store not found")
        if not vendor_repo.get_by_id(db, payload.vendor_id):
            raise HTTPException(status_code=400, detail="Vendor not found")

        # Check if link already exists
        existing = db.execute(text("""
            SELECT id FROM store_vendors WHERE store_id=:s AND vendor_id=:v
        """), {"s": payload.store_id, "v": payload.vendor_id}).first()

        if existing:
            logger.info("store_vendor_exists", extra={"id": existing[0]})
            return {"id": existing[0], "exists": True}

        # Create new link
        link_id = str(uuid.uuid4())
        db.execute(text("""
            INSERT INTO store_vendors(id, store_id, vendor_id)
            VALUES(:id,:s,:v)
        """), {"id": link_id, "s": payload.store_id, "v": payload.vendor_id})
        db.commit()
        logger.info("store_vendor_created", extra={"id": link_id})
        return {"id": link_id, "created": True}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Store-vendor linking failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@app.put("/provisioning/tenant-links")
async def upsert_tenant_link_v2(payload: TenantLinkV2Payload = Body(...), db: Session = Depends(get_db)):
    """Create a parent→child tenant link (V2 architecture)."""
    try:
        # Validate parent and child tenants exist
        tenant_repo = RepositoryFactory.get_tenant_repository()
        
        if not tenant_repo.get_by_id(db, payload.parent_tenant_id):
            raise HTTPException(status_code=400, detail="Parent tenant not found")
        if not tenant_repo.get_by_id(db, payload.child_tenant_id):
            raise HTTPException(status_code=400, detail="Child tenant not found")

        # Check if link already exists
        existing = db.execute(text("""
            SELECT id FROM tenant_links_new WHERE parent_tenant_id=:p AND child_tenant_id=:c AND relationship=:r
        """), {"p": payload.parent_tenant_id, "c": payload.child_tenant_id, "r": payload.relationship}).first()

        if existing:
            logger.info("tenant_link_exists", extra={"id": existing[0]})
            return {"id": existing[0], "exists": True}

        # Create new link
        link_id = str(uuid.uuid4())
        db.execute(text("""
            INSERT INTO tenant_links_new(id, parent_tenant_id, child_tenant_id, relationship)
            VALUES(:id,:p,:c,:r)
        """), {"id": link_id, "p": payload.parent_tenant_id, "c": payload.child_tenant_id, "r": payload.relationship})
        db.commit()
        logger.info("tenant_link_created", extra={"id": link_id})
        return {"id": link_id, "created": True}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Tenant linking failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

# ---------------- Additional V2 Endpoints ----------------
@app.put("/provisioning/erp-integrations/{integration_id}")
async def upsert_erp_integration_v2(integration_id: str = Path(...), payload: ErpIntegrationPayload = Body(...), db: Session = Depends(get_db)):
    """Create or update an ERP Integration (V2 architecture)."""
    try:
        # Validate tenant or vendor exists
        if payload.tenant_id:
            tenant_repo = RepositoryFactory.get_tenant_repository()
            if not tenant_repo.get_by_id(db, payload.tenant_id):
                raise HTTPException(status_code=400, detail="Tenant not found")
        
        if payload.vendor_id:
            vendor_repo = RepositoryFactory.get_vendor_repository()
            if not vendor_repo.get_by_id(db, payload.vendor_id):
                raise HTTPException(status_code=400, detail="Vendor not found")
        
        # Check if integration exists
        erp_repo = RepositoryFactory.get_erp_integration_repository()
        existing = erp_repo.get_by_id(db, integration_id)
        
        if existing:
            # Update existing integration
            erp_repo.update(db, integration_id, 
                           tenant_id=payload.tenant_id,
                           vendor_id=payload.vendor_id,
                           type=payload.type,
                           config=payload.config)
            logger.info("erp_integration_updated", extra={"integration_id": integration_id})
            return {"integration_id": integration_id, "updated": True}
        else:
            # Create new integration
            erp_repo.create(db,
                          id=integration_id,
                          tenant_id=payload.tenant_id,
                          vendor_id=payload.vendor_id,
                          type=payload.type,
                          config=payload.config)
            logger.info("erp_integration_created", extra={"integration_id": integration_id})
            return {"integration_id": integration_id, "created": True}
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"ERP integration failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@app.put("/provisioning/access-controls/{control_id}")
async def upsert_access_control_v2(control_id: str = Path(...), payload: AccessControlPayload = Body(...), db: Session = Depends(get_db)):
    """Create or update an Access Control (V2 architecture)."""
    try:
        # Validate site or store exists
        if payload.site_id:
            site_repo = RepositoryFactory.get_site_repository()
            if not site_repo.get_by_id(db, payload.site_id):
                raise HTTPException(status_code=400, detail="Site not found")
        
        if payload.store_id:
            store_repo = RepositoryFactory.get_store_repository()
            if not store_repo.get_by_id(db, payload.store_id):
                raise HTTPException(status_code=400, detail="Store not found")
        
        # Check if control exists
        access_repo = RepositoryFactory.get_access_control_repository()
        existing = access_repo.get_by_id(db, control_id)
        
        if existing:
            # Update existing control
            access_repo.update(db, control_id,
                              site_id=payload.site_id,
                              store_id=payload.store_id,
                              type=payload.type,
                              config=payload.config)
            logger.info("access_control_updated", extra={"control_id": control_id})
            return {"control_id": control_id, "updated": True}
        else:
            # Create new control
            access_repo.create(db,
                             id=control_id,
                             site_id=payload.site_id,
                             store_id=payload.store_id,
                             type=payload.type,
                             config=payload.config)
            logger.info("access_control_created", extra={"control_id": control_id})
            return {"control_id": control_id, "created": True}
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Access control failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@app.put("/provisioning/user-access-grants")
async def upsert_user_access_grant_v2(payload: UserAccessGrantPayload = Body(...), db: Session = Depends(get_db)):
    """Create or update a User Access Grant (V2 architecture)."""
    try:
        # Validate user and access control exist
        user_repo = RepositoryFactory.get_user_repository()
        access_repo = RepositoryFactory.get_access_control_repository()
        
        if not user_repo.get_by_id(db, payload.user_id):
            raise HTTPException(status_code=400, detail="User not found")
        if not access_repo.get_by_id(db, payload.access_control_id):
            raise HTTPException(status_code=400, detail="Access control not found")

        # Check if grant exists
        grant_repo = RepositoryFactory.get_user_access_grant_repository()
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
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"User access grant failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@app.put("/provisioning/scenarios/{scenario_id}")
async def upsert_scenario_v2(scenario_id: str = Path(...), payload: ScenarioPayload = Body(...), db: Session = Depends(get_db)):
    """Create or update a Scenario (V2 architecture)."""
    try:
        # Check if scenario exists
        scenario_repo = RepositoryFactory.get_scenario_repository()
        existing = scenario_repo.get_by_id(db, scenario_id)
        
        if existing:
            # Update existing scenario
            scenario_repo.update(db, scenario_id,
                               code=payload.code,
                               name=payload.name,
                               config=payload.config)
            logger.info("scenario_updated", extra={"scenario_id": scenario_id})
            return {"scenario_id": scenario_id, "updated": True}
        else:
            # Create new scenario
            scenario_repo.create(db,
                               id=scenario_id,
                               code=payload.code,
                               name=payload.name,
                               config=payload.config)
            logger.info("scenario_created", extra={"scenario_id": scenario_id})
            return {"scenario_id": scenario_id, "created": True}
            
    except Exception as e:
        logger.error(f"Scenario failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@app.put("/provisioning/zeroque-rails/{rail_id}")
async def upsert_zeroque_rail_v2(rail_id: str = Path(...), payload: ZeroqueRailPayload = Body(...), db: Session = Depends(get_db)):
    """Create or update a ZeroQue Rail (V2 architecture)."""
    try:
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
            
    except Exception as e:
        logger.error(f"ZeroQue rail failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

# Enhanced monitoring and management endpoints
@app.get("/provisioning/circuit-breakers")
async def get_circuit_breakers():
    """Get circuit breaker status"""
    return service_circuit_breaker.get_all_states()

@app.get("/provisioning/events/metrics")
async def get_event_metrics():
    """Get event system metrics"""
    return service_bus.get_service_metrics()

@app.get("/provisioning/sagas/{saga_id}")
async def get_saga_status(saga_id: str):
    """Get saga execution status"""
    status = saga_orchestrator.get_saga_status(saga_id)
    if not status:
        raise HTTPException(status_code=404, detail="Saga not found")
    return status

@app.get("/provisioning/events/{entity_id}")
async def get_entity_events(entity_id: str, limit: int = 100):
    """Get events for an entity"""
    events = await event_store.get_events(entity_id=entity_id, limit=limit)
    return {"entity_id": entity_id, "events": events}

@app.get("/provisioning/services")
async def get_services():
    """Get all registered services"""
    return service_registry.get_all_services()

@app.get("/provisioning/system/health")
async def get_system_health():
    """Get overall system health"""
    return await health_monitor.check_system_health()

# ---------------- V2 List Endpoints ----------------
@app.get("/provisioning/tenants")
async def list_tenants_v2(limit: int = Query(100), db: Session = Depends(get_db)):
    """List tenants (V2 architecture)"""
    try:
        tenant_repo = RepositoryFactory.get_tenant_repository()
        tenants = tenant_repo.get_all(db, limit)
        
        return [
            {
                "tenant_id": str(tenant.tenant_id),
                "name": tenant.name,
                "type": tenant.type,
                "active": tenant.active,
                "created_at": tenant.created_at
            }
            for tenant in tenants
        ]
    except Exception as e:
        logger.error(f"Failed to list tenants: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@app.get("/provisioning/sites")
async def list_sites_v2(limit: int = Query(200), db: Session = Depends(get_db)):
    """List sites (V2 architecture)"""
    try:
        site_repo = RepositoryFactory.get_site_repository()
        sites = site_repo.get_all(db, limit)
        
        return [
            {
                "site_id": str(site.site_id),
                "tenant_id": str(site.tenant_id),
                "name": site.name,
                "site_type": site.site_type,
                "geo": site.geo,
                "created_at": site.created_at
            }
            for site in sites
        ]
    except Exception as e:
        logger.error(f"Failed to list sites: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@app.get("/provisioning/stores")
async def list_stores_v2(limit: int = Query(200), db: Session = Depends(get_db)):
    """List stores (V2 architecture)"""
    try:
        store_repo = RepositoryFactory.get_store_repository()
        stores = store_repo.get_all(db, limit)
        
        return [
            {
                "store_id": str(store.store_id),
                "site_id": str(store.site_id),
                "name": store.name,
                "store_type": store.store_type,
                "geo": store.geo,
                "created_at": store.created_at
            }
            for store in stores
        ]
    except Exception as e:
        logger.error(f"Failed to list stores: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@app.get("/provisioning/users")
async def list_users_v2(limit: int = Query(200), db: Session = Depends(get_db)):
    """List users (V2 architecture)"""
    try:
        user_repo = RepositoryFactory.get_user_repository()
        users = user_repo.get_all(db, limit)
        
        return [
            {
                "user_id": str(user.user_id),
                "email": user.email,
                "display_name": user.display_name,
                "active": user.active,
                "created_at": user.created_at
            }
            for user in users
        ]
    except Exception as e:
        logger.error(f"Failed to list users: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@app.get("/provisioning/roles")
async def list_roles_v2(limit: int = Query(200), db: Session = Depends(get_db)):
    """List roles (V2 architecture)"""
    try:
        role_repo = RepositoryFactory.get_role_repository()
        roles = role_repo.get_all(db, limit)
        
        return [
            {
                "role_id": str(role.role_id),
                "code": role.code,
                "description": role.description,
                "created_at": role.created_at
            }
            for role in roles
        ]
    except Exception as e:
        logger.error(f"Failed to list roles: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@app.get("/provisioning/vendors")
async def list_vendors_v2(tenant_id: Optional[str] = Query(None), limit: int = Query(200), db: Session = Depends(get_db)):
    """List vendors (V2 architecture)"""
    try:
        vendor_repo = RepositoryFactory.get_vendor_repository()
        
        if tenant_id:
            vendors = vendor_repo.get_by_tenant(db, tenant_id)
        else:
            vendors = vendor_repo.get_all(db, limit)
        
        return [
            {
                "vendor_id": str(vendor.vendor_id),
                "tenant_id": str(vendor.tenant_id),
                "name": vendor.name,
                "description": vendor.description,
                "rating": vendor.rating,
                "active": vendor.active,
                "created_at": vendor.created_at
            }
            for vendor in vendors
        ]
    except Exception as e:
        logger.error(f"Failed to list vendors: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@app.get("/provisioning/role-assignments")
async def list_role_assignments_v2(user_id: Optional[str] = Query(None), limit: int = Query(200), db: Session = Depends(get_db)):
    """List role assignments (V2 architecture)"""
    try:
        role_assignment_repo = RepositoryFactory.get_role_assignment_repository()
        
        if user_id:
            # Get assignments for specific user
            assignments = db.execute(text("""
                SELECT id, user_id, role_id, scope_type, scope_id FROM role_assignments 
                WHERE user_id=:u ORDER BY id DESC LIMIT :l
            """), {"u": user_id, "l": limit}).all()
        else:
            # Get all assignments
            assignments = db.execute(text("""
                SELECT id, user_id, role_id, scope_type, scope_id FROM role_assignments 
                ORDER BY id DESC LIMIT :l
            """), {"l": limit}).all()
        
        return [
            {
                "id": str(assignment[0]),
                "user_id": str(assignment[1]),
                "role_id": str(assignment[2]),
                "scope_type": assignment[3],
                "scope_id": str(assignment[4]) if assignment[4] else None
            }
            for assignment in assignments
        ]
    except Exception as e:
        logger.error(f"Failed to list role assignments: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

# ---------------- Additional List Endpoints ----------------
@app.get("/provisioning/scenarios")
async def list_scenarios_v2(limit: int = Query(200), db: Session = Depends(get_db)):
    """List scenarios (V2 architecture)"""
    try:
        scenario_repo = RepositoryFactory.get_scenario_repository()
        scenarios = scenario_repo.get_all(db, limit)
        
        return [
            {
                "id": str(scenario.id),
                "code": scenario.code,
                "name": scenario.name,
                "config": scenario.config,
                "created_at": scenario.created_at
            }
            for scenario in scenarios
        ]
    except Exception as e:
        logger.error(f"Failed to list scenarios: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@app.get("/provisioning/erp-integrations")
async def list_erp_integrations_v2(tenant_id: Optional[str] = Query(None), limit: int = Query(200), db: Session = Depends(get_db)):
    """List ERP integrations (V2 architecture)"""
    try:
        erp_repo = RepositoryFactory.get_erp_integration_repository()
        
        if tenant_id:
            integrations = erp_repo.get_by_tenant(db, tenant_id)
        else:
            integrations = erp_repo.get_all(db, limit)
        
        return [
            {
                "id": str(integration.id),
                "tenant_id": str(integration.tenant_id) if integration.tenant_id else None,
                "vendor_id": str(integration.vendor_id) if integration.vendor_id else None,
                "type": integration.type,
                "config": integration.config,
                "active": integration.active,
                "last_sync_at": integration.last_sync_at,
                "created_at": integration.created_at
            }
            for integration in integrations
        ]
    except Exception as e:
        logger.error(f"Failed to list ERP integrations: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@app.get("/provisioning/access-controls")
async def list_access_controls_v2(site_id: Optional[str] = Query(None), store_id: Optional[str] = Query(None), limit: int = Query(200), db: Session = Depends(get_db)):
    """List access controls (V2 architecture)"""
    try:
        access_repo = RepositoryFactory.get_access_control_repository()
        
        if site_id:
            controls = access_repo.get_by_site(db, site_id)
        elif store_id:
            controls = access_repo.get_by_store(db, store_id)
        else:
            controls = access_repo.get_all(db, limit)
        
        return [
            {
                "id": str(control.id),
                "site_id": str(control.site_id) if control.site_id else None,
                "store_id": str(control.store_id) if control.store_id else None,
                "type": control.type,
                "config": control.config,
                "active": control.active,
                "created_at": control.created_at
            }
            for control in controls
        ]
    except Exception as e:
        logger.error(f"Failed to list access controls: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@app.get("/provisioning/user-access-grants")
async def list_user_access_grants_v2(user_id: Optional[str] = Query(None), limit: int = Query(200), db: Session = Depends(get_db)):
    """List user access grants (V2 architecture)"""
    try:
        grant_repo = RepositoryFactory.get_user_access_grant_repository()
        
        if user_id:
            grants = grant_repo.get_by_user(db, user_id)
        else:
            grants = grant_repo.get_all(db, limit)
        
        return [
            {
                "id": str(grant.id),
                "user_id": str(grant.user_id),
                "access_control_id": str(grant.access_control_id),
                "grant_type": grant.grant_type,
                "valid_from": grant.valid_from,
                "valid_until": grant.valid_until,
                "created_at": grant.created_at
            }
            for grant in grants
        ]
    except Exception as e:
        logger.error(f"Failed to list user access grants: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8204)