# services/provisioning/main.py
from fastapi import FastAPI, HTTPException, Body, Path, Query
from pydantic import BaseModel, Field
from typing import Optional
from sqlalchemy import text
import logging

from zeroque_common.db.session import get_engine, init_db, check_db, SessionLocal
from zeroque_common.models.provisioning import (
    Tenant, Site, Store, User, Role, Membership, ProviderMapping
)
from zeroque_common.middleware.idempotency import add_idempotency_middleware
from zeroque_common.events.bus import EventBus, EventType, Event
from zeroque_common.events.celery_app import celery_app

SERVICE_NAME = "provisioning"
app = FastAPI(title="ZeroQue Provisioning Service", version="0.3.0")

# ---------------- logging ----------------
logger = logging.getLogger(SERVICE_NAME)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

# Idempotency is important for clients that retry (e.g., mobile on flaky networks)
add_idempotency_middleware(app, routes=[
    ("POST", "/provisioning/memberships"),
    ("PUT",  "/provisioning/memberships"),
])

# ---- event bus ----
event_bus = EventBus()

# ---------------- lifecycle ----------------
@app.on_event("startup")
def on_startup():
    get_engine()
    init_db()
    logger.info("service_started", extra={"service": SERVICE_NAME, "version": "0.3.0"})

@app.get("/health")
def health():
    return {"status": "ok", "service": SERVICE_NAME}

@app.get("/readiness")
def readiness():
    return {"service": SERVICE_NAME, "db": check_db(), "redis": True}

# ---------------- payloads ----------------
class TenantPayload(BaseModel):
    name: str = Field(..., description="Human-friendly tenant name")

class SitePayload(BaseModel):
    tenant_id: str
    name: str

class StorePayload(BaseModel):
    site_id: str
    name: str

class UserPayload(BaseModel):
    email: str
    display_name: str

class RolePayload(BaseModel):
    code: str
    description: str = ""

class MembershipPayload(BaseModel):
    user_id: str
    role_id: str
    tenant_id: Optional[str] = None
    site_id: Optional[str] = None

class ProviderMappingPayload(BaseModel):
    provider: str = Field(..., pattern="^[a-zA-Z0-9_-]+$")
    entity_type: str = Field(..., pattern="^(store|user|product|tenant|site)$")
    local_id: str
    external_id: str

# --- budgets / tenancy extension payloads ---
class CostCentrePayload(BaseModel):
    tenant_id: str
    name: str
    manager_user_id: Optional[str] = None

class BudgetPayload(BaseModel):
    cost_centre_id: str
    period: str  # monthly|quarterly|yearly
    currency: str = "GBP"
    limit_minor: int
    hard_block: bool = True

class UserCostCentrePayload(BaseModel):
    user_id: str
    cost_centre_id: str

class TenantLinkPayload(BaseModel):
    parent_tenant_id: str
    child_tenant_id: str
    relationship: str = "distributor"

# ---------------- upserts (authoritative writes) ----------------
@app.put("/provisioning/tenants/{tenant_id}")
def upsert_tenant(tenant_id: str = Path(...), payload: TenantPayload = Body(...)):
    """Create or update a Tenant (top of hierarchy)."""
    with SessionLocal() as db:
        t = db.query(Tenant).filter(Tenant.tenant_id == tenant_id).one_or_none()
        if t:
            t.name = payload.name
            db.commit()
            logger.info("tenant_updated", extra={"tenant_id": tenant_id})
            return {"tenant_id": t.tenant_id, "name": t.name, "updated": True}
        t = Tenant(tenant_id=tenant_id, name=payload.name)
        db.add(t); db.commit()
        logger.info("tenant_created", extra={"tenant_id": tenant_id})
        return {"tenant_id": t.tenant_id, "name": t.name, "created": True}

@app.put("/provisioning/sites/{site_id}")
def upsert_site(site_id: str = Path(...), payload: SitePayload = Body(...)):
    """Create or update a Site (belongs to a Tenant)."""
    with SessionLocal() as db:
        if not db.query(Tenant).filter(Tenant.tenant_id == payload.tenant_id).one_or_none():
            raise HTTPException(status_code=400, detail="Tenant not found")
        s = db.query(Site).filter(Site.site_id == site_id).one_or_none()
        if s:
            s.tenant_id = payload.tenant_id
            s.name = payload.name
            db.commit()
            logger.info("site_updated", extra={"site_id": site_id, "tenant_id": payload.tenant_id})
            return {"site_id": s.site_id, "tenant_id": s.tenant_id, "name": s.name, "updated": True}
        s = Site(site_id=site_id, tenant_id=payload.tenant_id, name=payload.name)
        db.add(s); db.commit()
        logger.info("site_created", extra={"site_id": site_id, "tenant_id": payload.tenant_id})
        return {"site_id": s.site_id, "tenant_id": s.tenant_id, "name": s.name, "created": True}

@app.put("/provisioning/stores/{store_id}")
def upsert_store(store_id: str = Path(...), payload: StorePayload = Body(...)):
    """Create or update a Store (belongs to a Site)."""
    with SessionLocal() as db:
        if not db.query(Site).filter(Site.site_id == payload.site_id).one_or_none():
            raise HTTPException(status_code=400, detail="Site not found")
        st = db.query(Store).filter(Store.store_id == store_id).one_or_none()
        if st:
            st.site_id = payload.site_id
            st.name = payload.name
            db.commit()
            logger.info("store_updated", extra={"store_id": store_id, "site_id": payload.site_id})
            return {"store_id": st.store_id, "site_id": st.site_id, "name": st.name, "updated": True}
        st = Store(store_id=store_id, site_id=payload.site_id, name=payload.name)
        db.add(st); db.commit()
        logger.info("store_created", extra={"store_id": store_id, "site_id": payload.site_id})
        return {"store_id": st.store_id, "site_id": st.site_id, "name": st.name, "created": True}

@app.put("/provisioning/users/{user_id}")
def upsert_user(user_id: str = Path(...), payload: UserPayload = Body(...)):
    """Create or update a User (global object)."""
    with SessionLocal() as db:
        u = db.query(User).filter(User.user_id == user_id).one_or_none()
        if u:
            u.email = payload.email
            u.display_name = payload.display_name
            db.commit()
            logger.info("user_updated", extra={"user_id": user_id})
            return {"user_id": u.user_id, "email": u.email, "display_name": u.display_name, "updated": True}
        u = User(user_id=user_id, email=payload.email, display_name=payload.display_name)
        db.add(u); db.commit()
        logger.info("user_created", extra={"user_id": user_id})
        return {"user_id": u.user_id, "email": u.email, "display_name": u.display_name, "created": True}

@app.put("/provisioning/roles/{role_id}")
def upsert_role(role_id: str = Path(...), payload: RolePayload = Body(...)):
    """Create or update a Role (global role catalog)."""
    with SessionLocal() as db:
        r = db.query(Role).filter(Role.role_id == role_id).one_or_none()
        if r:
            r.code = payload.code
            r.description = payload.description
            db.commit()
            logger.info("role_updated", extra={"role_id": role_id})
            return {"role_id": r.role_id, "code": r.code, "description": r.description, "updated": True}
        r = Role(role_id=role_id, code=payload.code, description=payload.description)
        db.add(r); db.commit()
        logger.info("role_created", extra={"role_id": role_id})
        return {"role_id": r.role_id, "code": r.code, "description": r.description, "created": True}

@app.put("/provisioning/memberships")
def upsert_membership(payload: MembershipPayload = Body(...)):
    """
    Assign a Role to a User, optionally scoped to Tenant and/or Site.
    Idempotent: same (user, role, tenant, site) returns the existing id.
    """
    with SessionLocal() as db:
        if not db.query(User).filter(User.user_id == payload.user_id).one_or_none():
            raise HTTPException(status_code=400, detail="User not found")
        if not db.query(Role).filter(Role.role_id == payload.role_id).one_or_none():
            raise HTTPException(status_code=400, detail="Role not found")
        if payload.tenant_id and not db.query(Tenant).filter(Tenant.tenant_id == payload.tenant_id).one_or_none():
            raise HTTPException(status_code=400, detail="Tenant not found")
        if payload.site_id and not db.query(Site).filter(Site.site_id == payload.site_id).one_or_none():
            raise HTTPException(status_code=400, detail="Site not found")

        existing = db.execute(text("""
            SELECT id FROM memberships
             WHERE user_id=:u AND role_id=:r
               AND COALESCE(tenant_id,'')=COALESCE(:t,'')
               AND COALESCE(site_id,'')  =COALESCE(:s,'')
        """), {"u": payload.user_id, "r": payload.role_id, "t": payload.tenant_id, "s": payload.site_id}).first()

        if existing:
            logger.info("membership_exists", extra={"id": int(existing[0])})
            return {"id": int(existing[0]), "updated": False, "exists": True}

        db.execute(text("""
            INSERT INTO memberships(user_id, role_id, tenant_id, site_id)
            VALUES(:u,:r,:t,:s)
        """), {"u": payload.user_id, "r": payload.role_id, "t": payload.tenant_id, "s": payload.site_id})
        db.commit()
        new_id = db.execute(text("SELECT currval(pg_get_serial_sequence('memberships','id'))")).scalar()
        logger.info("membership_created", extra={"id": int(new_id)})
        return {"id": int(new_id), "created": True}

@app.put("/provisioning/provider-mappings")
def upsert_provider_mapping(payload: ProviderMappingPayload = Body(...)):
    """Map local IDs to external provider IDs (e.g., AiFi store/user/product)."""
    with SessionLocal() as db:
        pm = db.query(ProviderMapping).filter(
            ProviderMapping.provider == payload.provider,
            ProviderMapping.entity_type == payload.entity_type,
            ProviderMapping.local_id == payload.local_id
        ).one_or_none()

        if pm:
            pm.external_id = payload.external_id
            db.commit()
            logger.info("provider_mapping_updated", extra=payload.dict())
            return {"id": pm.id, "updated": True}

        pm = ProviderMapping(
            provider=payload.provider,
            entity_type=payload.entity_type,
            local_id=payload.local_id,
            external_id=payload.external_id
        )
        db.add(pm); db.commit()
        logger.info("provider_mapping_created", extra=payload.dict())
        return {"id": pm.id, "created": True}

# -------- budgets / user-to-cost-centre / tenant links --------
@app.put("/provisioning/cost-centres/{cost_centre_id}")
def upsert_cost_centre(cost_centre_id: str, payload: CostCentrePayload = Body(...)):
    """Create/update a Cost Centre under a tenant."""
    from zeroque_common.models.budgets import CostCentre
    with SessionLocal() as db:
        cc = db.query(CostCentre).filter(CostCentre.cost_centre_id == cost_centre_id).one_or_none()
        if cc:
            cc.tenant_id = payload.tenant_id
            cc.name = payload.name
            cc.manager_user_id = payload.manager_user_id
            db.commit()
            logger.info("cost_centre_updated", extra={"cost_centre_id": cost_centre_id})
            return {"cost_centre_id": cost_centre_id, "updated": True}
        cc = CostCentre(
            cost_centre_id=cost_centre_id,
            tenant_id=payload.tenant_id,
            name=payload.name,
            manager_user_id=payload.manager_user_id
        )
        db.add(cc); db.commit()
        logger.info("cost_centre_created", extra={"cost_centre_id": cost_centre_id})
        return {"cost_centre_id": cost_centre_id, "created": True}

@app.put("/provisioning/budgets/{budget_id}")
def upsert_budget(budget_id: str, payload: BudgetPayload = Body(...)):
    """Create/update a Budget snapshot for a Cost Centre (periodic)."""
    from zeroque_common.models.budgets import Budget, CostCentre
    with SessionLocal() as db:
        if not db.query(CostCentre).filter(CostCentre.cost_centre_id == payload.cost_centre_id).one_or_none():
            raise HTTPException(status_code=400, detail="Cost centre not found")
        b = db.query(Budget).filter(Budget.budget_id == budget_id).one_or_none()
        if b:
            b.cost_centre_id = payload.cost_centre_id
            b.period = payload.period
            b.currency = payload.currency
            b.limit_minor = payload.limit_minor
            b.hard_block = payload.hard_block
            db.commit()
            logger.info("budget_updated", extra={"budget_id": budget_id})
            return {"budget_id": budget_id, "updated": True}
        b = Budget(
            budget_id=budget_id,
            cost_centre_id=payload.cost_centre_id,
            period=payload.period,
            currency=payload.currency,
            limit_minor=payload.limit_minor,
            hard_block=payload.hard_block
        )
        db.add(b); db.commit()
        logger.info("budget_created", extra={"budget_id": budget_id})
        return {"budget_id": budget_id, "created": True}

@app.put("/provisioning/user-cost-centre")
def upsert_user_cost_centre(payload: UserCostCentrePayload = Body(...)):
    """Assign a user to a Cost Centre (primary link for spend rules)."""
    from zeroque_common.models.budgets import UserCostCentre, CostCentre
    with SessionLocal() as db:
        if not db.query(CostCentre).filter(CostCentre.cost_centre_id == payload.cost_centre_id).one_or_none():
            raise HTTPException(status_code=400, detail="Cost centre not found")
        if not db.query(User).filter(User.user_id == payload.user_id).one_or_none():
            raise HTTPException(status_code=400, detail="User not found")

        existing = db.execute(text("""
            SELECT id FROM user_cost_centres WHERE user_id=:u AND cost_centre_id=:cc
        """), {"u": payload.user_id, "cc": payload.cost_centre_id}).first()
        if existing:
            logger.info("user_cc_exists", extra={"id": int(existing[0])})
            return {"id": int(existing[0]), "exists": True}

        db.execute(text("""
            INSERT INTO user_cost_centres(user_id, cost_centre_id) VALUES(:u,:cc)
        """), {"u": payload.user_id, "cc": payload.cost_centre_id})
        db.commit()
        new_id = db.execute(text("SELECT currval(pg_get_serial_sequence('user_cost_centres','id'))")).scalar()
        logger.info("user_cc_created", extra={"id": int(new_id)})
        return {"id": int(new_id), "created": True}

@app.put("/provisioning/tenant-links")
def upsert_tenant_link(payload: TenantLinkPayload = Body(...)):
    """Create a parent→child tenant link (e.g., distributor model)."""
    from zeroque_common.models.tenancy import TenantLink
    with SessionLocal() as db:
        row = db.execute(text("""
            SELECT id FROM tenant_links
             WHERE parent_tenant_id=:p AND child_tenant_id=:c AND relationship=:r
        """), {"p": payload.parent_tenant_id, "c": payload.child_tenant_id, "r": payload.relationship}).first()
        if row:
            logger.info("tenant_link_exists", extra={"id": int(row[0])})
            return {"id": int(row[0]), "exists": True}

        db.execute(text("""
            INSERT INTO tenant_links(parent_tenant_id, child_tenant_id, relationship)
            VALUES(:p,:c,:r)
        """), {"p": payload.parent_tenant_id, "c": payload.child_tenant_id, "r": payload.relationship})
        db.commit()
        new_id = db.execute(text("SELECT currval(pg_get_serial_sequence('tenant_links','id'))")).scalar()
        logger.info("tenant_link_created", extra={"id": int(new_id)})
        return {"id": int(new_id), "created": True}

# ---------------- readers (lists) ----------------
@app.get("/provisioning/tenants")
def list_tenants(limit: int = Query(100)):
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT tenant_id, name FROM tenants ORDER BY tenant_id LIMIT :l
        """), {"l": limit}).all()
        return [{"tenant_id": r[0], "name": r[1]} for r in rows]

@app.get("/provisioning/sites")
def list_sites(tenant_id: str = Query(...), limit: int = Query(200)):
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT site_id, tenant_id, name FROM sites
             WHERE tenant_id=:t
             ORDER BY site_id LIMIT :l
        """), {"t": tenant_id, "l": limit}).all()
        return [{"site_id": r[0], "tenant_id": r[1], "name": r[2]} for r in rows]

@app.get("/provisioning/stores")
def list_stores(site_id: str = Query(...), limit: int = Query(200)):
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT store_id, site_id, name FROM stores
             WHERE site_id=:s
             ORDER BY store_id LIMIT :l
        """), {"s": site_id, "l": limit}).all()
        return [{"store_id": r[0], "site_id": r[1], "name": r[2]} for r in rows]

@app.get("/provisioning/users")
def list_users(limit: int = Query(200)):
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT user_id, email, display_name FROM users
             ORDER BY user_id LIMIT :l
        """), {"l": limit}).all()
        return [{"user_id": r[0], "email": r[1], "display_name": r[2]} for r in rows]

@app.get("/provisioning/roles")
def list_roles(limit: int = Query(200)):
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT role_id, code, description FROM roles
             ORDER BY role_id LIMIT :l
        """), {"l": limit}).all()
        return [{"role_id": r[0], "code": r[1], "description": r[2]} for r in rows]

@app.get("/provisioning/memberships")
def list_memberships(user_id: str = Query(...), limit: int = Query(200)):
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT id, user_id, role_id, tenant_id, site_id
              FROM memberships
             WHERE user_id=:u
             ORDER BY id DESC
             LIMIT :l
        """), {"u": user_id, "l": limit}).all()
        return [{"id": int(r[0]), "user_id": r[1], "role_id": r[2], "tenant_id": r[3], "site_id": r[4]} for r in rows]