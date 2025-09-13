from fastapi import FastAPI, Query
from sqlalchemy import text
from zeroque_common.db.session import get_engine, init_db, check_db, SessionLocal

SERVICE_NAME="entitlements"
app = FastAPI(title="ZeroQue Entitlements Service", version="0.5.0")

@app.on_event("startup")
def on_startup():
    get_engine(); init_db()

@app.get("/health")
def health(): return {"status":"ok","service":SERVICE_NAME}

@app.get("/readiness")
def readiness(): return {"service":SERVICE_NAME,"db":check_db(),"redis":True}

@app.get("/entitlements")
def get_entitlements(tenant_id: str = Query(...), site_id: str | None = Query(None)):
    with SessionLocal() as db:
        # derive plan → features
        plan = db.execute(text("""
            SELECT plan_code FROM subscriptions
            WHERE tenant_id=:t AND status='active'
            ORDER BY id DESC LIMIT 1
        """), {"t": tenant_id}).scalar()
        if not plan:
            return {"tenant_id": tenant_id, "features": {}, "plan": None}
        rows = db.execute(text("""
            SELECT pf.feature_code, pf.enabled, pf.limits
            FROM plan_features pf
            WHERE pf.plan_code=:p
        """), {"p": plan}).all()
        features = {r[0]: {"enabled": bool(r[1]), "limits": (r[2] or {})} for r in rows}
        return {"tenant_id": tenant_id, "site_id": site_id, "plan": plan, "features": features, "ttl_seconds": 60}