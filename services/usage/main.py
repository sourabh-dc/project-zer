from fastapi import FastAPI, HTTPException, Body, Query
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from sqlalchemy import text
from zeroque_common.db.session import get_engine, init_db, check_db, SessionLocal
from zeroque_common.models.usage import UsageMeter, UsageEvent, UsageAggregateDaily
from zeroque_common.models.provisioning import Tenant, Site, Store, User

SERVICE_NAME = "usage"
app = FastAPI(title="ZeroQue Usage Service", version="0.2.0")

@app.on_event("startup")
def on_startup():
    get_engine(); init_db()

@app.get("/health")
def health(): return {"status": "ok", "service": SERVICE_NAME}

@app.get("/readiness")
def readiness(): return {"service": SERVICE_NAME, "db": check_db(), "redis": True}

class EmitUsagePayload(BaseModel):
    tenant_id: str
    site_id: Optional[str] = None
    store_id: Optional[str] = None
    meter: str
    value: int = 1
    subject_id: Optional[str] = None
    occurred_at: Optional[datetime] = None

def _update_daily(db, when: datetime, tenant_id: str, site_id: Optional[str], store_id: Optional[str], meter_code: str, delta: int):
    d = when.date()
    updated = db.execute(text("""
        UPDATE usage_aggregates_daily
        SET value = value + :delta
        WHERE day = :day AND tenant_id=:tenant AND COALESCE(site_id,'') = COALESCE(:site,'') AND COALESCE(store_id,'') = COALESCE(:store,'') AND meter_code=:meter
    """), {"delta": delta, "day": d, "tenant": tenant_id, "site": site_id, "store": store_id, "meter": meter_code}).rowcount
    if updated == 0:
        try:
            db.execute(text("""
                INSERT INTO usage_aggregates_daily(day, tenant_id, site_id, store_id, meter_code, value)
                VALUES (:day, :tenant, :site, :store, :meter, :val)
            """), {"day": d, "tenant": tenant_id, "site": site_id, "store": store_id, "meter": meter_code, "val": delta})
        except Exception:
            db.execute(text("""
                UPDATE usage_aggregates_daily
                SET value = value + :delta
                WHERE day = :day AND tenant_id=:tenant AND COALESCE(site_id,'') = COALESCE(:site,'') AND COALESCE(store_id,'') = COALESCE(:store,'') AND meter_code=:meter
            """), {"delta": delta, "day": d, "tenant": tenant_id, "site": site_id, "store": store_id, "meter": meter_code})

@app.post("/dev/emit-usage")
def emit_usage(payload: EmitUsagePayload = Body(...)):
    when = payload.occurred_at or datetime.utcnow()
    with SessionLocal() as db:
        m = db.query(UsageMeter).filter(UsageMeter.code == payload.meter).one_or_none()
        if not m:
            raise HTTPException(status_code=400, detail="Unknown meter")
        ev = UsageEvent(tenant_id=payload.tenant_id, site_id=payload.site_id, store_id=payload.store_id, meter_code=payload.meter, subject_id=payload.subject_id, value=payload.value, occurred_at=when)
        db.add(ev); db.flush()
        _update_daily(db, when, payload.tenant_id, payload.site_id, payload.store_id, payload.meter, payload.value)
        db.commit()
        return {"event_id": ev.id, "meter": payload.meter, "value": payload.value}

class SimOrderPayload(BaseModel):
    tenant_id: str
    site_id: str
    store_id: str
    shopper_id: str

@app.post("/dev/simulate-order")
def simulate_order(payload: SimOrderPayload = Body(...)):
    when = datetime.utcnow()
    with SessionLocal() as db:
        if not db.query(Tenant).filter(Tenant.tenant_id == payload.tenant_id).one_or_none():
            raise HTTPException(status_code=400, detail="Tenant not found")
        if not db.query(Site).filter(Site.site_id == payload.site_id, Site.tenant_id == payload.tenant_id).one_or_none():
            raise HTTPException(status_code=400, detail="Site not found or not in tenant")
        if not db.query(Store).filter(Store.store_id == payload.store_id, Store.site_id == payload.site_id).one_or_none():
            raise HTTPException(status_code=400, detail="Store not found or not in site")
        if not db.query(User).filter(User.user_id == payload.shopper_id).one_or_none():
            raise HTTPException(status_code=400, detail="Shopper user not found")

        meters = {m.code for m in db.query(UsageMeter).all()}
        for needed in ["orders", "unique_shoppers"]:
            if needed not in meters:
                raise HTTPException(status_code=400, detail=f"Missing meter seed: {needed}")

        ev1 = UsageEvent(tenant_id=payload.tenant_id, site_id=payload.site_id, store_id=payload.store_id, meter_code="orders", subject_id=payload.shopper_id, value=1, occurred_at=when)
        db.add(ev1); db.flush()
        _update_daily(db, when, payload.tenant_id, payload.site_id, payload.store_id, "orders", 1)

        day = when.date()
        exists = db.execute(text("""
            SELECT 1 FROM usage_events
            WHERE meter_code='unique_shoppers' AND tenant_id=:tenant AND COALESCE(site_id,'')=COALESCE(:site,'') AND COALESCE(store_id,'')=COALESCE(:store,'')
              AND subject_id=:shopper AND occurred_at::date = :day
            LIMIT 1
        """), {"tenant": payload.tenant_id, "site": payload.site_id, "store": payload.store_id, "shopper": payload.shopper_id, "day": day}).first()
        if not exists:
            ev2 = UsageEvent(tenant_id=payload.tenant_id, site_id=payload.site_id, store_id=payload.store_id, meter_code="unique_shoppers", subject_id=payload.shopper_id, value=1, occurred_at=when)
            db.add(ev2); db.flush()
            _update_daily(db, when, payload.tenant_id, payload.site_id, payload.store_id, "unique_shoppers", 1)

        db.commit()
        return {"ok": True, "order_event_id": ev1.id}
    
@app.get("/usage/daily")
def get_usage_daily(
    tenant_id: str = Query(...),
    meter: str = Query(...),
    from_: str = Query("2000-01-01", alias="from"),
    to: str = Query("2100-01-01"),
    site_id: Optional[str] = Query(None),
    store_id: Optional[str] = Query(None)
):
    with SessionLocal() as db:
        sql = """
            SELECT day, SUM(value) AS value
            FROM usage_aggregates_daily
            WHERE tenant_id=:tenant
              AND meter_code=:meter
              AND day >= :from AND day <= :to
        """
        params = {"tenant": tenant_id, "meter": meter, "from": from_, "to": to}

        # Only constrain site/store if provided
        if site_id is not None:
            sql += " AND site_id = :site_id"
            params["site_id"] = site_id
        if store_id is not None:
            sql += " AND store_id = :store_id"
            params["store_id"] = store_id

        sql += " GROUP BY day ORDER BY day ASC"

        rows = db.execute(text(sql), params).all()
        return [{"day": str(r[0]), "value": int(r[1])} for r in rows]