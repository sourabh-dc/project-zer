# services/catalog/main.py
from fastapi import FastAPI, Body, Query, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List
from sqlalchemy import text
import logging, os
from zeroque_common.db.session import get_engine, init_db, check_db, SessionLocal
from zeroque_common.events.bus import EventBus, EventType, Event
from zeroque_common.events.celery_app import celery_app

SERVICE_NAME = "catalog"
app = FastAPI(title="ZeroQue Catalog Service", version="0.8.0")

# ---------- logging ----------
log = logging.getLogger(SERVICE_NAME)
if not log.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s :: %(message)s"))
    log.addHandler(h)
log.setLevel(os.getenv("LOG_LEVEL", "INFO"))

# ---- event bus ----
event_bus = EventBus()

@app.on_event("startup")
def on_startup():
    get_engine()
    init_db()
    log.info("service_started")

@app.get("/health")
def health():
    return {"status": "ok", "service": SERVICE_NAME}

@app.get("/readiness")
def readiness():
    return {"service": SERVICE_NAME, "db": check_db(), "redis": True}

# ---------- payloads ----------
class ProductUpsert(BaseModel):
    sku: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    description: Optional[str] = None
    active: bool = True

class PriceUpsert(BaseModel):
    sku: str = Field(..., min_length=1)
    currency: str = Field("GBP", pattern=r"^[A-Z]{3}$")
    unit_minor: float = Field(..., ge=0, description="price in pounds (e.g., 1.99)")
    active: bool = True

class RestockReq(BaseModel):
    store_id: str = Field(..., min_length=1)
    sku: str = Field(..., min_length=1)
    delta: int = Field(..., description="positive for inbound, negative for outbound; non-zero")
    reason: str = Field("restock", max_length=80)

# ---------- products ----------
@app.put("/catalog/products")
def upsert_product(payload: ProductUpsert = Body(...)):
    """
    Create or update a product by SKU.
    """
    with SessionLocal() as db:
        exists = db.execute(
            text("SELECT sku FROM products WHERE sku=:s"),
            {"s": payload.sku}
        ).first()

        if exists:
            db.execute(text("""
                UPDATE products
                   SET name=:n, description=:d, active=:a, updated_at=NOW()
                 WHERE sku=:s
            """), {"n": payload.name, "d": payload.description, "a": payload.active, "s": payload.sku})
            db.commit()
            log.info("product_updated sku=%s active=%s", payload.sku, payload.active)
            
            # Publish product updated event
            try:
                product_event = Event(
                    event_type=EventType.PRODUCT_UPDATED,
                    tenant_id="system",  # Catalog events are system-wide
                    data={
                        "sku": payload.sku,
                        "name": payload.name,
                        "description": payload.description,
                        "active": payload.active,
                        "action": "updated"
                    },
                    metadata={"service": "catalog", "version": "0.8.0"}
                )
                
                celery_app.send_task(
                    "zeroque_common.events.catalog_tasks.process_product_event",
                    args=[product_event.__dict__],
                    queue="catalog"
                )
                log.info("product_event_published sku=%s event=updated", payload.sku)
            except Exception as e:
                log.warning("Failed to publish product updated event: %s", str(e))
            
            return {"sku": payload.sku, "updated": True}
        else:
            db.execute(text("""
                INSERT INTO products(sku, name, description, active)
                VALUES(:s, :n, :d, :a)
            """), {"s": payload.sku, "n": payload.name, "d": payload.description, "a": payload.active})
            db.commit()
            log.info("product_created sku=%s", payload.sku)
            
            # Publish product created event
            try:
                product_event = Event(
                    event_type=EventType.PRODUCT_CREATED,
                    tenant_id="system",  # Catalog events are system-wide
                    data={
                        "sku": payload.sku,
                        "name": payload.name,
                        "description": payload.description,
                        "active": payload.active,
                        "action": "created"
                    },
                    metadata={"service": "catalog", "version": "0.8.0"}
                )
                
                celery_app.send_task(
                    "zeroque_common.events.catalog_tasks.process_product_event",
                    args=[product_event.__dict__],
                    queue="catalog"
                )
                log.info("product_event_published sku=%s event=created", payload.sku)
            except Exception as e:
                log.warning("Failed to publish product created event: %s", str(e))
            
            return {"sku": payload.sku, "created": True}

@app.get("/catalog/products")
def list_products(active: Optional[bool] = Query(None), limit: int = Query(100, ge=1, le=1000)):
    """
    List products, optionally filtered by 'active'.
    """
    with SessionLocal() as db:
        if active is None:
            rows = db.execute(
                text("SELECT sku,name,description,active FROM products ORDER BY sku LIMIT :l"),
                {"l": limit}
            ).all()
        else:
            rows = db.execute(
                text("SELECT sku,name,description,active FROM products WHERE active=:a ORDER BY sku LIMIT :l"),
                {"a": active, "l": limit}
            ).all()
        out = [{"sku": r[0], "name": r[1], "description": r[2], "active": bool(r[3])} for r in rows]
        log.info("products_listed count=%d active=%s", len(out), active)
        return out

# ---------- prices ----------
@app.put("/catalog/prices")
def upsert_price(payload: PriceUpsert = Body(...)):
    """
    Create or update a price row (sku + currency). One row can be marked active.
    """
    with SessionLocal() as db:
        # verify product exists for better ergonomics
        prod = db.execute(text("SELECT 1 FROM products WHERE sku=:s"), {"s": payload.sku}).first()
        if not prod:
            raise HTTPException(status_code=400, detail="SKU not found; create product first")

        r = db.execute(text("""
            SELECT id FROM prices WHERE sku=:s AND currency=:c
        """), {"s": payload.sku, "c": payload.currency}).first()

        if r:
            db.execute(text("""
                UPDATE prices
                   SET unit_minor=:u, active=:a, updated_at=NOW()
                 WHERE id=:id
            """), {"u": payload.unit_minor, "a": payload.active, "id": int(r[0])})
            db.commit()
            log.info("price_updated sku=%s currency=%s unit_minor=%d active=%s",
                     payload.sku, payload.currency, payload.unit_minor, payload.active)
            return {"sku": payload.sku, "currency": payload.currency, "updated": True}

        db.execute(text("""
            INSERT INTO prices(sku, currency, unit_minor, active)
            VALUES(:s, :c, :u, :a)
        """), {"s": payload.sku, "c": payload.currency, "u": payload.unit_minor, "a": payload.active})
        db.commit()
        log.info("price_created sku=%s currency=%s unit_minor=%d active=%s",
                 payload.sku, payload.currency, payload.unit_minor, payload.active)
        return {"sku": payload.sku, "currency": payload.currency, "created": True}

@app.get("/catalog/prices")
def list_prices(sku: Optional[str] = Query(None), currency: str = Query("GBP", pattern=r"^[A-Z]{3}$")):
    """
    List prices. If 'sku' is passed, filter to that SKU + currency; else list all prices for a currency.
    """
    with SessionLocal() as db:
        if sku:
            rows = db.execute(text("""
                SELECT id, sku, currency, unit_minor, active
                  FROM prices
                 WHERE sku=:s AND currency=:c
            """), {"s": sku, "c": currency}).all()
        else:
            rows = db.execute(text("""
                SELECT id, sku, currency, unit_minor, active
                  FROM prices
                 WHERE currency=:c
            """), {"c": currency}).all()
        out = [{"id": int(r[0]), "sku": r[1], "currency": r[2], "unit_minor": int(r[3]), "active": bool(r[4])} for r in rows]
        log.info("prices_listed count=%d sku=%s currency=%s", len(out), sku, currency)
        return out

# ---------- inventory ----------
@app.post("/catalog/inventory/restock")
def restock(payload: RestockReq = Body(...)):
    """
    Adjust on-hand stock for a store/SKU and append a movement record.
    Positive delta = inbound; negative = outbound.
    """
    if payload.delta == 0:
        raise HTTPException(status_code=400, detail="delta must be non-zero")

    with SessionLocal() as db:
        # Optional safety: ensure SKU exists
        exists = db.execute(text("SELECT 1 FROM products WHERE sku=:s"), {"s": payload.sku}).first()
        if not exists:
            raise HTTPException(status_code=400, detail="SKU not found; create product first")

        # Update existing row (NO updated_at here)
        updated = db.execute(text("""
            UPDATE inventory
               SET qty = qty + :d
             WHERE store_id=:st AND sku=:s
        """), {"d": payload.delta, "st": payload.store_id, "s": payload.sku}).rowcount

        # If no row, insert a new one. Don’t start negative.
        if updated == 0:
            initial_qty = max(payload.delta, 0)
            db.execute(text("""
                INSERT INTO inventory(store_id, sku, qty)
                VALUES(:st, :s, :q)
            """), {"st": payload.store_id, "s": payload.sku, "q": initial_qty})

        # Always write a movement record
        db.execute(text("""
            INSERT INTO inventory_movements(store_id, sku, delta, reason)
            VALUES(:st, :s, :d, :r)
        """), {"st": payload.store_id, "s": payload.sku, "d": payload.delta, "r": payload.reason})

        db.commit()

        current = db.execute(text("""
            SELECT qty FROM inventory WHERE store_id=:st AND sku=:s
        """), {"st": payload.store_id, "s": payload.sku}).scalar() or 0

        log.info("inventory_adjusted store=%s sku=%s delta=%d qty=%d reason=%s",
                 payload.store_id, payload.sku, payload.delta, int(current), payload.reason)

        return {"store_id": payload.store_id, "sku": payload.sku, "delta": payload.delta, "qty": int(current)}
@app.get("/catalog/inventory")
def get_inventory(store_id: str = Query(...), limit: int = Query(500, ge=1, le=5000)):
    """
    Return current stock for a store.
    """
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT sku, qty
              FROM inventory
             WHERE store_id=:st
             ORDER BY sku
             LIMIT :l
        """), {"st": store_id, "l": limit}).all()
        out = [{"sku": r[0], "qty": int(r[1])} for r in rows]
        log.info("inventory_listed store=%s count=%d", store_id, len(out))
        return out