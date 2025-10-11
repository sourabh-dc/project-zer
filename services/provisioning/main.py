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
import uuid
from datetime import timezone

from fastapi import FastAPI, HTTPException, Body, Path, Query, Depends
from typing import Dict, Any
from sqlalchemy import text
from sqlalchemy.orm import Session

from services.provisioning.core.provisioning_saga import ProvisioningSaga
from services.provisioning.core.recording_service import record_provisioning_metric
from services.provisioning.services.site_service import SiteService
from services.provisioning.services.store_service import StoreService
from services.provisioning.services.tenant_service import TenantService

# Add the packages path to sys.path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..', 'packages', 'zeroque_common'))

from zeroque_common.communication import (
    CircuitBreakerConfig,
    # Global instances
    service_bus,
    service_circuit_breaker,
    saga_orchestrator,
    service_registry,
    health_monitor,
    event_store
)
from zeroque_common.db.session import get_engine, init_db, check_db, SessionLocal, get_db
from zeroque_common.middleware.usage_middleware import add_api_call_meter
from zeroque_common.middleware.idempotency import add_idempotency_middleware
from zeroque_common.observability import setup_logging, init_metrics, init_insights, add_observability_middleware

# Import service layer, repositories and schemas
from .repositories.repository_factory import RepositoryFactory
from .utils.custom_exceptions import ValidationError
from .models import *
from .schemas import *

# Service configuration
SERVICE_NAME = "provisioning"
app = FastAPI(title="Enhanced ZeroQue Provisioning Service", version="2.0.0")

# Initialize enhanced communication
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


init_metrics(SERVICE_NAME) #initialize metrics
init_insights(SERVICE_NAME, "2.0.0") #initialize app insights

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

# Initialize saga
provisioning_saga = ProvisioningSaga()
tenant_service = TenantService()
site_service = SiteService()
store_service = StoreService()

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

# ---------------- V2 Enhanced Endpoints ----------------
@app.post("/provisioning/tenants", response_model=Dict[str, Any])
async def create_tenant_v2(payload: TenantV2Payload = Body(...)):
    """Create tenant with enhanced communication patterns"""
    try:
        return await tenant_service.create_tenant_v2(payload, SERVICE_NAME)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/provisioning/tenants/{tenant_id}")
async def upsert_tenant_v2(tenant_id: str = Path(...), payload: TenantV2Payload = Body(...), db: Session = Depends(get_db)):
    """Create or update a Tenant (V2 architecture)."""
    try:
        return await tenant_service.upsert_tenant_v2(tenant_id, payload, db)
    except ValidationError as e:
        record_provisioning_metric("create_tenant", "validation_error", tenant_id)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Tenant operation failed: {str(e)}")
        record_provisioning_metric("create_tenant", "error", tenant_id)
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@app.put("/provisioning/sites/{site_id}")
async def upsert_site_v2(site_id: str = Path(...), payload: SiteV2Payload = Body(...), tenant_id: str = Query(...), db: Session = Depends(get_db)):
    """Create or update a Site (V2 architecture)."""
    try:
        return await site_service.upsert_site_v2(site_id, payload, tenant_id, db)
    except ValidationError as e:
        record_provisioning_metric("create_site", "validation_error", tenant_id)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Site operation failed: {str(e)}")
        record_provisioning_metric("create_site", "error", tenant_id)
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@app.put("/provisioning/stores/{store_id}")
async def upsert_store_v2(store_id: str = Path(...), payload: StoreV2Payload = Body(...), site_id: str = Query(...), db: Session = Depends(get_db)):
    """Create or update a Store (V2 architecture)."""
    try:
        return await store_service.upsert_store_v2(store_id, payload, site_id, db)
    except Exception as e:
        logger.error(f"Store operation failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

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

# =============================================================================
# INTEGRATION ENDPOINTS
# =============================================================================

@app.post("/provisioning/v2/integration/cv-connector/user-created")
async def notify_cv_connector_user_created(
    tenant_id: str = Body(...),
    user_id: str = Body(...),
    user_data: Dict[str, Any] = Body(...)
):
    """Integration endpoint for CV Connector service to handle USER_CREATED events"""
    try:
        logger.info(f"Processing USER_CREATED event for CV Connector integration: user_id={user_id}, tenant_id={tenant_id}")

        # Validate user exists
        with SessionLocal() as db:
            user = db.execute(
                text("SELECT * FROM users WHERE id = :user_id AND tenant_id = :tenant_id"),
                {"user_id": user_id, "tenant_id": tenant_id}
            ).fetchone()

            if not user:
                raise HTTPException(status_code=404, detail="User not found")

        # Prepare event data for CV Connector service
        cv_event_data = {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "user_data": user_data,
            "event_source": "provisioning_service"
        }

        # Notify CV Connector service via HTTP call
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    "http://localhost:8100/events/user-created",
                    json=cv_event_data
                )

                if response.status_code == 200:
                    logger.info(f"Successfully notified CV Connector service for user {user_id}")
                    return {"ok": True, "cv_notified": True, "user_id": user_id}
                else:
                    logger.warning(f"CV Connector service returned status {response.status_code} for user {user_id}")
                    return {"ok": False, "cv_notified": False, "user_id": user_id, "error": "CV Connector service error"}

        except Exception as e:
            logger.error(f"Failed to notify CV Connector service for user {user_id}: {str(e)}")
            return {"ok": False, "cv_notified": False, "user_id": user_id, "error": str(e)}

    except Exception as e:
        logger.error(f"Error processing USER_CREATED event for user {user_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to process USER_CREATED event: {str(e)}")

@app.post("/provisioning/v2/integration/cv-connector/tenant-created")
async def notify_cv_connector_tenant_created(
    tenant_id: str = Body(...),
    tenant_data: Dict[str, Any] = Body(...)
):
    """Integration endpoint for CV Connector service to handle TENANT_CREATED events"""
    try:
        logger.info(f"Processing TENANT_CREATED event for CV Connector integration: tenant_id={tenant_id}")

        # Validate tenant exists
        with SessionLocal() as db:
            tenant = db.execute(
                text("SELECT * FROM tenants WHERE tenant_id = :tenant_id"),
                {"tenant_id": tenant_id}
            ).fetchone()

            if not tenant:
                raise HTTPException(status_code=404, detail="Tenant not found")

        # Prepare event data for CV Connector service
        cv_event_data = {
            "tenant_id": tenant_id,
            "tenant_data": tenant_data,
            "event_source": "provisioning_service"
        }

        # Notify CV Connector service via HTTP call for initial setup
        try:
            import httpx
            async with httpx.AsyncClient(timeout=15.0) as client:
                # First, create CV provider configuration for the tenant
                provider_config = {
                    "tenant_id": tenant_id,
                    "type": "cv",
                    "name": "aifi",
                    "config": {
                        "provider": "aifi",
                        "api_key": "default_api_key",  # Should be configured per tenant
                        "base_url": "https://api.aifi.example",
                        "location_id": tenant_data.get("location_id"),
                        "store_id": tenant_data.get("store_id")
                    },
                    "active": True
                }

                response = await client.post(
                    "http://localhost:8100/admin/rails/cv",
                    json=provider_config
                )

                if response.status_code == 200:
                    logger.info(f"Successfully set up CV provider configuration for tenant {tenant_id}")
                    return {"ok": True, "cv_setup": True, "tenant_id": tenant_id}
                else:
                    logger.warning(f"CV Connector service returned status {response.status_code} for tenant {tenant_id}")
                    return {"ok": False, "cv_setup": False, "tenant_id": tenant_id, "error": "CV Connector service error"}

        except Exception as e:
            logger.error(f"Failed to set up CV provider configuration for tenant {tenant_id}: {str(e)}")
            return {"ok": False, "cv_setup": False, "tenant_id": tenant_id, "error": str(e)}

    except Exception as e:
        logger.error(f"Error processing TENANT_CREATED event for tenant {tenant_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to process TENANT_CREATED event: {str(e)}")

@app.get("/provisioning/v2/integration/status")
async def get_integration_status():
    """Get status of all service integrations"""
    try:
        integration_status = {
            "cv_connector_service": {"status": "unknown", "url": "http://localhost:8100"},
            "cv_gateway_service": {"status": "unknown", "url": "http://localhost:8000"},
            "catalog_service": {"status": "unknown", "url": "http://localhost:8080"},
            "orders_service": {"status": "unknown", "url": "http://localhost:8081"}
        }

        # Test each service connectivity
        import httpx
        async with httpx.AsyncClient(timeout=5.0) as client:
            for service_name, config in integration_status.items():
                try:
                    response = await client.get(f"{config['url']}/health")
                    if response.status_code == 200:
                        config["status"] = "healthy"
                        config["response_time_ms"] = response.elapsed.total_seconds() * 1000
                    else:
                        config["status"] = "unhealthy"
                except Exception as e:
                    config["status"] = "unreachable"
                    config["error"] = str(e)

        return {
            "integration_status": integration_status,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

    except Exception as e:
        logger.error(f"Error getting integration status: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get integration status: {str(e)}")

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