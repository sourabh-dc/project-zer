from fastapi import FastAPI, Query
from sqlalchemy import text
from zeroque_common.db.session import get_engine, init_db, check_db, SessionLocal

SERVICE_NAME="reports"
app = FastAPI(title="ZeroQue Reports Service", version="0.7.0")

@app.on_event("startup")
def on_startup(): get_engine(); init_db()
@app.get("/health")     
def health():    
    return {"status":"ok","service":SERVICE_NAME}
@app.get("/readiness")  
def readiness(): 
    return {"service":SERVICE_NAME,"db":check_db(),"redis":True}

@app.get("/reports/sales/by-sku")
def sales_by_sku(tenant_id: str = Query(...), date_from: str = Query(...), date_to: str = Query(...)):
    with SessionLocal() as db:
        rows = db.execute(text("""
          SELECT oi.sku, SUM(oi.qty) AS units, SUM(oi.qty * oi.price_minor) AS revenue_minor
            FROM orders o
            JOIN order_items oi ON oi.order_id = o.order_id
           WHERE o.tenant_id=:t AND o.occurred_at::date BETWEEN :f AND :to
           GROUP BY oi.sku
           ORDER BY revenue_minor DESC
        """), {"t": tenant_id, "f": date_from, "to": date_to}).all()
        return [{"sku": r[0], "units": int(r[1]), "revenue_minor": int(r[2])} for r in rows]

@app.get("/reports/sales/by-store")
def sales_by_store(tenant_id: str = Query(...), date_from: str = Query(...), date_to: str = Query(...)):
    with SessionLocal() as db:
        rows = db.execute(text("""
          SELECT o.store_id, COUNT(*) AS orders, SUM(o.total_minor) AS revenue_minor
            FROM orders o
           WHERE o.tenant_id=:t AND o.occurred_at::date BETWEEN :f AND :to
           GROUP BY o.store_id
           ORDER BY revenue_minor DESC
        """), {"t": tenant_id, "f": date_from, "to": date_to}).all()
        return [{"store_id": r[0], "orders": int(r[1]), "revenue_minor": int(r[2])} for r in rows]

@app.get("/reports/footfall/daily")
def footfall_daily(tenant_id: str = Query(...), date_from: str = Query(...), date_to: str = Query(...)):
    with SessionLocal() as db:
        rows = db.execute(text("""
          SELECT day, value FROM usage_aggregates_daily
           WHERE tenant_id=:t AND meter_code='unique_shoppers' AND day BETWEEN :f AND :to
           ORDER BY day
        """), {"t": tenant_id, "f": date_from, "to": date_to}).all()
        return [{"day": str(r[0]), "unique_shoppers": int(r[1])} for r in rows]
    
@app.get("/reports/stock/onhand")
def stock_onhand(store_id: str = Query(...)):
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT sku, qty FROM inventory WHERE store_id=:st ORDER BY sku
        """), {"st": store_id}).all()
        return [{"sku": r[0], "qty": int(r[1])} for r in rows]

@app.get("/reports/stock/movements")
def stock_movements(store_id: str = Query(...), limit: int = Query(100)):
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT created_at, sku, delta, reason
              FROM inventory_movements
             WHERE store_id=:st
             ORDER BY id DESC
             LIMIT :l
        """), {"st": store_id, "l": limit}).all()
        return [{"created_at": str(r[0]), "sku": r[1], "delta": int(r[2]), "reason": r[3]} for r in rows]