from fastapi import FastAPI, HTTPException, Body, Path
from pydantic import BaseModel, Field
from typing import Optional
from zeroque_common.db.session import get_engine, init_db, check_db, SessionLocal
from zeroque_common.models.provisioning import Tenant, Site, Store, User, Role, Membership, ProviderMapping
from sqlalchemy import text
from fastapi import Query
from zeroque_common.middleware.idempotency import add_idempotency_middleware
SERVICE_NAME = "provisioning"
app = FastAPI(title="ZeroQue Provisioning Service", version="0.2.0")

add_idempotency_middleware(app, routes=[
    ("POST", "/provisioning/memberships"),
    # add more if you want idempotency elsewhere
])

@app.on_event("startup")
def on_startup():
    get_engine(); init_db()

@app.get("/health")
def health(): return {"status": "ok", "service": SERVICE_NAME}

@app.get("/readiness")
def readiness(): return {"service": SERVICE_NAME, "db": check_db(), "redis": True}

class TenantPayload(BaseModel):
    name: str

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
    entity_type: str = Field(..., pattern="^(store|user|product)$")
    local_id: str
    external_id: str

######new sprint
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
#########

@app.put("/provisioning/tenants/{tenant_id}")
def upsert_tenant(tenant_id: str = Path(...), payload: TenantPayload = Body(...)):
    with SessionLocal() as db:
        t = db.query(Tenant).filter(Tenant.tenant_id == tenant_id).one_or_none()
        if t:
            t.name = payload.name
            db.commit()
            return {"tenant_id": t.tenant_id, "name": t.name, "updated": True}
        t = Tenant(tenant_id=tenant_id, name=payload.name)
        db.add(t); db.commit()
        return {"tenant_id": t.tenant_id, "name": t.name, "created": True}

@app.put("/provisioning/sites/{site_id}")
def upsert_site(site_id: str = Path(...), payload: SitePayload = Body(...)):
    with SessionLocal() as db:
        if not db.query(Tenant).filter(Tenant.tenant_id == payload.tenant_id).one_or_none():
            raise HTTPException(status_code=400, detail="Tenant not found")
        s = db.query(Site).filter(Site.site_id == site_id).one_or_none()
        if s:
            s.tenant_id = payload.tenant_id
            s.name = payload.name
            db.commit()
            return {"site_id": s.site_id, "tenant_id": s.tenant_id, "name": s.name, "updated": True}
        s = Site(site_id=site_id, tenant_id=payload.tenant_id, name=payload.name)
        db.add(s); db.commit()
        return {"site_id": s.site_id, "tenant_id": s.tenant_id, "name": s.name, "created": True}

@app.put("/provisioning/stores/{store_id}")
def upsert_store(store_id: str = Path(...), payload: StorePayload = Body(...)):
    with SessionLocal() as db:
        if not db.query(Site).filter(Site.site_id == payload.site_id).one_or_none():
            raise HTTPException(status_code=400, detail="Site not found")
        st = db.query(Store).filter(Store.store_id == store_id).one_or_none()
        if st:
            st.site_id = payload.site_id
            st.name = payload.name
            db.commit()
            return {"store_id": st.store_id, "site_id": st.site_id, "name": st.name, "updated": True}
        st = Store(store_id=store_id, site_id=payload.site_id, name=payload.name)
        db.add(st); db.commit()
        return {"store_id": st.store_id, "site_id": st.site_id, "name": st.name, "created": True}

@app.put("/provisioning/users/{user_id}")
def upsert_user(user_id: str = Path(...), payload: UserPayload = Body(...)):
    with SessionLocal() as db:
        u = db.query(User).filter(User.user_id == user_id).one_or_none()
        if u:
            u.email = payload.email
            u.display_name = payload.display_name
            db.commit()
            return {"user_id": u.user_id, "email": u.email, "display_name": u.display_name, "updated": True}
        u = User(user_id=user_id, email=payload.email, display_name=payload.display_name)
        db.add(u); db.commit()
        return {"user_id": u.user_id, "email": u.email, "display_name": u.display_name, "created": True}

@app.put("/provisioning/roles/{role_id}")
def upsert_role(role_id: str = Path(...), payload: RolePayload = Body(...)):
    with SessionLocal() as db:
        r = db.query(Role).filter(Role.role_id == role_id).one_or_none()
        if r:
            r.code = payload.code
            r.description = payload.description
            db.commit()
            return {"role_id": r.role_id, "code": r.code, "description": r.description, "updated": True}
        r = Role(role_id=role_id, code=payload.code, description=payload.description)
        db.add(r); db.commit()
        return {"role_id": r.role_id, "code": r.code, "description": r.description, "created": True}

@app.put("/provisioning/memberships")
def upsert_membership(payload: MembershipPayload = Body(...)):
    with SessionLocal() as db:
        if not db.query(User).filter(User.user_id == payload.user_id).one_or_none():
            raise HTTPException(status_code=400, detail="User not found")
        if not db.query(Role).filter(Role.role_id == payload.role_id).one_or_none():
            raise HTTPException(status_code=400, detail="Role not found")
        if payload.tenant_id and not db.query(Tenant).filter(Tenant.tenant_id == payload.tenant_id).one_or_none():
            raise HTTPException(status_code=400, detail="Tenant not found")
        if payload.site_id and not db.query(Site).filter(Site.site_id == payload.site_id).one_or_none():
            raise HTTPException(status_code=400, detail="Site not found")

        # Unique scope check - WRAP SQL WITH text()
        existing = db.execute(
            text("SELECT id FROM memberships WHERE user_id=:u AND role_id=:r AND COALESCE(tenant_id,'')=COALESCE(:t,'') AND COALESCE(site_id,'')=COALESCE(:s,'')"),  # <-- text() here
            {"u": payload.user_id, "r": payload.role_id, "t": payload.tenant_id, "s": payload.site_id}
        ).first()
        if existing:
            return {"id": int(existing[0]), "updated": False, "exists": True}

        # INSERT statement - WRAP SQL WITH text()
        db.execute(
            text("INSERT INTO memberships(user_id, role_id, tenant_id, site_id) VALUES(:u,:r,:t,:s)"),  # <-- text() here
            {"u": payload.user_id, "r": payload.role_id, "t": payload.tenant_id, "s": payload.site_id}
        )
        db.commit()
        
        # Get the last inserted ID - WRAP SQL WITH text()
        new_id = db.execute(text("SELECT currval(pg_get_serial_sequence('memberships','id'))")).scalar()  # <-- text() here
        return {"id": int(new_id), "created": True}
    
@app.put("/provisioning/provider-mappings")
def upsert_provider_mapping(payload: ProviderMappingPayload = Body(...)):
    with SessionLocal() as db:
        pm = db.query(ProviderMapping).filter(
            ProviderMapping.provider == payload.provider,
            ProviderMapping.entity_type == payload.entity_type,
            ProviderMapping.local_id == payload.local_id
        ).one_or_none()
        if pm:
            pm.external_id = payload.external_id
            db.commit()
            return {"id": pm.id, "updated": True}
        pm = ProviderMapping(provider=payload.provider, entity_type=payload.entity_type, local_id=payload.local_id, external_id=payload.external_id)
        db.add(pm); db.commit()
        return {"id": pm.id, "created": True}

@app.put("/provisioning/cost-centres/{cost_centre_id}")
def upsert_cost_centre(cost_centre_id: str, payload: CostCentrePayload = Body(...)):
    from zeroque_common.models.budgets import CostCentre
    with SessionLocal() as db:
        cc = db.query(CostCentre).filter(CostCentre.cost_centre_id == cost_centre_id).one_or_none()
        if cc:
            cc.tenant_id = payload.tenant_id
            cc.name = payload.name
            cc.manager_user_id = payload.manager_user_id
            db.commit()
            return {"cost_centre_id": cost_centre_id, "updated": True}
        cc = CostCentre(cost_centre_id=cost_centre_id, tenant_id=payload.tenant_id, name=payload.name, manager_user_id=payload.manager_user_id)
        db.add(cc); db.commit()
        return {"cost_centre_id": cost_centre_id, "created": True}

@app.put("/provisioning/budgets/{budget_id}")
def upsert_budget(budget_id: str, payload: BudgetPayload = Body(...)):
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
            return {"budget_id": budget_id, "updated": True}
        b = Budget(budget_id=budget_id, cost_centre_id=payload.cost_centre_id, period=payload.period, currency=payload.currency, limit_minor=payload.limit_minor, hard_block=payload.hard_block)
        db.add(b); db.commit()
        return {"budget_id": budget_id, "created": True}

@app.put("/provisioning/user-cost-centre")
def upsert_user_cost_centre(payload: UserCostCentrePayload = Body(...)):
    from zeroque_common.models.budgets import UserCostCentre, CostCentre
    with SessionLocal() as db:
        if not db.query(CostCentre).filter(CostCentre.cost_centre_id == payload.cost_centre_id).one_or_none():
            raise HTTPException(status_code=400, detail="Cost centre not found")
        if not db.query(User).filter(User.user_id == payload.user_id).one_or_none():
            raise HTTPException(status_code=400, detail="User not found")
        # idempotent insert
        existing = db.execute(
            text("SELECT id FROM user_cost_centres WHERE user_id=:u AND cost_centre_id=:cc"),
            {"u": payload.user_id, "cc": payload.cost_centre_id}
        ).first()
        if existing:
            return {"id": int(existing[0]), "exists": True}
        db.execute(
            text("INSERT INTO user_cost_centres(user_id, cost_centre_id) VALUES(:u,:cc)"),
            {"u": payload.user_id, "cc": payload.cost_centre_id}
        )
        db.commit()
        new_id = db.execute(text("SELECT currval(pg_get_serial_sequence('user_cost_centres','id'))")).scalar()
        return {"id": int(new_id), "created": True}

@app.put("/provisioning/tenant-links")
def upsert_tenant_link(payload: TenantLinkPayload = Body(...)):
    from zeroque_common.models.tenancy import TenantLink
    with SessionLocal() as db:
        # idempotent upsert
        row = db.execute(
            text("""SELECT id FROM tenant_links WHERE parent_tenant_id=:p AND child_tenant_id=:c AND relationship=:r"""),
            {"p": payload.parent_tenant_id, "c": payload.child_tenant_id, "r": payload.relationship}
        ).first()
        if row:
            return {"id": int(row[0]), "exists": True}
        db.execute(text("""
            INSERT INTO tenant_links(parent_tenant_id, child_tenant_id, relationship)
            VALUES(:p,:c,:r)
        """), {"p": payload.parent_tenant_id, "c": payload.child_tenant_id, "r": payload.relationship})
        db.commit()
        new_id = db.execute(text("SELECT currval(pg_get_serial_sequence('tenant_links','id'))")).scalar()
        return {"id": int(new_id), "created": True}
    


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