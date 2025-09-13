from fastapi import FastAPI, Body, HTTPException, Query
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
from sqlalchemy import text
from zeroque_common.db.session import get_engine, init_db, check_db, SessionLocal
from zeroque_common.middleware.usage_middleware import add_api_call_meter
from zeroque_common.billing.helpers import create_trade_invoice_if_applicable
from zeroque_common.middleware.idempotency import add_idempotency_middleware

SERVICE_NAME = "orders"
app = FastAPI(title="ZeroQue Orders Service", version="0.8.0")

# metering middleware
add_api_call_meter(app)

add_idempotency_middleware(app, routes=[
    ("POST", "/orders"),
])
# ---------- startup / health ----------
@app.on_event("startup")
def on_startup():
    get_engine()
    init_db()

@app.get("/health")
def health():
    return {"status": "ok", "service": SERVICE_NAME}

@app.get("/readiness")
def readiness():
    return {"service": SERVICE_NAME, "db": check_db(), "redis": True}

# ---------- models ----------
class NewOrderItem(BaseModel):
    sku: str
    qty: int

class NewOrder(BaseModel):
    tenant_id: str
    site_id: str
    store_id: str
    shopper_id: str
    currency: str = "GBP"
    items: List[NewOrderItem]

# ---------- helpers ----------
def _user_cc(db, user_id: str) -> Optional[str]:
    row = db.execute(
        text("SELECT cost_centre_id FROM user_cost_centres WHERE user_id=:u ORDER BY id ASC LIMIT 1"),
        {"u": user_id}
    ).first()
    return row[0] if row else None

def _budget_snapshot(db, cc_id: str):
    row = db.execute(text("""
        SELECT limit_minor, spent_minor, currency, hard_block
          FROM budgets
         WHERE cost_centre_id=:cc
         ORDER BY budget_id DESC
         LIMIT 1
    """), {"cc": cc_id}).first()
    if not row:
        return None
    return {
        "limit_minor": int(row[0]),
        "spent_minor": int(row[1]),
        "currency": row[2],
        "hard_block": bool(row[3]),
    }

def _update_daily(db, when: datetime, tenant_id: str, site_id: Optional[str], store_id: Optional[str], meter_code: str, delta: int):
    day = when.date()
    upd = db.execute(text("""
        UPDATE usage_aggregates_daily
           SET value = value + :delta
         WHERE day=:d AND tenant_id=:t
           AND COALESCE(site_id,'')=COALESCE(:s,'')
           AND COALESCE(store_id,'')=COALESCE(:st,'')
           AND meter_code=:m
    """), {"delta": delta, "d": day, "t": tenant_id, "s": site_id, "st": store_id, "m": meter_code}).rowcount
    if upd == 0:
        try:
            db.execute(text("""
                INSERT INTO usage_aggregates_daily(day, tenant_id, site_id, store_id, meter_code, value)
                VALUES(:d,:t,:s,:st,:m,:v)
            """), {"d": day, "t": tenant_id, "s": site_id, "st": store_id, "m": meter_code, "v": delta})
        except Exception:
            db.execute(text("""
                UPDATE usage_aggregates_daily
                   SET value = value + :delta
                 WHERE day=:d AND tenant_id=:t
                   AND COALESCE(site_id,'')=COALESCE(:s,'')
                   AND COALESCE(store_id,'')=COALESCE(:st,'')
                   AND meter_code=:m
            """), {"delta": delta, "d": day, "t": tenant_id, "s": site_id, "st": store_id, "m": meter_code})

def _approval_cover_and_consume(db, cost_centre_id: str, user_id: str, amount: int) -> bool:
    need = amount
    for scoped in (True, False):  # user-scoped first, then CC-wide
        rows = db.execute(text("""
            SELECT id, remaining_minor
              FROM approval_requests
             WHERE cost_centre_id=:cc AND status='approved'
               AND (:u IS NULL OR (user_scope_id = :u))
               AND (:scoped = TRUE AND user_scope_id IS NOT NULL OR :scoped = FALSE AND user_scope_id IS NULL)
             ORDER BY approved_at DESC NULLS LAST, id DESC
        """), {"cc": cost_centre_id, "u": user_id, "scoped": scoped}).all()
        for r in rows:
            if need <= 0:
                break
            ar_id, rem = int(r[0]), int(r[1] or 0)
            if rem <= 0:
                continue
            take = min(rem, need)
            db.execute(text("UPDATE approval_requests SET remaining_minor = remaining_minor - :take WHERE id=:id"),
                       {"take": take, "id": ar_id})
            need -= take
    return need == 0

def _apply_inventory_decrements(db, store_id: str, items: list[dict]):
    # items: [{"sku":..., "qty": int}, ...]
    for it in items:
        sku = it["sku"]; q = int(it["qty"])
        upd = db.execute(text("""
            UPDATE inventory SET qty = qty - :q WHERE store_id=:st AND sku=:s
        """), {"q": q, "st": store_id, "s": sku}).rowcount
        if upd == 0:
            db.execute(text("""
                INSERT INTO inventory(store_id, sku, qty) VALUES(:st, :s, :q)
            """), {"st": store_id, "s": sku, "q": -q})
        db.execute(text("""
            INSERT INTO inventory_movements(store_id, sku, delta, reason)
            VALUES(:st, :s, :d, 'sale')
        """), {"st": store_id, "s": sku, "d": -q})

# ---------- endpoints ----------
@app.post("/orders")
def create_order(payload: NewOrder = Body(...)):
    when = datetime.utcnow()
    with SessionLocal() as db:
        # 1) prices (strict)
        validated = []
        totals = 0
        for it in payload.items:
            row = db.execute(text("""
                SELECT unit_minor FROM prices
                 WHERE sku=:s AND currency=:c AND active = TRUE
            """), {"s": it.sku, "c": payload.currency}).first()
            if not row:
                raise HTTPException(status_code=400, detail=f"No active price for SKU {it.sku} {payload.currency}")
            unit = int(row[0])
            validated.append({"sku": it.sku, "qty": int(it.qty), "unit_minor": unit})
            totals += unit * int(it.qty)

        # 2) resolve CC + budget/approvals
        cc_id = _user_cc(db, payload.shopper_id)
        if not cc_id:
            raise HTTPException(status_code=400, detail="Shopper has no cost centre")

        snap = _budget_snapshot(db, cc_id)
        if not snap:
            raise HTTPException(status_code=400, detail="No budget configured")

        remaining = snap["limit_minor"] - snap["spent_minor"]
        if remaining < totals:
            if not _approval_cover_and_consume(db, cc_id, payload.shopper_id, totals - max(0, remaining)):
                raise HTTPException(status_code=403, detail="Budget would overspend (hard block); no approval cover")

        # 3) order header
        db.execute(text("""
            INSERT INTO orders(tenant_id, site_id, store_id, shopper_id, cost_centre_id,
                               provider, provider_order_id, total_minor, currency, status, occurred_at)
            VALUES(:t,:s,:st,:u,:cc,'manual','orders-api',:tot,:cur,'completed',:occ)
        """), {"t": payload.tenant_id, "s": payload.site_id, "st": payload.store_id, "u": payload.shopper_id,
               "cc": cc_id, "tot": totals, "cur": payload.currency, "occ": when})
        order_id = db.execute(text("SELECT currval(pg_get_serial_sequence('orders','order_id'))")).scalar()

        # 4) items
        for it in validated:
            name = db.execute(text("SELECT name FROM products WHERE sku=:sku"), {"sku": it["sku"]}).scalar() or it["sku"]
            db.execute(text("""
                INSERT INTO order_items(order_id, sku, name, qty, price_minor)
                VALUES(:oid,:sku,:name,:qty,:price)
            """), {"oid": order_id, "sku": it["sku"], "name": name, "qty": it["qty"], "price": it["unit_minor"]})

        # 5) ledger (debit/credit)
        db.execute(text("""
            INSERT INTO ledger_entries(tenant_id, account, entry_type, amount_minor, currency,
                                       cost_centre_id, site_id, store_id,
                                       reference_type, reference_id, description)
            VALUES(:t,'CostCentreSpend','debit',:amt,:cur,:cc,:s,:st,'order',:ref,'Orders API')
        """), {"t": payload.tenant_id, "amt": totals, "cur": payload.currency, "cc": cc_id,
               "s": payload.site_id, "st": payload.store_id, "ref": str(order_id)})
        db.execute(text("""
            INSERT INTO ledger_entries(tenant_id, account, entry_type, amount_minor, currency,
                                       cost_centre_id, site_id, store_id,
                                       reference_type, reference_id, description)
            VALUES(:t,'TenantClearing','credit',:amt,:cur,:cc,:s,:st,'order',:ref,'Orders API')
        """), {"t": payload.tenant_id, "amt": totals, "cur": payload.currency, "cc": cc_id,
               "s": payload.site_id, "st": payload.store_id, "ref": str(order_id)})

        # 6) budget spend
        db.execute(text("UPDATE budgets SET spent_minor = spent_minor + :amt WHERE cost_centre_id=:cc"),
                   {"amt": totals, "cc": cc_id})

        # 7) usage + unique shoppers
        db.execute(text("""
            INSERT INTO usage_events(tenant_id, site_id, store_id, meter_code, subject_id, value, occurred_at)
            VALUES(:t,:s,:st,'orders',:u,1,:occ)
        """), {"t": payload.tenant_id, "s": payload.site_id, "st": payload.store_id, "u": payload.shopper_id, "occ": when})
        _update_daily(db, when, payload.tenant_id, payload.site_id, payload.store_id, "orders", 1)

        exist = db.execute(text("""
            SELECT 1 FROM usage_events
             WHERE meter_code='unique_shoppers' AND tenant_id=:t
               AND COALESCE(site_id,'')=COALESCE(:s,'')
               AND COALESCE(store_id,'')=COALESCE(:st,'')
               AND subject_id=:u AND occurred_at::date = :d
             LIMIT 1
        """), {"t": payload.tenant_id, "s": payload.site_id, "st": payload.store_id, "u": payload.shopper_id, "d": when.date()}).first()
        if not exist:
            db.execute(text("""
                INSERT INTO usage_events(tenant_id, site_id, store_id, meter_code, subject_id, value, occurred_at)
                VALUES(:t,:s,:st,'unique_shoppers',:u,1,:occ)
            """), {"t": payload.tenant_id, "s": payload.site_id, "st": payload.store_id, "u": payload.shopper_id, "occ": when})
            _update_daily(db, when, payload.tenant_id, payload.site_id, payload.store_id, "unique_shoppers", 1)

        # 8) inventory decrement
        _apply_inventory_decrements(db, payload.store_id,
            [{"sku": it["sku"], "qty": it["qty"]} for it in validated]
        )

        # 9) trade invoice if tenant uses trade
        create_trade_invoice_if_applicable(
            db, payload.tenant_id, int(order_id), totals, payload.currency,
            payload.site_id, payload.store_id
        )

        db.commit()

        # dev receipt notification (separate commit on purpose)
        db.execute(text("""
            INSERT INTO notifications(tenant_id, target_user_id, channel, subject, body)
            VALUES(:t,:u,'dev','Order receipt', :body)
        """), {"t": payload.tenant_id, "u": payload.shopper_id,
               "body": f"Order {order_id} total {totals} {payload.currency}"})
        db.commit()

        return {"ok": True, "order_id": int(order_id), "total_minor": totals, "currency": payload.currency}

# distributor + list endpoints (unchanged)
@app.get("/orders/distributor")
def list_orders_for_distributor(distributor_tenant_id: str = Query(...), limit: int = Query(100)):
    with SessionLocal() as db:
        child_ids = [r[0] for r in db.execute(text("""
            SELECT child_tenant_id FROM tenant_links
             WHERE parent_tenant_id=:p AND relationship='distributor'
        """), {"p": distributor_tenant_id}).all()]
        if not child_ids:
            return []
        rows = db.execute(text("""
            SELECT order_id, tenant_id, site_id, store_id, shopper_id, total_minor, currency, status, occurred_at
              FROM orders
             WHERE tenant_id = ANY(:kids)
             ORDER BY occurred_at DESC
             LIMIT :l
        """), {"kids": child_ids, "l": limit}).all()
        return [
            {"order_id": int(r[0]), "tenant_id": r[1], "site_id": r[2], "store_id": r[3], "shopper_id": r[4],
             "total_minor": int(r[5]), "currency": r[6], "status": r[7], "occurred_at": str(r[8])}
            for r in rows
        ]

@app.get("/orders")
def list_orders(tenant_id: str = Query(...), limit: int = Query(50)):
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT order_id, tenant_id, site_id, store_id, shopper_id, total_minor, currency, status, occurred_at
              FROM orders
             WHERE tenant_id=:t
             ORDER BY occurred_at DESC
             LIMIT :l
        """), {"t": tenant_id, "l": limit}).all()
        return [
            {"order_id": int(r[0]), "tenant_id": r[1], "site_id": r[2], "store_id": r[3], "shopper_id": r[4],
             "total_minor": int(r[5]), "currency": r[6], "status": r[7], "occurred_at": str(r[8])}
            for r in rows
        ]

@app.get("/orders/{order_id}")
def get_order(order_id: int):
    with SessionLocal() as db:
        header = db.execute(text("""
            SELECT order_id, tenant_id, site_id, store_id, shopper_id, total_minor, currency, status, occurred_at
              FROM orders
             WHERE order_id=:id
        """), {"id": order_id}).first()
        if not header:
            raise HTTPException(status_code=404, detail="order not found")
        items = db.execute(text("""
            SELECT sku, name, qty, price_minor FROM order_items WHERE order_id=:id
        """), {"id": order_id}).all()
        return {
            "order": {"order_id": int(header[0]), "tenant_id": header[1], "site_id": header[2], "store_id": header[3],
                      "shopper_id": header[4], "total_minor": int(header[5]), "currency": header[6], "status": header[7],
                      "occurred_at": str(header[8])},
            "items": [{"sku": i[0], "name": i[1], "qty": int(i[2]), "price_minor": int(i[3])} for i in items]
        }