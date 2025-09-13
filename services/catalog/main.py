from fastapi import FastAPI, Body, Query, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from sqlalchemy import text
from zeroque_common.db.session import get_engine, init_db, check_db, SessionLocal

SERVICE_NAME="catalog"
app = FastAPI(title="ZeroQue Catalog Service", version="0.7.0")

@app.on_event("startup")
def on_startup(): get_engine(); init_db()
@app.get("/health")     
def health():     
    return {"status":"ok","service":SERVICE_NAME}
@app.get("/readiness")  
def readiness():  
    return {"service":SERVICE_NAME,"db":check_db(),"redis":True}

# ---------- payloads ----------
class ProductUpsert(BaseModel):
    sku: str
    name: str
    description: Optional[str] = None
    active: bool = True

class PriceUpsert(BaseModel):
    sku: str
    currency: str = "GBP"
    unit_minor: int
    active: bool = True

class RestockReq(BaseModel):
    store_id: str
    sku: str
    delta: int  # positive for in, negative for out
    reason: str = "restock"

# ---------- products ----------
@app.put("/catalog/products")
def upsert_product(payload: ProductUpsert = Body(...)):
    with SessionLocal() as db:
        exists = db.execute(text("SELECT sku FROM products WHERE sku=:s"), {"s": payload.sku}).first()
        if exists:
            db.execute(text("""
                UPDATE products SET name=:n, description=:d, active=:a WHERE sku=:s
            """), {"n": payload.name, "d": payload.description, "a": payload.active, "s": payload.sku})
        else:
            db.execute(text("""
                INSERT INTO products(sku,name,description,active) VALUES(:s,:n,:d,:a)
            """), {"s": payload.sku, "n": payload.name, "d": payload.description, "a": payload.active})
        db.commit()
        return {"sku": payload.sku, "updated": bool(exists), "created": not bool(exists)}

@app.get("/catalog/products")
def list_products(active: Optional[bool] = Query(None), limit: int = Query(100)):
    with SessionLocal() as db:
        if active is None:
            rows = db.execute(text("SELECT sku,name,description,active FROM products ORDER BY sku LIMIT :l"), {"l": limit}).all()
        else:
            rows = db.execute(text("SELECT sku,name,description,active FROM products WHERE active=:a ORDER BY sku LIMIT :l"), {"a": active, "l": limit}).all()
        return [{"sku": r[0], "name": r[1], "description": r[2], "active": bool(r[3])} for r in rows]

# ---------- prices ----------
@app.put("/catalog/prices")
def upsert_price(payload: PriceUpsert = Body(...)):
    with SessionLocal() as db:
        r = db.execute(text("""
            SELECT id FROM prices WHERE sku=:s AND currency=:c
        """), {"s": payload.sku, "c": payload.currency}).first()
        if r:
            db.execute(text("""
                UPDATE prices SET unit_minor=:u, active=:a WHERE id=:id
            """), {"u": payload.unit_minor, "a": payload.active, "id": int(r[0])})
            db.commit()
            return {"sku": payload.sku, "currency": payload.currency, "updated": True}
        db.execute(text("""
            INSERT INTO prices(sku,currency,unit_minor,active) VALUES(:s,:c,:u,:a)
        """), {"s": payload.sku, "c": payload.currency, "u": payload.unit_minor, "a": payload.active})
        db.commit()
        return {"sku": payload.sku, "currency": payload.currency, "created": True}

@app.get("/catalog/prices")
def list_prices(sku: Optional[str] = Query(None), currency: str = Query("GBP")):
    with SessionLocal() as db:
        if sku:
            rows = db.execute(text("""
                SELECT id, sku, currency, unit_minor, active FROM prices WHERE sku=:s AND currency=:c
            """), {"s": sku, "c": currency}).all()
        else:
            rows = db.execute(text("""
                SELECT id, sku, currency, unit_minor, active FROM prices WHERE currency=:c
            """), {"c": currency}).all()
        return [{"id": int(r[0]), "sku": r[1], "currency": r[2], "unit_minor": int(r[3]), "active": bool(r[4])} for r in rows]

# ---------- inventory ----------
@app.post("/catalog/inventory/restock")
def restock(payload: RestockReq = Body(...)):
    if payload.delta == 0:
        raise HTTPException(status_code=400, detail="delta must be non-zero")
    with SessionLocal() as db:
        # upsert inventory
        upd = db.execute(text("""
            UPDATE inventory SET qty = qty + :d WHERE store_id=:st AND sku=:s
        """), {"d": payload.delta, "st": payload.store_id, "s": payload.sku}).rowcount
        if upd == 0:
            db.execute(text("""
                INSERT INTO inventory(store_id, sku, qty) VALUES(:st, :s, :q)
            """), {"st": payload.store_id, "s": payload.sku, "q": max(payload.delta, 0)})
        # movement record
        db.execute(text("""
            INSERT INTO inventory_movements(store_id, sku, delta, reason)
            VALUES(:st, :s, :d, :r)
        """), {"st": payload.store_id, "s": payload.sku, "d": payload.delta, "r": payload.reason})
        db.commit()
        current = db.execute(text("SELECT qty FROM inventory WHERE store_id=:st AND sku=:s"),
                             {"st": payload.store_id, "s": payload.sku}).scalar()
        return {"store_id": payload.store_id, "sku": payload.sku, "delta": payload.delta, "qty": int(current)}

@app.get("/catalog/inventory")
def get_inventory(store_id: str = Query(...), limit: int = Query(500)):
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT sku, qty FROM inventory WHERE store_id=:st ORDER BY sku LIMIT :l
        """), {"st": store_id, "l": limit}).all()
        return [{"sku": r[0], "qty": int(r[1])} for r in rows]