from fastapi import FastAPI, HTTPException, Path, Body, Request, Query
from pydantic import BaseModel, Field
import os, time
import stripe as stripe_sdk
from sqlalchemy import text
from fastapi.responses import PlainTextResponse
from zeroque_common.db.session import get_engine, init_db, SessionLocal, check_db
from zeroque_common.models.billing import Plan, Feature, PlanFeature, StripeCustomer, TradeAccount, Subscription, PaymentPreference, TradeInvoice, StripeCharge

SERVICE_NAME = "billing"
app = FastAPI(title="ZeroQue Billing Service", version="0.4.0")  # Updated version

class SubscribePayload(BaseModel):
    plan: str = Field(..., pattern="^(core|pro|enterprise)$")
    payment_method: str = Field(..., pattern="^(stripe|trade)$")

class TradePayload(BaseModel):
    ar_customer_code: str
    terms: str = "NET30"

# NEW: Model for the new endpoint
class PaymentPrefPayload(BaseModel):
    method: str  # 'trade' | 'stripe'

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

# --- Existing Endpoints (Keep these) ---
@app.post("/billing/tenants/{tenant_id}/trade-account")
def create_trade_account(tenant_id: str = Path(...), payload: TradePayload = Body(...)):
    with SessionLocal() as db:
        existing = db.query(TradeAccount).filter(TradeAccount.tenant_id == tenant_id).one_or_none()
        if existing:
            existing.ar_customer_code = payload.ar_customer_code
            existing.terms = payload.terms
            existing.active = True
            db.commit()
            return {"tenant_id": tenant_id, "active": existing.active, "ar_customer_code": existing.ar_customer_code, "terms": existing.terms}
        tr = TradeAccount(tenant_id=tenant_id, ar_customer_code=payload.ar_customer_code, terms=payload.terms, active=True)
        db.add(tr)
        db.commit()
        return {"tenant_id": tenant_id, "active": tr.active, "ar_customer_code": tr.ar_customer_code, "terms": tr.terms}

@app.post("/billing/tenants/{tenant_id}/subscribe")
def subscribe(tenant_id: str = Path(...), payload: SubscribePayload = Body(...)):
    with SessionLocal() as db:
        if payload.payment_method == "trade":
            tr = db.query(TradeAccount).filter(TradeAccount.tenant_id == tenant_id, TradeAccount.active == True).one_or_none()
            if not tr:
                raise HTTPException(status_code=400, detail="Trade account not active for tenant.")
            external_id = f"trade-sub-{tenant_id}-{int(time.time())}"
            sub = Subscription(tenant_id=tenant_id, plan_code=payload.plan, provider="trade", status="active", external_id=external_id)
            db.add(sub)
            db.commit()
            return {"subscription_id": sub.external_id, "status": sub.status, "provider": "trade", "plan": sub.plan_code}

        api_key = os.getenv("STRIPE_API_KEY", "").strip()
        if not api_key:
            cust = db.query(StripeCustomer).filter(StripeCustomer.tenant_id == tenant_id).one_or_none()
            if not cust:
                cust = StripeCustomer(tenant_id=tenant_id, stripe_customer_id=f"stub_cus_{tenant_id}")
                db.add(cust); db.commit()
            external_id = f"stub_sub_{tenant_id}_{int(time.time())}"
            sub = Subscription(tenant_id=tenant_id, plan_code=payload.plan, provider="stripe", status="active", external_id=external_id)
            db.add(sub); db.commit()
            return {"subscription_id": sub.external_id, "status": sub.status, "provider": "stripe", "plan": sub.plan_code}

        stripe_sdk.api_key = api_key
        cust = db.query(StripeCustomer).filter(StripeCustomer.tenant_id == tenant_id).one_or_none()
        if not cust:
            sc = stripe_sdk.Customer.create(metadata={"tenant_id": tenant_id})
            cust = StripeCustomer(tenant_id=tenant_id, stripe_customer_id=sc["id"])
            db.add(cust); db.commit()

        price_map = {
            "core": os.getenv("STRIPE_PRICE_CORE", "price_core_dev"),
            "pro": os.getenv("STRIPE_PRICE_PRO", "price_pro_dev"),
            "enterprise": os.getenv("STRIPE_PRICE_ENTERPRISE", "price_enterprise_dev"),
        }
        price_id = price_map[payload.plan]

        created = stripe_sdk.Subscription.create(
            customer=cust.stripe_customer_id,
            items=[{"price": price_id}],
            payment_behavior="default_incomplete"
        )
        sub = Subscription(tenant_id=tenant_id, plan_code=payload.plan, provider="stripe", status=created["status"], external_id=created["id"])
        db.add(sub); db.commit()
        return {"subscription_id": sub.external_id, "status": sub.status, "provider": "stripe", "plan": sub.plan_code}

@app.post("/webhooks/stripe")
async def stripe_webhook(request: Request):
    payload = await request.json()
    external_id = payload.get("data", {}).get("object", {}).get("id")
    status = payload.get("data", {}).get("object", {}).get("status")
    if external_id and status:
        with SessionLocal() as db:
            sub = db.query(Subscription).filter(Subscription.external_id == external_id).one_or_none()
            if sub:
                sub.status = status
                db.commit()
                return {"ok": True, "updated": external_id, "status": status}
    return {"ok": True}

# --- NEW Endpoints (Add these) ---
@app.put("/billing/payment-preference/{tenant_id}")
def set_payment_preference(tenant_id: str, payload: PaymentPrefPayload = Body(...)):
    if payload.method not in ("trade","stripe"):
        raise HTTPException(status_code=400, detail="invalid method")
    with SessionLocal() as db:
        exists = db.execute(text("SELECT tenant_id FROM payment_preferences WHERE tenant_id=:t"), {"t": tenant_id}).first()
        if exists:
            db.execute(text("UPDATE payment_preferences SET method=:m WHERE tenant_id=:t"), {"m": payload.method, "t": tenant_id})
        else:
            db.execute(text("INSERT INTO payment_preferences(tenant_id, method) VALUES(:t,:m)"), {"t": tenant_id, "m": payload.method})
        db.commit()
        return {"tenant_id": tenant_id, "method": payload.method}

@app.get("/billing/trade-invoices")
def list_invoices(tenant_id: str = Query(...)):
    with SessionLocal() as db:
        rows = db.execute(text("""
          SELECT id, order_id, amount_minor, currency, status, memo
          FROM trade_invoices WHERE tenant_id=:t ORDER BY id DESC
        """), {"t": tenant_id}).all()
        return [{"id": int(r[0]), "order_id": r[1], "amount_minor": int(r[2]), "currency": r[3], "status": r[4], "memo": r[5]} for r in rows]

@app.get("/billing/stripe-charges")
def list_charges(tenant_id: str = Query(...)):
    with SessionLocal() as db:
        rows = db.execute(text("""
          SELECT id, order_id, amount_minor, currency, status, receipt_url
          FROM stripe_charges WHERE tenant_id=:t ORDER BY id DESC
        """), {"t": tenant_id}).all()
        return [{"id": int(r[0]), "order_id": r[1], "amount_minor": int(r[2]), "currency": r[3], "status": r[4], "receipt_url": r[5]} for r in rows]
    
@app.get("/billing/trade-invoices/export.csv", response_class=PlainTextResponse)
def export_invoices_csv(tenant_id: str = Query(...), date_from: str = Query(...), date_to: str = Query(...)):
    with SessionLocal() as db:
        # If created_at filter feels too strict for you, you can drop it or make it optional
        rows = db.execute(text("""
          SELECT id, order_id, amount_minor, currency, status, memo, created_at::date
            FROM trade_invoices
           WHERE tenant_id=:t
             AND created_at::date BETWEEN :f AND :to
           ORDER BY id
        """), {"t": tenant_id, "f": date_from, "to": date_to}).all()
        out = ["id,order_id,amount_minor,currency,status,memo,created_date"]
        for r in rows:
            memo = (r[5] or "").replace('"','""')
            out.append(f'{int(r[0])},{r[1]},{int(r[2])},{r[3]},{r[4]},"{memo}",{r[6]}')
        return "\n".join(out) + ("\n" if out else "")