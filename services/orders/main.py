# services/orders/main.py
from fastapi import FastAPI, Body, HTTPException, Query, Path
from pydantic import BaseModel
from typing import List, Optional, Literal
from datetime import datetime
from sqlalchemy import text
import os, requests, logging

from zeroque_common.db.session import get_engine, init_db, check_db, SessionLocal
from zeroque_common.middleware.usage_middleware import add_api_call_meter
from zeroque_common.billing.helpers import create_trade_invoice_if_applicable
from zeroque_common.middleware.idempotency import add_idempotency_middleware
from zeroque_common.events.integration import publish_order_created, publish_order_completed
from zeroque_common.events.bus import EventBus, EventType, Event
from zeroque_common.events.celery_app import celery_app
from zeroque_common.observability import setup_logging, init_metrics, init_insights, add_observability_middleware

SERVICE_NAME = "orders"
app = FastAPI(title="ZeroQue Orders Service", version="0.9.2")

# ---- observability ----
logger = setup_logging(SERVICE_NAME, "0.9.2")
metrics = init_metrics(SERVICE_NAME)
insights = init_insights(SERVICE_NAME, "0.9.2")

# ---- middleware ----
add_observability_middleware(app, SERVICE_NAME)
add_api_call_meter(app)
add_idempotency_middleware(app, routes=[("POST", "/orders")])

# ---- config ----
PAYMENTS_BASE = os.getenv("PAYMENTS_BASE", "http://localhost:8209")
BILLING_BASE  = os.getenv("BILLING_BASE",  "http://localhost:8206")

# ---- event bus ----
event_bus = EventBus()

# ---- lifecycle ----
@app.on_event("startup")
def on_startup():
    get_engine(); init_db()
    logger.info("Orders service started")

@app.get("/health")
def health(): return {"status": "ok", "service": SERVICE_NAME}

@app.get("/readiness")
def readiness(): return {"service": SERVICE_NAME, "db": check_db(), "redis": True}

# Observability endpoints
@app.get("/metrics")
def get_metrics():
    """Get service metrics"""
    return metrics.get_metrics_summary()

@app.get("/insights")
def get_service_insights():
    """Get service insights"""
    service_insights = insights.get_insights()
    return {
        "service_name": service_insights.service_name,
        "timestamp": service_insights.timestamp.isoformat(),
        "health_status": service_insights.health_status,
        "performance_metrics": service_insights.performance_metrics,
        "business_metrics": service_insights.business_metrics,
        "error_rate": service_insights.error_rate,
        "uptime_seconds": service_insights.uptime_seconds,
        "version": service_insights.version,
        "environment": service_insights.environment
    }

@app.get("/health/detailed")
def get_detailed_health():
    """Get detailed health status"""
    return insights.get_health_summary()

# ---- models ----
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
    payment_method: Optional[Literal["stripe","trade"]] = None

# ---- helpers ----
def _user_cc(db, user_id: str) -> Optional[str]:
    row = db.execute(
        text("""SELECT cost_centre_id
                  FROM user_cost_centres
                 WHERE user_id=:u
              ORDER BY id ASC LIMIT 1"""),
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
    """Upsert into daily usage aggregate; resilient to races."""
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
                   AND meter_code = :m
            """), {"delta": delta, "d": day, "t": tenant_id, "s": site_id, "st": store_id, "m": meter_code})

def _approval_cover_and_consume(db, cost_centre_id: str, user_id: str, amount: int) -> bool:
    """Consume from approvals (user-scoped first, then CC-wide) to cover 'amount' of overspend."""
    need = amount
    for scoped in (True, False):
        rows = db.execute(text("""
            SELECT id, remaining_minor
              FROM approval_requests
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
            db.execute(text("""
                UPDATE approval_requests
                   SET remaining_minor = remaining_minor - :take
                 WHERE id=:id
            """), {"take": take, "id": ar_id})
            need -= take
    return need == 0

def _apply_inventory_decrements(db, store_id: str, items: list[dict]):
    """Decrement inventory and append 'sale' movements."""
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

# ---- endpoints ----
@app.post("/orders")
def create_order(payload: NewOrder = Body(...)):
    """
    Create an order. If payment method is 'stripe', an external payment intent is created and the order
    is set to payment_pending; complete card on the client and then call POST /orders/{id}/settle.
    If method 'trade' (default), the order is completed immediately and a Trade invoice is posted.
    """
    when = datetime.utcnow()
    with SessionLocal() as db:
        logger.info(f"order_create_started tenant={payload.tenant_id} site={payload.site_id} store={payload.store_id} shopper={payload.shopper_id} items={len(payload.items)} method={payload.payment_method or '-'}")

        # 1) price validation using new pricing engine
        validated = []
        totals = 0
        pricing_context = {
            "user_role": "customer",  # TODO: Get actual user role from user service
            "order_time": when.isoformat()
        }
        
        for it in payload.items:
            # Try to get calculated price from pricing service
            try:
                import httpx
                pricing_response = httpx.post(
                    f"{os.getenv('PRICING_BASE_URL', 'http://localhost:8209')}/pricing/calculate",
                    json={
                        "store_id": payload.store_id,
                        "sku": it.sku,
                        "user_id": payload.shopper_id,
                        "currency": payload.currency,
                        "quantity": int(it.qty),
                        "force_recalculate": False
                    },
                    timeout=5.0
                )
                if pricing_response.status_code == 200:
                    pricing_data = pricing_response.json()
                    unit = pricing_data["final_price_gbp"]  # Price in pounds
                    base_price = pricing_data.get("base_price_gbp", pricing_data["final_price_gbp"])  # Price in pounds
                    logger.info(f"pricing_engine_used sku={it.sku} base={base_price} final={unit} rules={len(pricing_data.get('applied_rules', []))} promos={len(pricing_data.get('applied_promotions', []))}")
                else:
                    raise Exception(f"Pricing service error: {pricing_response.status_code}")
            except Exception as e:
                logger.warning(f"pricing_service_fallback sku={it.sku} error={str(e)}")
                # Fallback to old pricing logic
                row = db.execute(text("""
                    SELECT unit_minor FROM prices
                     WHERE sku=:s AND currency=:c AND active = TRUE
                """), {"s": it.sku, "c": payload.currency}).first()
                if not row:
                    logger.warning(f"no_active_price sku={it.sku} currency={payload.currency}")
                    raise HTTPException(status_code=400, detail=f"No active price for SKU {it.sku} {payload.currency}")
                unit = float(row[0])  # Now in pounds
            
            validated.append({"sku": it.sku, "qty": int(it.qty), "unit_minor": unit})
            totals += unit * int(it.qty)
        logger.info(f"order_price_validated total_minor={totals} currency={payload.currency}")

        # 2) budget / approvals
        cc_id = _user_cc(db, payload.shopper_id)
        if not cc_id:
            raise HTTPException(status_code=400, detail="Shopper has no cost centre")
        snap = _budget_snapshot(db, cc_id)
        if not snap:
            raise HTTPException(status_code=400, detail="No budget configured")

        remaining = snap["limit_minor"] - snap["spent_minor"]
        overspend = max(0, totals - max(0, remaining))
        if overspend > 0:
            covered = _approval_cover_and_consume(db, cc_id, payload.shopper_id, overspend)
            if not covered:
                logger.info(f"budget_blocked cc={cc_id} remaining={remaining} need={totals}")
                raise HTTPException(status_code=403, detail="Budget would overspend (hard block); no approval cover")
        logger.info(f"budget_ok cc={cc_id} remaining_before={remaining} total={totals}")

        # 3) decide method: explicit > tenant pref > default trade
        method = payload.payment_method
        if method is None:
            pm = db.execute(text("SELECT method FROM payment_preferences WHERE tenant_id=:t"),
                            {"t": payload.tenant_id}).scalar()
            method = (pm or "trade")

        # ---- STRIPE path ----
        if method == "stripe":
            db.execute(text("""
                INSERT INTO orders(tenant_id, site_id, store_id, shopper_id, cost_centre_id,
                                   provider, provider_order_id, total_minor, currency, status, occurred_at)
                VALUES(:t,:s,:st,:u,:cc,'stripe','orders-api',:tot,:cur,'payment_pending',:occ)
            """), {"t": payload.tenant_id, "s": payload.site_id, "st": payload.store_id,
                   "u": payload.shopper_id, "cc": cc_id, "tot": totals, "cur": payload.currency, "occ": when})
            order_id = db.execute(text("SELECT currval(pg_get_serial_sequence('orders','order_id'))")).scalar()

            for it in validated:
                name = db.execute(text("SELECT name FROM products WHERE sku=:sku"), {"sku": it["sku"]}).scalar() or it["sku"]
                db.execute(text("""
                    INSERT INTO order_items(order_id, sku, name, qty, price_minor)
                    VALUES(:oid,:sku,:name,:qty,:price)
                """), {"oid": order_id, "sku": it["sku"], "name": name, "qty": it["qty"], "price": it["unit_minor"]})
            db.commit()

            try:
                r = requests.post(
                    f"{PAYMENTS_BASE}/payments/stripe/payment-intent",
                    json={
                        "tenant_id": payload.tenant_id,
                        "order_id": str(order_id),
                        "site_id": payload.site_id,
                        "amount_minor": totals,
                        "currency": payload.currency
                    },
                    timeout=10
                )
                r.raise_for_status()
                pi = r.json()
            except Exception as e:
                logger.exception(f"stripe_pi_error order_id={order_id} err={str(e)}")
                db.execute(text("UPDATE orders SET status='payment_failed' WHERE order_id=:id"), {"id": order_id})
                db.commit()
                raise HTTPException(status_code=502, detail=f"stripe error: {e}")

            db.execute(
                text("UPDATE orders SET provider_order_id=:pi WHERE order_id=:id"),
                {"pi": pi.get("payment_intent_id"), "id": order_id},
            )
            db.commit()
            logger.info(f"order_created_stripe order_id={order_id} total={totals} currency={payload.currency} pi={pi.get('payment_intent_id')}")

            return {
                "ok": True,
                "order_id": int(order_id),
                "status": "payment_pending",
                "total_gbp": totals,
                "currency": payload.currency,
                "payment": {
                    "provider": "stripe",
                    "payment_intent_id": pi.get("payment_intent_id"),
                    "client_secret": pi.get("client_secret"),
                    "status": pi.get("status"),
                }
            }

        # ---- TRADE path ----
        db.execute(text("""
            INSERT INTO orders(tenant_id, site_id, store_id, shopper_id, cost_centre_id,
                               provider, provider_order_id, total_minor, currency, status, occurred_at)
            VALUES(:t,:s,:st,:u,:cc,'manual','orders-api',:tot,:cur,'completed',:occ)
        """), {"t": payload.tenant_id, "s": payload.site_id, "st": payload.store_id, "u": payload.shopper_id,
               "cc": cc_id, "tot": totals, "cur": payload.currency, "occ": when})
        order_id = db.execute(text("SELECT currval(pg_get_serial_sequence('orders','order_id'))")).scalar()

        for it in validated:
            name = db.execute(text("SELECT name FROM products WHERE sku=:sku"), {"sku": it["sku"]}).scalar() or it["sku"]
            db.execute(text("""
                INSERT INTO order_items(order_id, sku, name, qty, price_minor)
                VALUES(:oid,:sku,:name,:qty,:price)
            """), {"oid": order_id, "sku": it["sku"], "name": name, "qty": it["qty"], "price": it["unit_minor"]})

        # Ledger (CC spend -> Tenant clearing)
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

        # Budget spend
        db.execute(text("UPDATE budgets SET spent_minor = spent_minor + :amt WHERE cost_centre_id=:cc"),
                   {"amt": totals, "cc": cc_id})

        # Usage events + daily agg
        db.execute(text("""
            INSERT INTO usage_events(tenant_id, site_id, store_id, meter_code, subject_id, value, occurred_at)
            VALUES(:t,:s,:st,'orders',:u,1,:occ)
        """), {"t": payload.tenant_id, "s": payload.site_id, "st": payload.store_id, "u": payload.shopper_id, "occ": when})
        _update_daily(db, when, payload.tenant_id, payload.site_id, payload.store_id, "orders", 1)

        # Unique shopper of day
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

        # Inventory decrements
        _apply_inventory_decrements(db, payload.store_id, [{"sku": it["sku"], "qty": it["qty"]} for it in validated])

        # Trade invoice via Billing helper
        create_trade_invoice_if_applicable(
            db, payload.tenant_id, int(order_id), totals, payload.currency,
            payload.site_id, payload.store_id
        )

        db.commit()

        # Dev notification
        db.execute(text("""
            INSERT INTO notifications(tenant_id, target_user_id, channel, subject, body)
            VALUES(:t,:u,'dev','Order receipt', :body)
        """), {"t": payload.tenant_id, "u": payload.shopper_id,
               "body": f"Order {order_id} total {totals} {payload.currency}"})
        db.commit()

        # Publish order events
        try:
            # Publish order created event
            order_created_event = Event(
                event_type=EventType.ORDER_CREATED,
                tenant_id=payload.tenant_id,
                site_id=payload.site_id,
                store_id=payload.store_id,
                user_id=payload.shopper_id,
                data={
                    "order_id": int(order_id),
                    "total_gbp": totals,
                    "currency": payload.currency,
                    "payment_method": "trade",
                    "items": validated
                },
                metadata={"service": "orders", "version": "0.9.2"}
            )
            
            # Publish order completed event
            order_completed_event = Event(
                event_type=EventType.ORDER_COMPLETED,
                tenant_id=payload.tenant_id,
                site_id=payload.site_id,
                store_id=payload.store_id,
                user_id=payload.shopper_id,
                data={
                    "order_id": int(order_id),
                    "total_gbp": totals,
                    "currency": payload.currency,
                    "payment_method": "trade",
                    "status": "completed"
                },
                metadata={"service": "orders", "version": "0.9.2"}
            )
            
            # Send events to Celery for async processing
            celery_app.send_task(
                "zeroque_common.events.tasks.process_order_event",
                args=[order_created_event.__dict__],
                queue="orders"
            )
            
            celery_app.send_task(
                "zeroque_common.events.tasks.process_order_event", 
                args=[order_completed_event.__dict__],
                queue="orders"
            )
            
            logger.info(f"order_events_published order_id={order_id} events=2")
            
        except Exception as e:
            logger.warning(f"Failed to publish order events: {str(e)}")

        logger.info(f"order_created_trade order_id={order_id} total={totals} currency={payload.currency}")
        return {
            "ok": True,
            "order_id": int(order_id),
            "total_gbp": totals,
            "currency": payload.currency,
            "payment": {"provider": "trade"}
        }

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
             "total_gbp": float(r[5]), "currency": r[6], "status": r[7], "occurred_at": str(r[8])}
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
                      "shopper_id": header[4], "total_gbp": float(header[5]), "currency": header[6], "status": header[7],
                      "occurred_at": str(header[8])},
            "items": [{"sku": i[0], "name": i[1], "qty": int(i[2]), "price_gbp": float(i[3])} for i in items]
        }

@app.post("/orders/{order_id}/settle")
def settle_order(order_id: int = Path(...)):
    """
    Finalize a Stripe order after payment succeeds (idempotent).
    """
    when = datetime.utcnow()
    with SessionLocal() as db:
        h = db.execute(text("""
            SELECT order_id, tenant_id, site_id, store_id, shopper_id, cost_centre_id, total_minor, currency, status
              FROM orders WHERE order_id=:id
        """), {"id": order_id}).first()
        if not h:
            raise HTTPException(status_code=404, detail="order not found")
        if h[8] == "completed":
            return {"ok": True, "order_id": order_id, "status": "completed"}  # idempotent
        if h[8] != "payment_pending":
            raise HTTPException(status_code=409, detail=f"order not pending; status={h[8]}")

        tenant_id, site_id, store_id, shopper_id, cc_id, total_minor, currency = h[1], h[2], h[3], h[4], h[5], int(h[6]), h[7]

        # Ledger
        db.execute(text("""
            INSERT INTO ledger_entries(tenant_id, account, entry_type, amount_minor, currency,
                                       cost_centre_id, site_id, store_id,
                                       reference_type, reference_id, description)
            VALUES(:t,'CostCentreSpend','debit',:amt,:cur,:cc,:s,:st,'order',:ref,'Stripe order')
        """), {"t": tenant_id, "amt": total_minor, "cur": currency, "cc": cc_id,
               "s": site_id, "st": store_id, "ref": str(order_id)})
        db.execute(text("""
            INSERT INTO ledger_entries(tenant_id, account, entry_type, amount_minor, currency,
                                       cost_centre_id, site_id, store_id,
                                       reference_type, reference_id, description)
            VALUES(:t,'TenantClearing','credit',:amt,:cur,:cc,:s,:st,'order',:ref,'Stripe order')
        """), {"t": tenant_id, "amt": total_minor, "cur": currency, "cc": cc_id,
               "s": site_id, "st": store_id, "ref": str(order_id)})

        # Budget spend
        db.execute(text("UPDATE budgets SET spent_minor = spent_minor + :amt WHERE cost_centre_id=:cc"),
                   {"amt": total_minor, "cc": cc_id})

        # Usage + daily aggregates
        db.execute(text("""
            INSERT INTO usage_events(tenant_id, site_id, store_id, meter_code, subject_id, value, occurred_at)
            VALUES(:t,:s,:st,'orders',:u,1,:occ)
        """), {"t": tenant_id, "s": site_id, "st": store_id, "u": shopper_id, "occ": when})
        _update_daily(db, when, tenant_id, site_id, store_id, "orders", 1)

        # Unique shopper of day
        exist = db.execute(text("""
            SELECT 1 FROM usage_events
             WHERE meter_code='unique_shoppers' AND tenant_id=:t
               AND COALESCE(site_id,'')=COALESCE(:s,'')
               AND COALESCE(store_id,'')=COALESCE(:st,'')
               AND subject_id=:u AND occurred_at::date = :d
             LIMIT 1
        """), {"t": tenant_id, "s": site_id, "st": store_id, "u": shopper_id, "d": when.date()}).first()
        if not exist:
            db.execute(text("""
                INSERT INTO usage_events(tenant_id, site_id, store_id, meter_code, subject_id, value, occurred_at)
                VALUES(:t,:s,:st,'unique_shoppers',:u,1,:occ)
            """), {"t": tenant_id, "s": site_id, "st": store_id, "u": shopper_id, "occ": when})
            _update_daily(db, when, tenant_id, site_id, store_id, "unique_shoppers", 1)

        # Inventory out
        items = db.execute(text("SELECT sku, qty FROM order_items WHERE order_id=:id"), {"id": order_id}).all()
        _apply_inventory_decrements(db, store_id, [{"sku": i[0], "qty": int(i[1])} for i in items])

        # Mark done
        db.execute(text("UPDATE orders SET status='completed' WHERE order_id=:id"), {"id": order_id})
        db.commit()
        
        # Publish order completed event
        try:
            import asyncio
            asyncio.create_task(publish_order_completed(
                tenant_id=tenant_id,
                order_id=order_id,
                site_id=site_id,
                store_id=store_id,
                user_id=shopper_id,
                total_minor=total_minor,
                currency=currency,
                payment_method="stripe"
            ))
        except Exception as e:
            logger.warning(f"Failed to publish order completed event: {str(e)}")
        
        logger.info(f"order_settled order_id={order_id} total={total_minor} currency={currency}")
        return {"ok": True, "order_id": order_id, "status": "completed"}