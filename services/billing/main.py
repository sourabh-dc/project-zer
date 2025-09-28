from fastapi import FastAPI, HTTPException, Path, Body, Request, Query
from pydantic import BaseModel, Field
import os, time, logging
import stripe as stripe_sdk
from sqlalchemy import text
from fastapi.responses import PlainTextResponse
from zeroque_common.db.session import get_engine, init_db, SessionLocal, check_db
from zeroque_common.models.billing import (
    Plan, Feature, PlanFeature, StripeCustomer, TradeAccount, Subscription,
    PaymentPreference, TradeInvoice, StripeCharge
)
from .reports import router as reports_router
from fastapi import Header
import json
log = logging.getLogger("billing")
logging.basicConfig(level=os.getenv("LOG_LEVEL","INFO"))
SERVICE_NAME = "billing"
app = FastAPI(title="ZeroQue Billing Service", version="0.5.0")  # bumped

# ---------- logging ----------
log = logging.getLogger(SERVICE_NAME)
if not log.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s :: %(message)s"))
    log.addHandler(_h)
log.setLevel(logging.INFO)

# ---------- routers ----------
app.include_router(reports_router, prefix="/billing", tags=["reports"])

# ---------- payloads ----------
class SubscribePayload(BaseModel):
    plan: str = Field(..., pattern="^(core|pro|enterprise)$")
    payment_method: str = Field(..., pattern="^(stripe|trade)$")

class TradePayload(BaseModel):
    ar_customer_code: str
    terms: str = "NET30"

class PaymentPrefPayload(BaseModel):
    method: str  # 'trade' | 'stripe'

class PostInvoiceLine(BaseModel):
    sku: str
    qty: int
    unit_price_minor: int
    currency: str | None = None
    tax_minor: int = 0          # NEW
    tax_code: str | None = None # NEW

class PostInvoice(BaseModel):
    tenant_id: str
    site_id: str | None = None
    order_id: str | None = None
    amount_minor: int
    currency: str = "GBP"
    lines: list[PostInvoiceLine] = []
    invoice_code: str | None = None  # NEW

# ---------- lifecycle ----------
@app.on_event("startup")
def on_startup():
    get_engine(); init_db()
    log.info("service_started")

@app.get("/health")
def health(): return {"status": "ok", "service": SERVICE_NAME}

@app.get("/readiness")
def readiness():
    return {"service": SERVICE_NAME, "db": check_db(), "redis": True}

# ---------- endpoints ----------
@app.post("/billing/tenants/{tenant_id}/trade-account")
def create_trade_account(tenant_id: str = Path(...), payload: TradePayload = Body(...)):
    """
    Create or activate a trade account for a tenant.
    """
    with SessionLocal() as db:
        existing = db.query(TradeAccount).filter(TradeAccount.tenant_id == tenant_id).one_or_none()
        if existing:
            existing.ar_customer_code = payload.ar_customer_code
            existing.terms = payload.terms
            existing.active = True
            db.commit()
            log.info("trade_account_updated tenant=%s", tenant_id)
            return {
                "tenant_id": tenant_id, "active": existing.active,
                "ar_customer_code": existing.ar_customer_code, "terms": existing.terms
            }
        tr = TradeAccount(
            tenant_id=tenant_id, ar_customer_code=payload.ar_customer_code,
            terms=payload.terms, active=True
        )
        db.add(tr); db.commit()
        log.info("trade_account_created tenant=%s", tenant_id)
        return {"tenant_id": tenant_id, "active": tr.active,
                "ar_customer_code": tr.ar_customer_code, "terms": tr.terms}

@app.post("/billing/tenants/{tenant_id}/subscribe")
def subscribe(tenant_id: str = Path(...), payload: SubscribePayload = Body(...)):
    """
    Create a subscription for the tenant on the chosen payment rail.
    - trade  → local subscription (active)
    - stripe → real Stripe subscription if STRIPE_API_KEY set, else stubbed active subscription for dev
    """
    with SessionLocal() as db:
        if payload.payment_method == "trade":
            tr = db.query(TradeAccount).filter(
                TradeAccount.tenant_id == tenant_id, TradeAccount.active == True
            ).one_or_none()
            if not tr:
                raise HTTPException(status_code=400, detail="Trade account not active for tenant.")
            external_id = f"trade-sub-{tenant_id}-{int(time.time())}"
            sub = Subscription(
                tenant_id=tenant_id, plan_code=payload.plan, provider="trade",
                status="active", external_id=external_id
            )
            db.add(sub); db.commit()
            log.info("subscription_created_trade tenant=%s plan=%s sub=%s", tenant_id, payload.plan, external_id)
            return {"subscription_id": sub.external_id, "status": sub.status, "provider": "trade", "plan": sub.plan_code}

        # Stripe path
        api_key = os.getenv("STRIPE_API_KEY", "").strip()
        if not api_key:
            # Stubbed subscription for dev without Stripe
            cust = db.query(StripeCustomer).filter(StripeCustomer.tenant_id == tenant_id).one_or_none()
            if not cust:
                cust = StripeCustomer(tenant_id=tenant_id, stripe_customer_id=f"stub_cus_{tenant_id}")
                db.add(cust); db.commit()
            external_id = f"stub_sub_{tenant_id}_{int(time.time())}"
            sub = Subscription(
                tenant_id=tenant_id, plan_code=payload.plan, provider="stripe",
                status="active", external_id=external_id
            )
            db.add(sub); db.commit()
            log.warning("subscription_stubbed_stripe tenant=%s plan=%s sub=%s", tenant_id, payload.plan, external_id)
            return {"subscription_id": sub.external_id, "status": sub.status, "provider": "stripe", "plan": sub.plan_code}

        # Real Stripe
        stripe_sdk.api_key = api_key
        cust = db.query(StripeCustomer).filter(StripeCustomer.tenant_id == tenant_id).one_or_none()
        if not cust:
            sc = stripe_sdk.Customer.create(metadata={"tenant_id": tenant_id})
            cust = StripeCustomer(tenant_id=tenant_id, stripe_customer_id=sc["id"])
            db.add(cust); db.commit()
            log.info("stripe_customer_created tenant=%s stripe_customer_id=%s", tenant_id, sc["id"])

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
        sub = Subscription(
            tenant_id=tenant_id, plan_code=payload.plan, provider="stripe",
            status=created["status"], external_id=created["id"]
        )
        db.add(sub); db.commit()
        log.info("subscription_created_stripe tenant=%s plan=%s sub=%s status=%s",
                 tenant_id, payload.plan, created["id"], created["status"])
        return {"subscription_id": sub.external_id, "status": sub.status, "provider": "stripe", "plan": sub.plan_code}

@app.post("/webhooks/stripe")
async def stripe_webhook(request: Request, stripe_signature: str = Header(None, alias="Stripe-Signature")):
    # Verify signature if configured
    payload = await request.body()
    event = None

    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()
    if webhook_secret:
        try:
            event = stripe_sdk.Webhook.construct_event(
                payload=payload,
                sig_header=stripe_signature,
                secret=webhook_secret,
            )
        except Exception as e:
            log.warning(f"stripe_webhook_invalid_signature err={e}")
            raise HTTPException(status_code=400, detail="invalid signature")
    else:
        # Dev convenience if no secret set
        try:
            event = json.loads(payload.decode("utf-8"))
        except Exception:
            raise HTTPException(status_code=400, detail="invalid payload")

    # Idempotency by event id
    event_id = event.get("id")
    event_type = event.get("type")
    if not event_id:
        raise HTTPException(status_code=400, detail="missing event id")

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

        # --- Handle a couple of event types we care about ---
        if event_type in ("customer.subscription.created", "customer.subscription.updated"):
            obj = event.get("data", {}).get("object", {}) or {}
            external_id = obj.get("id")
            status = obj.get("status")
            if external_id and status:
                sub_upd = db.execute(text("""
                    UPDATE subscriptions SET status=:st WHERE external_id=:ext
                """), {"st": status, "ext": external_id}).rowcount
                db.commit()
                log.info(f"stripe_webhook_subscription_updated sub={external_id} status={status}")

        if event_type in ("payment_intent.succeeded",):
            obj = event.get("data", {}).get("object", {}) or {}
            pi_id = obj.get("id")
            amount_minor = int(obj.get("amount_received") or obj.get("amount") or 0)
            currency = (obj.get("currency") or "gbp").upper()
            metadata = obj.get("metadata") or {}
            tenant_id = metadata.get("tenant_id")
            site_id = metadata.get("site_id")
            order_id = metadata.get("order_id")
            receipt_url = None
            # Try drill into charges for receipt_url if available
            ch = (obj.get("charges") or {}).get("data") or []
            if ch and isinstance(ch, list):
                receipt_url = ch[0].get("receipt_url")

            if not tenant_id:
                log.warning(f"stripe_webhook_pi_succeeded missing tenant_id for pi={pi_id}")
            else:
                # persist charge row (upsert by PI if you want)
                db.execute(text("""
                    INSERT INTO stripe_charges(tenant_id, site_id, order_id, amount_minor, currency, status, receipt_url)
                    VALUES(:t, :s, :o, :amt, :cur, 'succeeded', :r)
                """), {"t": tenant_id, "s": site_id, "o": order_id, "amt": amount_minor, "cur": currency, "r": receipt_url})
                db.commit()
                log.info(f"stripe_charge_recorded tenant={tenant_id} order={order_id} amt={amount_minor} {currency} receipt={bool(receipt_url)}")

    return {"ok": True}

@app.put("/billing/payment-preference/{tenant_id}")
def set_payment_preference(tenant_id: str, payload: PaymentPrefPayload = Body(...)):
    """
    Upsert the default payment method for a tenant ('trade'|'stripe').
    """
    if payload.method not in ("trade", "stripe"):
        raise HTTPException(status_code=400, detail="invalid method")
    with SessionLocal() as db:
        exists = db.execute(
            text("SELECT tenant_id FROM payment_preferences WHERE tenant_id=:t"),
            {"t": tenant_id}
        ).first()
        if exists:
            db.execute(
                text("UPDATE payment_preferences SET method=:m WHERE tenant_id=:t"),
                {"m": payload.method, "t": tenant_id}
            )
            db.commit()
            log.info("payment_pref_updated tenant=%s method=%s", tenant_id, payload.method)
        else:
            db.execute(
                text("INSERT INTO payment_preferences(tenant_id, method) VALUES(:t,:m)"),
                {"t": tenant_id, "m": payload.method}
            )
            db.commit()
            log.info("payment_pref_created tenant=%s method=%s", tenant_id, payload.method)
        return {"tenant_id": tenant_id, "method": payload.method}

@app.get("/billing/trade-invoices")
def list_invoices(tenant_id: str = Query(...)):
    with SessionLocal() as db:
        rows = db.execute(text("""
          SELECT id, order_id, amount_minor, currency, status, memo
          FROM trade_invoices WHERE tenant_id=:t ORDER BY id DESC
        """), {"t": tenant_id}).all()
        return [{
            "id": int(r[0]), "order_id": r[1], "amount_minor": int(r[2]),
            "currency": r[3], "status": r[4], "memo": r[5]
        } for r in rows]



@app.post("/billing/trade-invoices/{invoice_id}/post")
def post_invoice(invoice_id: str = Path(...), payload: PostInvoice = Body(...)):
    with SessionLocal() as db:
        # upsert draft (now supports invoice_code)
        db.execute(text("""
            INSERT INTO trade_invoices(id, tenant_id, site_id, order_id, amount_minor, currency, status, memo, invoice_code)
            VALUES(:id,:t,:s,:o,:amt,:cur,'draft','',:icode)
            ON CONFLICT (id) DO UPDATE SET
                tenant_id = EXCLUDED.tenant_id,
                site_id = EXCLUDED.site_id,
                order_id = EXCLUDED.order_id,
                amount_minor = EXCLUDED.amount_minor,
                currency = EXCLUDED.currency,
                invoice_code = COALESCE(EXCLUDED.invoice_code, trade_invoices.invoice_code)
        """), {"id": invoice_id, "t": payload.tenant_id, "s": payload.site_id, "o": payload.order_id,
               "amt": payload.amount_minor, "cur": payload.currency, "icode": payload.invoice_code})

        # replace lines (with tax fields)
        db.execute(text("DELETE FROM trade_invoice_lines WHERE invoice_id=:id"), {"id": invoice_id})
        for ln in payload.lines:
            db.execute(text("""
                INSERT INTO trade_invoice_lines(
                    invoice_id, sku, qty, unit_price_minor, currency, tax_minor, tax_code
                )
                VALUES(:id,:sku,:qty,:up,:cur,:tax,:tcode)
            """), {"id": invoice_id, "sku": ln.sku, "qty": int(ln.qty),
                   "up": int(ln.unit_price_minor), "cur": ln.currency or payload.currency,
                   "tax": int(ln.tax_minor or 0), "tcode": ln.tax_code})

        # post
        db.execute(text("""
            UPDATE trade_invoices SET status='posted', posted_at=NOW() WHERE id=:id
        """), {"id": invoice_id})
        db.commit()
        return {"invoice_id": invoice_id, "status": "posted"}
    
@app.post("/billing/trade-invoices/{invoice_id}/export")
def export_invoice(invoice_id: str = Path(...)):
    """
    Mark a posted invoice as exported (assign export batch id + timestamp).
    """
    with SessionLocal() as db:
        # FIX: `export_batch_id:=` → should be `export_batch_id =`
        db.execute(text("""
            UPDATE trade_invoices
               SET status='exported',
                   exported_at=NOW(),
                   export_batch_id = 'batch-' || to_char(NOW(),'YYYYMMDDHH24MISS')
             WHERE id=:id
        """), {"id": invoice_id})
        db.commit()
        log.info("trade_invoice_exported invoice_id=%s", invoice_id)
        return {"invoice_id": invoice_id, "status": "exported"}

@app.get("/billing/trade-invoices/export.csv")
def export_csv(
    tenant_id: str = Query(...), site_id: str | None = Query(None),
    date_from: str = Query(...), date_to: str = Query(...)
):
    """
    Export basic invoice CSV for a date range (created_at window).
    """
    q = """
      SELECT id, tenant_id, site_id, amount_minor, currency, status, posted_at, exported_at
        FROM trade_invoices
       WHERE tenant_id=:t AND created_at >= :f AND created_at < :to
    """
    params = {"t": tenant_id, "f": date_from, "to": date_to}
    if site_id:
        q += " AND site_id=:s"
        params["s"] = site_id
    q += " ORDER BY id ASC"

    with SessionLocal() as db:
        rows = db.execute(text(q), params).all()

    lines = ["invoice_id,tenant_id,site_id,amount_minor,currency,status,posted_at,exported_at"]
    for r in rows:
        lines.append(",".join([
            str(r[0]), r[1], (r[2] or ""), str(r[3]), r[4], r[5],
            (r[6].isoformat() if r[6] else ""), (r[7].isoformat() if r[7] else "")
        ]))
    csv = "\n".join(lines)
    log.info("trade_invoice_export_csv tenant=%s rows=%d", tenant_id, len(rows))
    return PlainTextResponse(csv)

@app.get("/billing/stripe-charges")
def list_charges(tenant_id: str = Query(...)):
    with SessionLocal() as db:
        rows = db.execute(text("""
          SELECT id, order_id, amount_minor, currency, status, receipt_url
          FROM stripe_charges WHERE tenant_id=:t ORDER BY id DESC
        """), {"t": tenant_id}).all()
        return [{
            "id": int(r[0]),
            "order_id": r[1],
            "amount_minor": int(r[2]),
            "currency": r[3],
            "status": r[4],
            "receipt_url": r[5]
        } for r in rows]

@app.get("/billing/trade-invoices/export-gl.csv")
def export_gl_csv(
    tenant_id: str = Query(...),
    date_from: str = Query(...),
    date_to: str = Query(...),
    site_id: str | None = Query(None),
):
    """
    Flat GL lines for posted (or exported) trade invoices.
    Accounts (example):
      - AccountsReceivable (DR)  total
      - Revenue (CR)             sum(unit_price_minor * qty) across lines (exclusive of tax)
      - TaxPayable (CR)          sum(tax_minor) across lines
    """
    where = ["ti.tenant_id=:t", "ti.status IN ('posted','exported')", "ti.created_at >= :f", "ti.created_at < :to"]
    params = {"t": tenant_id, "f": date_from, "to": date_to}
    if site_id:
        where.append("COALESCE(ti.site_id,'') = COALESCE(:s,'')")
        params["s"] = site_id

    q = f"""
      SELECT ti.id, ti.site_id, ti.currency,
             COALESCE(SUM(til.qty * til.unit_price_minor),0) AS net_minor,
             COALESCE(SUM(til.tax_minor),0) AS tax_minor,
             COALESCE(SUM(til.qty * til.unit_price_minor) + SUM(til.tax_minor),0) AS total_minor
        FROM trade_invoices ti
        JOIN trade_invoice_lines til ON til.invoice_id = ti.id
       WHERE {' AND '.join(where)}
       GROUP BY ti.id, ti.site_id, ti.currency
       ORDER BY ti.id
    """

    with SessionLocal() as db:
        rows = db.execute(text(q), params).all()

    # CSV: date,invoice_id,site_id,account,debit_minor,credit_minor,currency
    lines = ["date,invoice_id,site_id,account,debit_minor,credit_minor,currency"]
    # simplified: use posted_at as date; fallback to current_date if null
    with SessionLocal() as db:
        for r in rows:
            inv_id, site, cur, net, tax, total = r
            posted_at = db.execute(text("SELECT posted_at FROM trade_invoices WHERE id=:id"), {"id": inv_id}).scalar()
            day = (posted_at.date().isoformat() if posted_at else time.strftime("%Y-%m-%d"))

            # AR (DR)
            lines.append(f"{day},{inv_id},{site or ''},AccountsReceivable,{total},0,{cur}")
            # Revenue (CR)
            if int(net or 0) > 0:
                lines.append(f"{day},{inv_id},{site or ''},Revenue,0,{int(net)}, {cur}")
            # TaxPayable (CR)
            if int(tax or 0) > 0:
                lines.append(f"{day},{inv_id},{site or ''},TaxPayable,0,{int(tax)}, {cur}")

    return PlainTextResponse("\n".join(lines))