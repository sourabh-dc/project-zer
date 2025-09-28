# services/subscriptions/main.py
from fastapi import FastAPI, Body, Query, HTTPException, Path, Request, Header
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from sqlalchemy import text
import logging, os, json, time
from datetime import datetime, timedelta
from zeroque_common.db.session import get_engine, init_db, check_db, SessionLocal
import stripe as stripe_sdk
from fastapi.responses import PlainTextResponse

SERVICE_NAME = "subscriptions"
app = FastAPI(title="ZeroQue Site Subscriptions Service", version="0.1.0")

# ---------- logging ----------
log = logging.getLogger(SERVICE_NAME)
if not log.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s :: %(message)s"))
    log.addHandler(h)
log.setLevel(os.getenv("LOG_LEVEL", "INFO"))

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
class SubscribeSitePayload(BaseModel):
    plan_code: str = Field(..., pattern="^(core|pro|enterprise)$")
    payment_method: str = Field(..., pattern="^(stripe|trade)$")

class CreateBillingAccountPayload(BaseModel):
    payment_method: str = Field(..., pattern="^(stripe|trade)$")
    external_id: str = Field(..., min_length=1)
    metadata: Optional[Dict[str, Any]] = None

class TradeAccountPayload(BaseModel):
    ar_customer_code: str = Field(..., min_length=1)
    terms: str = Field("NET30", max_length=20)

# ---------- subscription plans ----------
@app.get("/subscriptions/plans")
def list_plans(active: Optional[bool] = Query(None)):
    """
    List available subscription plans with pricing.
    """
    with SessionLocal() as db:
        where_clause = "WHERE active = :a" if active is not None else "WHERE 1=1"
        params = {"a": active} if active is not None else {}
        
        rows = db.execute(text(f"""
            SELECT code, name, description, price_yearly_minor, currency, active
              FROM subscription_plans
              {where_clause}
             ORDER BY price_yearly_minor
        """), params).all()
        
        out = [{
            "code": r[0], "name": r[1], "description": r[2],
            "price_yearly_minor": int(r[3]), "currency": r[4], "active": bool(r[5])
        } for r in rows]
        log.info("plans_listed count=%d active=%s", len(out), active)
        return out

@app.get("/subscriptions/plans/{plan_code}/features")
def list_plan_features(plan_code: str = Path(...)):
    """
    List features included in a specific plan.
    """
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT f.code, f.name, f.description, f.category, pf.enabled, pf.limits
              FROM plan_features pf
              JOIN features f ON pf.feature_code = f.code
             WHERE pf.plan_code = :plan AND f.active = TRUE
             ORDER BY f.category, f.name
        """), {"plan": plan_code}).all()
        
        out = [{
            "code": r[0], "name": r[1], "description": r[2], "category": r[3],
            "enabled": bool(r[4]), "limits": r[5]
        } for r in rows]
        log.info("plan_features_listed plan=%s count=%d", plan_code, len(out))
        return out

# ---------- site billing accounts ----------
@app.post("/subscriptions/sites/{tenant_id}/{site_id}/billing-accounts")
def create_billing_account(
    tenant_id: str = Path(...), 
    site_id: str = Path(...), 
    payload: CreateBillingAccountPayload = Body(...)
):
    """
    Create a billing account for a site (Stripe customer or Trade account).
    """
    with SessionLocal() as db:
        # Check if billing account already exists
        exists = db.execute(text("""
            SELECT id FROM site_billing_accounts
             WHERE tenant_id=:tid AND site_id=:sid AND payment_method=:pm
        """), {"tid": tenant_id, "sid": site_id, "pm": payload.payment_method}).first()
        
        if exists:
            raise HTTPException(status_code=400, detail="Billing account already exists for this site and payment method")
        
        db.execute(text("""
            INSERT INTO site_billing_accounts(tenant_id, site_id, payment_method, external_id, metadata)
            VALUES(:tid, :sid, :pm, :ext, :meta)
        """), {
            "tid": tenant_id, "sid": site_id, "pm": payload.payment_method,
            "ext": payload.external_id, "meta": json.dumps(payload.metadata or {})
        })
        db.commit()
        log.info("billing_account_created tenant=%s site=%s method=%s", tenant_id, site_id, payload.payment_method)
        return {"created": True, "tenant_id": tenant_id, "site_id": site_id, "payment_method": payload.payment_method}

@app.get("/subscriptions/sites/{tenant_id}/{site_id}/billing-accounts")
def list_billing_accounts(tenant_id: str = Path(...), site_id: str = Path(...)):
    """
    List billing accounts for a site.
    """
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT payment_method, external_id, active, metadata, created_at
              FROM site_billing_accounts
             WHERE tenant_id=:tid AND site_id=:sid
             ORDER BY created_at
        """), {"tid": tenant_id, "sid": site_id}).all()
        
        out = [{
            "payment_method": r[0], "external_id": r[1], "active": bool(r[2]),
            "metadata": r[3], "created_at": r[4]
        } for r in rows]
        log.info("billing_accounts_listed tenant=%s site=%s count=%d", tenant_id, site_id, len(out))
        return out

# ---------- site subscriptions ----------
@app.post("/subscriptions/sites/{tenant_id}/{site_id}/subscribe")
def subscribe_site(
    tenant_id: str = Path(...), 
    site_id: str = Path(...), 
    payload: SubscribeSitePayload = Body(...)
):
    """
    Create a subscription for a site.
    """
    with SessionLocal() as db:
        # Check if site already has an active subscription
        existing = db.execute(text("""
            SELECT id FROM site_subscriptions
             WHERE tenant_id=:tid AND site_id=:sid AND status IN ('active', 'trialing')
        """), {"tid": tenant_id, "sid": site_id}).first()
        
        if existing:
            raise HTTPException(status_code=400, detail="Site already has an active subscription")
        
        # Verify billing account exists
        billing_account = db.execute(text("""
            SELECT external_id FROM site_billing_accounts
             WHERE tenant_id=:tid AND site_id=:sid AND payment_method=:pm AND active=TRUE
        """), {"tid": tenant_id, "sid": site_id, "pm": payload.payment_method}).first()
        
        if not billing_account:
            raise HTTPException(status_code=400, detail=f"No active billing account found for payment method: {payload.payment_method}")
        
        # Handle different payment methods
        if payload.payment_method == "trade":
            external_id = f"trade-sub-{tenant_id}-{site_id}-{int(time.time())}"
            status = "active"
            current_period_start = datetime.utcnow()
            current_period_end = current_period_start + timedelta(days=365)  # 1 year
            
            db.execute(text("""
                INSERT INTO site_subscriptions(tenant_id, site_id, plan_code, payment_method, status, 
                                             external_id, current_period_start, current_period_end)
                VALUES(:tid, :sid, :plan, :pm, :st, :ext, :start, :end)
            """), {
                "tid": tenant_id, "sid": site_id, "plan": payload.plan_code, "pm": payload.payment_method,
                "st": status, "ext": external_id, "start": current_period_start, "end": current_period_end
            })
            db.commit()
            log.info("subscription_created_trade tenant=%s site=%s plan=%s sub=%s", 
                    tenant_id, site_id, payload.plan_code, external_id)
            
        else:  # stripe
            api_key = os.getenv("STRIPE_API_KEY", "").strip()
            if not api_key:
                # Stubbed subscription for dev
                external_id = f"stub_sub_{tenant_id}_{site_id}_{int(time.time())}"
                status = "active"
                current_period_start = datetime.utcnow()
                current_period_end = current_period_start + timedelta(days=365)
                
                db.execute(text("""
                    INSERT INTO site_subscriptions(tenant_id, site_id, plan_code, payment_method, status, 
                                                 external_id, current_period_start, current_period_end)
                    VALUES(:tid, :sid, :plan, :pm, :st, :ext, :start, :end)
                """), {
                    "tid": tenant_id, "sid": site_id, "plan": payload.plan_code, "pm": payload.payment_method,
                    "st": status, "ext": external_id, "start": current_period_start, "end": current_period_end
                })
                db.commit()
                log.warning("subscription_stubbed_stripe tenant=%s site=%s plan=%s sub=%s", 
                           tenant_id, site_id, payload.plan_code, external_id)
            else:
                # Real Stripe subscription
                stripe_sdk.api_key = api_key
                
                # Get plan pricing
                plan = db.execute(text("""
                    SELECT price_yearly_minor FROM subscription_plans WHERE code=:plan
                """), {"plan": payload.plan_code}).first()
                
                if not plan:
                    raise HTTPException(status_code=400, detail="Invalid plan code")
                
                # Create Stripe subscription
                created = stripe_sdk.Subscription.create(
                    customer=billing_account[0],
                    items=[{"price_data": {
                        "currency": "gbp",
                        "product_data": {"name": f"{payload.plan_code.title()} Plan"},
                        "unit_amount": plan[0],  # price in minor units
                        "recurring": {"interval": "year"}
                    }}],
                    payment_behavior="default_incomplete"
                )
                
                db.execute(text("""
                    INSERT INTO site_subscriptions(tenant_id, site_id, plan_code, payment_method, status, 
                                                 external_id, current_period_start, current_period_end)
                    VALUES(:tid, :sid, :plan, :pm, :st, :ext, :start, :end)
                """), {
                    "tid": tenant_id, "sid": site_id, "plan": payload.plan_code, "pm": payload.payment_method,
                    "st": created["status"], "ext": created["id"], 
                    "start": datetime.fromtimestamp(created["current_period_start"]),
                    "end": datetime.fromtimestamp(created["current_period_end"])
                })
                db.commit()
                log.info("subscription_created_stripe tenant=%s site=%s plan=%s sub=%s status=%s",
                        tenant_id, site_id, payload.plan_code, created["id"], created["status"])
                external_id = created["id"]
                status = created["status"]
        
        return {
            "subscription_id": external_id, 
            "status": status, 
            "provider": payload.payment_method, 
            "plan": payload.plan_code,
            "tenant_id": tenant_id,
            "site_id": site_id
        }

@app.get("/subscriptions/sites/{tenant_id}/{site_id}")
def get_site_subscription(tenant_id: str = Path(...), site_id: str = Path(...)):
    """
    Get current subscription for a site.
    """
    with SessionLocal() as db:
        row = db.execute(text("""
            SELECT plan_code, payment_method, status, external_id, current_period_start, 
                   current_period_end, trial_end, canceled_at, created_at
              FROM site_subscriptions
             WHERE tenant_id=:tid AND site_id=:sid
             ORDER BY created_at DESC
             LIMIT 1
        """), {"tid": tenant_id, "sid": site_id}).first()
        
        if not row:
            raise HTTPException(status_code=404, detail="No subscription found for this site")
        
        return {
            "tenant_id": tenant_id, "site_id": site_id, "plan_code": row[0],
            "payment_method": row[1], "status": row[2], "external_id": row[3],
            "current_period_start": row[4], "current_period_end": row[5],
            "trial_end": row[6], "canceled_at": row[7], "created_at": row[8]
        }

@app.get("/subscriptions/sites/{tenant_id}")
def list_tenant_subscriptions(tenant_id: str = Path(...)):
    """
    List all subscriptions for a tenant.
    """
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT site_id, plan_code, payment_method, status, external_id, 
                   current_period_start, current_period_end, created_at
              FROM site_subscriptions
             WHERE tenant_id=:tid
             ORDER BY created_at DESC
        """), {"tid": tenant_id}).all()
        
        out = [{
            "tenant_id": tenant_id, "site_id": r[0], "plan_code": r[1],
            "payment_method": r[2], "status": r[3], "external_id": r[4],
            "current_period_start": r[5], "current_period_end": r[6], "created_at": r[7]
        } for r in rows]
        log.info("tenant_subscriptions_listed tenant=%s count=%d", tenant_id, len(out))
        return out

# ---------- Stripe webhook ----------
@app.post("/webhooks/stripe")
async def stripe_webhook(request: Request, stripe_signature: str = Header(None, alias="Stripe-Signature")):
    """
    Handle Stripe webhooks for subscription lifecycle events.
    """
    body = await request.body()
    
    # Verify signature if configured
    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET")
    if webhook_secret:
        try:
            event = stripe_sdk.Webhook.construct_event(body, stripe_signature, webhook_secret)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid payload")
        except stripe_sdk.error.SignatureVerificationError:
            raise HTTPException(status_code=400, detail="Invalid signature")
    else:
        # Dev mode - parse without verification
        event = json.loads(body)
    
    event_id = event.get("id")
    event_type = event.get("type")
    
    if not event_id or not event_type:
        raise HTTPException(status_code=400, detail="Missing event id or type")
    
    with SessionLocal() as db:
        # Insert once; if duplicate -> already processed
        try:
            db.execute(text("""
                INSERT INTO stripe_events(event_id, event_type) VALUES(:id, :t)
            """), {"id": event_id, "t": event_type})
            db.commit()
        except Exception:
            # Duplicate; safe to ACK
            return {"ok": True, "duplicate": True}
        
        # Handle subscription events
        if event_type in ("customer.subscription.created", "customer.subscription.updated", 
                         "customer.subscription.deleted"):
            obj = event.get("data", {}).get("object", {}) or {}
            external_id = obj.get("id")
            status = obj.get("status")
            
            if external_id and status:
                # Update site subscription
                updated = db.execute(text("""
                    UPDATE site_subscriptions 
                       SET status=:st, 
                           current_period_start=:start,
                           current_period_end=:end,
                           updated_at=NOW()
                     WHERE external_id=:ext
                """), {
                    "st": status, 
                    "ext": external_id,
                    "start": datetime.fromtimestamp(obj.get("current_period_start", 0)) if obj.get("current_period_start") else None,
                    "end": datetime.fromtimestamp(obj.get("current_period_end", 0)) if obj.get("current_period_end") else None
                }).rowcount
                
                if updated:
                    db.commit()
                    log.info("stripe_webhook_subscription_updated sub=%s status=%s", external_id, status)
                else:
                    log.warning("stripe_webhook_subscription_not_found sub=%s", external_id)
        
        return {"ok": True, "event_id": event_id, "event_type": event_type}
