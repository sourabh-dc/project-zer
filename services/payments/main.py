# services/payments/main.py
import os
import json
from fastapi import FastAPI, Body, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import text
from zeroque_common.db.session import get_engine, init_db, check_db, SessionLocal
import requests
import stripe
STRIPE_API_KEY = os.getenv("STRIPE_API_KEY", "")  # test key
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")

SERVICE_NAME = "payments"
app = FastAPI(title="ZeroQue Payments Service", version="0.1.0")
ORDERS_BASE = os.getenv("ORDERS_BASE", "http://localhost:8208")

@app.on_event("startup")
def on_startup():
    get_engine(); init_db()
    if STRIPE_API_KEY:
        stripe.api_key = STRIPE_API_KEY

@app.get("/health")
def health(): return {"status":"ok","service":SERVICE_NAME}

@app.get("/readiness")
def readiness(): return {"service":SERVICE_NAME,"db":check_db(),"stripe":bool(STRIPE_API_KEY)}

class EnsureCustomer(BaseModel):
    tenant_id: str
    email: str | None = None
    name: str | None = None

@app.post("/payments/stripe/webhook")
async def stripe_events(request: Request):
    payload = await request.json()

    # quick extract – handle either payment_intent.* or charge.succeeded
    etype = payload.get("type")
    obj   = payload.get("data", {}).get("object", {})
    payment_intent_id = obj.get("payment_intent") or obj.get("id")
    charge_id = obj.get("id") if etype == "charge.succeeded" else None
    amount_minor = obj.get("amount", obj.get("amount_received"))
    currency = (obj.get("currency") or "gbp").upper()

    if not payment_intent_id:
        return {"ok": True}  # ignore unknown event shapes

    with SessionLocal() as db:
        # find order_id + tenant/site you stored when creating PI
        row = db.execute(text("""
            SELECT order_id, tenant_id, site_id
              FROM stripe_charges
             WHERE payment_intent_id=:pi
             ORDER BY id DESC LIMIT 1
        """), {"pi": payment_intent_id}).first()

        # If not found yet (first event), create a stub row; orders service saved PI on order
        if not row:
            # try to recover order from metadata if you stored it, else leave order_id null
            order_id = obj.get("metadata", {}).get("order_id")
            tenant_id = obj.get("metadata", {}).get("tenant_id")
            site_id = obj.get("metadata", {}).get("site_id")
            db.execute(text("""
                INSERT INTO stripe_charges(tenant_id, order_id, site_id, payment_intent_id, charge_id,
                                           amount_minor, currency, status, raw)
                VALUES(:t,:o,:si,:pi,:ch,:amt,:cur,:st, CAST(:raw AS JSONB))
            """), {
                "t": tenant_id, "o": order_id, "si": site_id, "pi": payment_intent_id, "ch": charge_id,
                "amt": int(amount_minor or 0), "cur": currency, "st": obj.get("status","unknown"),
                "raw": json.dumps(payload)
            })
            db.commit()
        else:
            order_id, tenant_id, site_id = row[0], row[1], row[2]
            db.execute(text("""
                UPDATE stripe_charges
                   SET charge_id = COALESCE(:ch, charge_id),
                       amount_minor = COALESCE(:amt, amount_minor),
                       currency = :cur,
                       status = :st,
                       raw = CAST(:raw AS JSONB),
                       updated_at = NOW()
                 WHERE payment_intent_id = :pi
            """), {
                "ch": charge_id, "amt": int(amount_minor or 0), "cur": currency,
                "st": obj.get("status","unknown"), "raw": json.dumps(payload), "pi": payment_intent_id
            })
            db.commit()

        # Settle order on success
        succeeded = (
            etype == "payment_intent.succeeded" or
            (etype == "charge.succeeded" and obj.get("paid") is True)
        )
        if succeeded and order_id:
            try:
                requests.post(f"{ORDERS_BASE}/orders/{order_id}/settle", timeout=5)
            except Exception:
                pass

    return {"ok": True}

@app.post("/payments/stripe/customers")
def ensure_customer(payload: EnsureCustomer):
    if not STRIPE_API_KEY: raise HTTPException(500, "STRIPE_API_KEY not set")
    with SessionLocal() as db:
        row = db.execute(text("SELECT stripe_customer_id FROM stripe_customers WHERE tenant_id=:t"),
                         {"t": payload.tenant_id}).first()
        if row:
            return {"tenant_id": payload.tenant_id, "stripe_customer_id": row[0], "exists": True}

        cust = stripe.Customer.create(
            email=payload.email,
            name=payload.name or payload.tenant_id,
            metadata={"tenant_id": payload.tenant_id}
        )
        db.execute(text("""
            INSERT INTO stripe_customers(tenant_id, stripe_customer_id)
            VALUES(:t,:cid)
        """), {"t": payload.tenant_id, "cid": cust["id"]})
        db.commit()
        return {"tenant_id": payload.tenant_id, "stripe_customer_id": cust["id"], "created": True}

class CreatePI(BaseModel):
    tenant_id: str
    order_id: str
    amount_minor: int
    currency: str = "GBP"

@app.post("/payments/stripe/payment-intent")
def create_payment_intent(payload: CreatePI):
    if not STRIPE_API_KEY: raise HTTPException(500, "STRIPE_API_KEY not set")
    if payload.amount_minor <= 0: raise HTTPException(400, "amount must be > 0")
    with SessionLocal() as db:
        # ensure customer
        row = db.execute(text("SELECT stripe_customer_id FROM stripe_customers WHERE tenant_id=:t"),
                         {"t": payload.tenant_id}).first()
        if not row:
            raise HTTPException(400, "stripe customer missing for tenant (call /customers first)")
        customer_id = row[0]

        pi = stripe.PaymentIntent.create(
            amount=payload.amount_minor,
            currency=payload.currency.lower(),
            customer=customer_id,
            automatic_payment_methods={"enabled": True},
            metadata={"tenant_id": payload.tenant_id, "order_id": payload.order_id}
        )

        db.execute(text("""
            INSERT INTO stripe_charges(tenant_id, order_id, payment_intent_id, amount_minor, currency, status, raw)
            VALUES(:t,:o,:pi,:amt,:cur,:st, CAST(:raw AS JSONB))
            ON CONFLICT (payment_intent_id) DO UPDATE
              SET status=EXCLUDED.status, raw=EXCLUDED.raw, updated_at=NOW()
        """), {
            "t": payload.tenant_id, "o": payload.order_id, "pi": pi["id"],
            "amt": payload.amount_minor, "cur": payload.currency, "st": pi["status"],
            "raw": json.dumps(pi)
        })
        db.commit()
        return {"payment_intent_id": pi["id"], "client_secret": pi["client_secret"], "status": pi["status"]}

@app.post("/payments/stripe/webhook")
async def stripe_webhook(request: Request):
    if not STRIPE_WEBHOOK_SECRET:
        raise HTTPException(500, "STRIPE_WEBHOOK_SECRET not set")
    payload = await request.body()
    sig = request.headers.get("Stripe-Signature", "")
    try:
        event = stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
    except Exception as e:
        raise HTTPException(400, f"invalid signature: {e}")

    etype = event["type"]
    obj = event["data"]["object"]

    # We’ll handle payment_intent.* and charge.succeeded for redundancy
    with SessionLocal() as db:
        if etype.startswith("payment_intent."):
            pi = obj
            db.execute(text("""
                UPDATE stripe_charges
                   SET status=:st, raw=CAST(:raw AS JSONB), updated_at=NOW()
                 WHERE payment_intent_id=:pi
            """), {"st": pi["status"], "raw": stripe.util.convert_to_json_string(pi), "pi": pi["id"]})
            # Optionally: update orders.status based on pi["status"] via HTTP to orders service (later step)
            db.commit()
        elif etype == "charge.succeeded":
            ch = obj
            pi_id = ch.get("payment_intent")
            db.execute(text("""
                UPDATE stripe_charges
                   SET charge_id=:ch, status='succeeded', raw=CAST(:raw AS JSONB), updated_at=NOW()
                 WHERE payment_intent_id=:pi
            """), {"ch": ch["id"], "raw": stripe.util.convert_to_json_string(ch), "pi": pi_id})
            db.commit()
    return {"ok": True}