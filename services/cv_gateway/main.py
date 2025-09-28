from fastapi import FastAPI, Body, HTTPException, Query, Path
from pydantic import BaseModel
from typing import List, Optional
from sqlalchemy import text
from datetime import datetime
import json
from zeroque_common.db.session import get_engine, init_db, check_db, SessionLocal
from zeroque_common.middleware.usage_middleware import add_api_call_meter
from zeroque_common.billing.helpers import create_trade_invoice_if_applicable
from zeroque_common.middleware.idempotency import add_idempotency_middleware

SERVICE_NAME = "cv_gateway"
app = FastAPI(title="ZeroQue CV Gateway", version="0.8.0")

# metering middleware
add_api_call_meter(app)

add_idempotency_middleware(app, routes=[
    ("POST", "/cv/aifi/webhook/order"),
])
# ---------- startup / health ----------
@app.on_event("startup")
def on_startup():
    get_engine(); init_db()

@app.get("/health")
def health(): return {"status":"ok","service":SERVICE_NAME}

@app.get("/readiness")
def readiness(): return {"service": SERVICE_NAME, "db": check_db(), "redis": True}

# ---------- payload models ----------
class AiFiItem(BaseModel):
    sku: str
    name: str
    qty: int
    price_minor: int  # provider-sent; we validate against our active price

class AiFiOrder(BaseModel):
    provider_order_id: str
    # external IDs (optional if local IDs are provided)
    tenant_ext_id: Optional[str] = None
    site_ext_id: Optional[str] = None
    store_ext_id: Optional[str] = None
    user_ext_id: Optional[str] = None
    # local IDs (dev convenience)
    tenant_id: Optional[str] = None
    site_id: Optional[str] = None
    store_id: Optional[str] = None
    shopper_id: Optional[str] = None

    currency: str = "GBP"
    items: List[AiFiItem]
    occurred_at: Optional[datetime] = None

# ---------- helpers ----------
def _map_provider(db, provider: str, entity_type: str, external_id: str) -> Optional[str]:
    row = db.execute(text("""
        SELECT local_id
          FROM provider_mappings
         WHERE provider=:p AND entity_type=:et AND external_id=:eid
         LIMIT 1
    """), {"p": provider, "et": entity_type, "eid": external_id}).first()
    return row[0] if row else None

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
    for scoped in (True, False):
        rows = db.execute(text("""
            SELECT id, remaining_minor FROM approval_requests
             WHERE cost_centre_id=:cc AND status='approved'
               AND (:u IS NULL OR (user_scope_id = :u))
               AND (:scoped = TRUE AND user_scope_id IS NOT NULL OR :scoped = FALSE AND user_scope_id IS NULL)
             ORDER BY approved_at DESC NULLS LAST, id DESC
        """), {"cc": cost_centre_id, "u": user_id, "scoped": scoped}).all()
        for r in rows:
            if need <= 0: break
            ar_id, rem = int(r[0]), int(r[1] or 0)
            if rem <= 0: continue
            take = min(rem, need)
            db.execute(text("UPDATE approval_requests SET remaining_minor = remaining_minor - :take WHERE id=:id"),
                       {"take": take, "id": ar_id})
            need -= take
    return need == 0

def _review_unknown_item(db, provider: str, tenant_id: str, site_id: str, store_id: str,
                         external_sku: str, name: str, qty: int, price_minor: int, payload_fragment: dict):
    db.execute(text("""
        INSERT INTO cv_unknown_item_reviews(provider, tenant_id, site_id, store_id,
                                            external_sku, name, qty, price_minor, payload_json, status)
        VALUES(:p,:t,:si,:st,:esk,:n,:q,:pm,:pl,'pending')
    """), {"p": provider, "t": tenant_id, "si": site_id, "st": store_id,
           "esk": external_sku, "n": name, "q": qty, "pm": price_minor,
           "pl": json.dumps(payload_fragment)})

def _apply_inventory_decrements(db, store_id: str, items: list[dict]):
    for it in items:
        sku = it["sku"]; q = int(it["qty"])
        upd = db.execute(text("UPDATE inventory SET qty = qty - :q WHERE store_id=:st AND sku=:s"),
                         {"q": q, "st": store_id, "s": sku}).rowcount
        if upd == 0:
            db.execute(text("INSERT INTO inventory(store_id, sku, qty) VALUES(:st, :s, :q)"),
                       {"st": store_id, "s": sku, "q": -q})
        db.execute(text("INSERT INTO inventory_movements(store_id, sku, delta, reason) VALUES(:st, :s, :d, 'sale')"),
                   {"st": store_id, "s": sku, "d": -q})

# ---------- webhook ----------
@app.post("/cv/aifi/webhook/order")
def aifi_order(payload: AiFiOrder = Body(...)):
    when = payload.occurred_at or datetime.utcnow()
    with SessionLocal() as db:
        # 1) resolve local IDs (prefer local IDs when provided)
        tenant_id = payload.tenant_id or (payload.tenant_ext_id and _map_provider(db, "aifi", "tenant", payload.tenant_ext_id))
        site_id   = payload.site_id   or (payload.site_ext_id   and _map_provider(db, "aifi", "site",   payload.site_ext_id))
        store_id  = payload.store_id  or (payload.store_ext_id  and _map_provider(db, "aifi", "store",  payload.store_ext_id))
        shopper_id= payload.shopper_id or (payload.user_ext_id   and _map_provider(db, "aifi", "user",   payload.user_ext_id))

        if not all([tenant_id, site_id, store_id, shopper_id]):
            raise HTTPException(status_code=400, detail="Mapping failed (tenant/site/store/user). Provide local IDs or external IDs + provider_mappings.")

        # 2) shopper cost centre
        cc_row = db.execute(text("""
            SELECT cost_centre_id FROM user_cost_centres
             WHERE user_id=:u ORDER BY id ASC LIMIT 1
        """), {"u": shopper_id}).first()
        cost_centre_id = cc_row[0] if cc_row else None

        # 3) validate items: product+active price. If unknown → record review(s) and 202.
        unknown = []
        validated = []
        for it in payload.items:
            prod = db.execute(text("SELECT 1 FROM products WHERE sku=:s AND active=TRUE"), {"s": it.sku}).first()
            price = db.execute(text("""
                SELECT unit_minor FROM prices WHERE sku=:s AND currency=:c AND active=TRUE
            """), {"s": it.sku, "c": payload.currency}).first()
            if not prod or not price:
                unknown.append({"sku": it.sku, "name": it.name, "qty": it.qty, "price_minor": it.price_minor})
                continue
            validated.append({"sku": it.sku, "qty": int(it.qty), "unit_minor": int(price[0])})

        if unknown:
            for u in unknown:
                _review_unknown_item(db, "aifi", tenant_id, site_id, store_id,
                                     u["sku"], u["name"], int(u["qty"]), int(u["price_minor"]), u)
            db.commit()
            return {"ok": False, "status": 202, "reason": "reconciliation_required",
                    "unknown_count": len(unknown), "items": unknown}

        total_minor = sum(i["qty"] * i["unit_minor"] for i in validated)

        # 4) budget/approvals
        if cost_centre_id:
            b = db.execute(text("""
                SELECT limit_minor, spent_minor FROM budgets
                 WHERE cost_centre_id=:cc ORDER BY budget_id DESC LIMIT 1
            """), {"cc": cost_centre_id}).first()
            if b:
                remaining = int(b[0]) - int(b[1])
                if remaining < total_minor:
                    need = total_minor - max(0, remaining)
                    if not _approval_cover_and_consume(db, cost_centre_id, shopper_id, need):
                        raise HTTPException(status_code=403, detail="Budget would overspend (hard block); no approval cover")

        # 5) order + items
        db.execute(text("""
            INSERT INTO orders(tenant_id, site_id, store_id, shopper_id, cost_centre_id,
                               provider, provider_order_id, total_minor, currency, status, occurred_at)
            VALUES(:t,:si,:st,:u,:cc,'aifi',:po,:tot,:cur,'completed',:occ)
        """), {"t": tenant_id, "si": site_id, "st": store_id, "u": shopper_id, "cc": cost_centre_id,
               "po": payload.provider_order_id, "tot": total_minor, "cur": payload.currency, "occ": when})
        order_id = db.execute(text("SELECT currval(pg_get_serial_sequence('orders','order_id'))")).scalar()

        for it in validated:
            # name stored as SKU for now; you can join products for friendly name if you like
            db.execute(text("""
                INSERT INTO order_items(order_id, sku, name, qty, price_minor)
                VALUES(:oid,:sku,:name,:qty,:price)
            """), {"oid": order_id, "sku": it["sku"], "name": it["sku"], "qty": it["qty"], "price": it["unit_minor"]})

        # 6) ledger
        db.execute(text("""
            INSERT INTO ledger_entries(tenant_id, account, entry_type, amount_minor, currency,
                                       cost_centre_id, site_id, store_id,
                                       reference_type, reference_id, description)
            VALUES(:t,'CostCentreSpend','debit',:amt,:cur,:cc,:si,:st,'order',:ref,'CV order')
        """), {"t": tenant_id, "amt": total_minor, "cur": payload.currency, "cc": cost_centre_id,
               "si": site_id, "st": store_id, "ref": str(order_id)})
        db.execute(text("""
            INSERT INTO ledger_entries(tenant_id, account, entry_type, amount_minor, currency,
                                       cost_centre_id, site_id, store_id,
                                       reference_type, reference_id, description)
            VALUES(:t,'TenantClearing','credit',:amt,:cur,:cc,:si,:st,'order',:ref,'CV order')
        """), {"t": tenant_id, "amt": total_minor, "cur": payload.currency, "cc": cost_centre_id,
               "si": site_id, "st": store_id, "ref": str(order_id)})

        # 7) budget spend
        if cost_centre_id:
            db.execute(text("UPDATE budgets SET spent_minor = spent_minor + :amt WHERE cost_centre_id=:cc"),
                       {"amt": total_minor, "cc": cost_centre_id})

        # 8) usage (+ unique shoppers)
        db.execute(text("""
            INSERT INTO usage_events(tenant_id, site_id, store_id, meter_code, subject_id, value, occurred_at)
            VALUES(:t,:si,:st,'orders',:u,1,:occ)
        """), {"t": tenant_id, "si": site_id, "st": store_id, "u": shopper_id, "occ": when})
        _update_daily(db, when, tenant_id, site_id, store_id, "orders", 1)

        exist = db.execute(text("""
            SELECT 1 FROM usage_events
             WHERE meter_code='unique_shoppers' AND tenant_id=:t
               AND COALESCE(site_id,'')=COALESCE(:si,'')
               AND COALESCE(store_id,'')=COALESCE(:st,'')
               AND subject_id=:u AND occurred_at::date = :d
             LIMIT 1
        """), {"t": tenant_id, "si": site_id, "st": store_id, "u": shopper_id, "d": when.date()}).first()
        if not exist:
            db.execute(text("""
                INSERT INTO usage_events(tenant_id, site_id, store_id, meter_code, subject_id, value, occurred_at)
                VALUES(:t,:si,:st,'unique_shoppers',:u,1,:occ)
            """), {"t": tenant_id, "si": site_id, "st": store_id, "u": shopper_id, "occ": when})
            _update_daily(db, when, tenant_id, site_id, store_id, "unique_shoppers", 1)

        # 9) inventory decrement + trade invoice
        _apply_inventory_decrements(db, store_id, [{"sku": it["sku"], "qty": it["qty"]} for it in validated])
        create_trade_invoice_if_applicable(db, tenant_id, int(order_id), total_minor, payload.currency, site_id, store_id)
        db.commit()

        # 10) dev receipt notification
        db.execute(text("""
            INSERT INTO notifications(tenant_id, target_user_id, channel, subject, body)
            VALUES(:t,:u,'dev','Order receipt', :body)
        """), {"t": tenant_id, "u": shopper_id,
               "body": f"Order {order_id} total {total_minor} {payload.currency}"})
        db.commit()

        return {"ok": True, "order_id": int(order_id), "total_minor": total_minor, "currency": payload.currency}

# ---------- review APIs ----------
@app.get("/cv/reviews")
def list_reviews(tenant_id: str = Query(...), status: str = Query("pending"), limit: int = Query(50)):
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT id, provider, external_sku, name, qty, price_minor, status, created_at
              FROM cv_unknown_item_reviews
             WHERE tenant_id=:t AND status=:s
             ORDER BY id DESC
             LIMIT :l
        """), {"t": tenant_id, "s": status, "l": limit}).all()
        return [{
            "id": int(r[0]), "provider": r[1], "external_sku": r[2], "name": r[3],
            "qty": int(r[4]), "price_minor": int(r[5] or 0), "status": r[6], "created_at": str(r[7])
        } for r in rows]

class ReviewResolvePayload(BaseModel):
    mapped_sku: Optional[str] = None
    status: str = "resolved"  # resolved|ignored
    notes: Optional[str] = None

@app.post("/cv/reviews/{review_id}/resolve")
def resolve_review(review_id: int = Path(...), payload: ReviewResolvePayload = Body(...)):
    if payload.status not in ("resolved", "ignored"):
        raise HTTPException(status_code=400, detail="invalid status")
    with SessionLocal() as db:
        db.execute(text("""
            UPDATE cv_unknown_item_reviews
               SET status=:st, mapped_sku=:ms, notes=:n
             WHERE id=:id
        """), {"st": payload.status, "ms": payload.mapped_sku, "n": payload.notes, "id": review_id})
        db.commit()
        return {"id": review_id, "status": payload.status}