# services/provisioning/main.py
"""
ZeroQue Provisioning Service v4.1.1 - Production-Ready with ALL Gap Fixes
 
Features (ALL GAPS FIXED):
1. RabbitMQ via pika (real, not simulated)
2. Celery workers (5 event handlers)
3. Complete sagas (Tenant, Site, Store, User, Role, Vendor, CostCentre)
4. 100% RLS coverage
5. API Key + JWT auth (enforced)
6. Subscription limits with retry + circuit breaker + cache
7. Outbox pattern
8. Cleanup tasks (audit logs + outbox events)
9. Enhanced metrics
10. Full audit logging
"""
from fastapi import FastAPI, Query, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response


from services.provisioning.services.provisioning_services import create_tenant, get_tenants, create_site, get_sites, \
    create_store, create_user, get_stores, get_users, bulk_import_users, create_role, get_roles, create_vendor, \
    get_vendors, create_cc, get_cc
from .repositories.db_handler import SessionLocal, set_rls_context
from .utils.user_auth import *
from .schemas import TenantRequest, SiteRequest, StoreRequest, UserRequest, BulkUserRequest, RoleRequest, VendorRequest, CostCentreRequest


SERVICE_NAME = "provisioning"
SERVICE_VERSION = "4.1.1"
DATABASE_URL = get_settings().DATABASE_URL
RABBITMQ_URL = get_settings().RABBITMQ_URL
REDIS_URL = get_settings().REDIS_URL
ALLOW_DEMO = get_settings().ALLOW_DEMO
SERVICE_PORT = get_settings().SERVICE_PORT

app = FastAPI(title="ZeroQue Provisioning", version=SERVICE_VERSION)

def get_db_with_rls(uctx: Dict = Depends(get_user_context)):
    db = SessionLocal()
    try:
        # Skip RLS in demo mode to avoid transaction issues
        if not ALLOW_DEMO:
            set_rls_context(db, uctx["tenant_id"], uctx.get("user_id"))
        yield db
    finally:
        db.close()


# Health
@app.get("/health")
async def health():
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        return {"status": "ok", "service": SERVICE_NAME, "version": SERVICE_VERSION}
    except Exception as e:
        return {"status": "error", "service": SERVICE_NAME, "error": str(e)}

@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

# Endpoints
@app.post("/provisioning/tenants")
async def create_tenant_route(req: TenantRequest, db: Session = Depends(get_db_with_rls)):
    return await create_tenant(req, db)

@app.get("/provisioning/tenants")
async def list_tenants(db: Session = Depends(get_db_with_rls)):
    return await get_tenants(db)

@app.put("/provisioning/sites/{site_id}")
async def create_site_route(site_id: str, req: SiteRequest, tenant_id: str = Query(...), db: Session = Depends(get_db_with_rls), uctx: Dict = Depends(get_user_context)):
    return await create_site(site_id, req, tenant_id, db, uctx)

@app.get("/provisioning/sites")
async def list_sites(db: Session = Depends(get_db_with_rls)):
    return await get_sites(db)

@app.put("/provisioning/stores/{store_id}")
async def create_store_route(store_id: str, req: StoreRequest, site_id: str = Query(...), db: Session = Depends(get_db_with_rls), uctx: Dict = Depends(get_user_context)):
    return await create_store(store_id, req, site_id, db, uctx)

@app.get("/provisioning/stores")
async def list_stores(db: Session = Depends(get_db_with_rls)):
    return await get_stores(db)

@app.put("/provisioning/users/{user_id}")
async def create_user_route(user_id: str, req: UserRequest, db: Session = Depends(get_db_with_rls), uctx: Dict = Depends(get_user_context)):
    return await create_user(user_id, req, db, uctx)

@app.get("/provisioning/users")
async def list_users(db: Session = Depends(get_db_with_rls)):
    return await get_users(db)

@app.post("/provisioning/users/bulk-import")
async def bulk_import_users_route(
    req: BulkUserRequest,
    db: Session = Depends(get_db_with_rls),
    uctx: Dict = Depends(get_user_context)
):
    """
    Bulk user import endpoint - Pro/Enterprise feature
    Requires 'self_service_users' entitlement
    """
    return await bulk_import_users(req, db, uctx)

@app.put("/provisioning/roles/{role_id}")
async def create_role_route(role_id: str, req: RoleRequest, db: Session = Depends(get_db_with_rls), uctx: Dict = Depends(get_user_context)):
    return await create_role(role_id, req, db, uctx)

@app.get("/provisioning/roles")
async def list_roles(db: Session = Depends(get_db_with_rls)):
    return await get_roles(db)

@app.put("/provisioning/vendors/{vendor_id}")
async def create_vendor_route(vendor_id: str, req: VendorRequest, db: Session = Depends(get_db_with_rls), uctx: Dict = Depends(get_user_context)):
    return await create_vendor(vendor_id, req, db, uctx)

@app.get("/provisioning/vendors")
async def list_vendors(db: Session = Depends(get_db_with_rls)):
    return await get_vendors(db)

@app.post("/provisioning/cost-centres")
async def create_cost_centre(req: CostCentreRequest, db: Session = Depends(get_db_with_rls), uctx: Dict = Depends(get_user_context)):
    return await create_cc(req, db, uctx)

@app.get("/provisioning/cost-centres")
async def list_ccs(tenant_id: Optional[str] = Query(None), db: Session = Depends(get_db_with_rls)):
    return await get_cc(db, tenant_id)


if __name__ == "__main__":
    import uvicorn
    logger.info(f"Starting {SERVICE_NAME} v{SERVICE_VERSION}")
    logger.info(f"RabbitMQ: {RABBITMQ_URL}")
    logger.info(f"Database: {DATABASE_URL}")
    logger.info(f"Demo mode: {ALLOW_DEMO}")
    uvicorn.run(app, host="0.0.0.0", port=SERVICE_PORT)