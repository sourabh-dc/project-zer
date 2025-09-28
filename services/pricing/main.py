# services/pricing/main.py
from fastapi import FastAPI, Body, Query, HTTPException, Path
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from sqlalchemy import text
import logging, os, json
from datetime import datetime, timedelta
from zeroque_common.db.session import get_engine, init_db, check_db, SessionLocal
from zeroque_common.events.bus import EventBus, EventType, Event
from zeroque_common.events.celery_app import celery_app

SERVICE_NAME = "pricing"
app = FastAPI(title="ZeroQue Pricing Service", version="0.1.0")

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
class StoreProductUpsert(BaseModel):
    store_id: str = Field(..., min_length=1)
    sku: str = Field(..., min_length=1)
    active: bool = True
    base_price_minor: Optional[float] = Field(None, ge=0, description="store-specific base price in pounds")
    currency: str = Field("GBP", pattern=r"^[A-Z]{3}$")

class PriceRuleCreate(BaseModel):
    name: str = Field(..., min_length=1)
    description: Optional[str] = None
    rule_type: str = Field(..., description="percentage|fixed|formula|override")
    rule_config: Dict[str, Any] = Field(..., description="rule-specific configuration")
    priority: int = Field(100, ge=1, le=1000)
    active: bool = True
    tenant_id: Optional[str] = None
    site_id: Optional[str] = None
    store_id: Optional[str] = None

class PriceRuleConditionCreate(BaseModel):
    rule_id: int = Field(..., ge=1)
    condition_type: str = Field(..., description="sku|category|user_role|time|quantity|etc")
    condition_config: Dict[str, Any] = Field(..., description="condition-specific configuration")

class PromotionCreate(BaseModel):
    name: str = Field(..., min_length=1)
    description: Optional[str] = None
    promo_type: str = Field(..., description="discount|tax|bogo|bulk|etc")
    promo_config: Dict[str, Any] = Field(..., description="promotion-specific configuration")
    priority: int = Field(100, ge=1, le=1000)
    active: bool = True
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    tenant_id: Optional[str] = None
    site_id: Optional[str] = None
    store_id: Optional[str] = None

class PriceCalculationRequest(BaseModel):
    store_id: str = Field(..., min_length=1)
    sku: str = Field(..., min_length=1)
    user_id: Optional[str] = None
    currency: str = Field("GBP", pattern=r"^[A-Z]{3}$")
    quantity: int = Field(1, ge=1)
    force_recalculate: bool = False

# ---------- store products ----------
@app.put("/pricing/store-products")
def upsert_store_product(payload: StoreProductUpsert = Body(...)):
    """
    Create or update store-specific product availability and base pricing.
    """
    with SessionLocal() as db:
        # Verify product exists
        prod = db.execute(text("SELECT 1 FROM products WHERE sku=:s"), {"s": payload.sku}).first()
        if not prod:
            raise HTTPException(status_code=400, detail="SKU not found; create product first")

        # Check if store product exists
        exists = db.execute(text("""
            SELECT id FROM store_products WHERE store_id=:st AND sku=:s
        """), {"st": payload.store_id, "s": payload.sku}).first()

        if exists:
            db.execute(text("""
                UPDATE store_products
                   SET active=:a, base_price_minor=:p, currency=:c, updated_at=NOW()
                 WHERE id=:id
            """), {"a": payload.active, "p": payload.base_price_minor, "c": payload.currency, "id": int(exists[0])})
            db.commit()
            log.info("store_product_updated store=%s sku=%s active=%s", payload.store_id, payload.sku, payload.active)
            return {"store_id": payload.store_id, "sku": payload.sku, "updated": True}
        else:
            db.execute(text("""
                INSERT INTO store_products(store_id, sku, active, base_price_minor, currency)
                VALUES(:st, :s, :a, :p, :c)
            """), {"st": payload.store_id, "s": payload.sku, "a": payload.active, "p": payload.base_price_minor, "c": payload.currency})
            db.commit()
            log.info("store_product_created store=%s sku=%s", payload.store_id, payload.sku)
            return {"store_id": payload.store_id, "sku": payload.sku, "created": True}

@app.get("/pricing/store-products")
def list_store_products(store_id: str = Query(...), active: Optional[bool] = Query(None)):
    """
    List products available in a specific store.
    """
    with SessionLocal() as db:
        if active is None:
            rows = db.execute(text("""
                SELECT sp.sku, p.name, p.description, sp.active, sp.base_price_minor, sp.currency
                  FROM store_products sp
                  JOIN products p ON sp.sku = p.sku
                 WHERE sp.store_id = :st
                 ORDER BY sp.sku
            """), {"st": store_id}).all()
        else:
            rows = db.execute(text("""
                SELECT sp.sku, p.name, p.description, sp.active, sp.base_price_minor, sp.currency
                  FROM store_products sp
                  JOIN products p ON sp.sku = p.sku
                 WHERE sp.store_id = :st AND sp.active = :a
                 ORDER BY sp.sku
            """), {"st": store_id, "a": active}).all()
        
        out = [{
            "sku": r[0], "name": r[1], "description": r[2], 
            "active": bool(r[3]), "base_price_minor": r[4], "currency": r[5]
        } for r in rows]
        log.info("store_products_listed store=%s count=%d active=%s", store_id, len(out), active)
        return out

# ---------- price rules ----------
@app.post("/pricing/rules")
def create_price_rule(payload: PriceRuleCreate = Body(...)):
    """
    Create a new pricing rule.
    """
    with SessionLocal() as db:
        db.execute(text("""
            INSERT INTO price_rules(name, description, rule_type, rule_config, priority, active, 
                                  tenant_id, site_id, store_id)
            VALUES(:n, :d, :t, :c, :p, :a, :tid, :sid, :stid)
        """), {
            "n": payload.name, "d": payload.description, "t": payload.rule_type,
            "c": json.dumps(payload.rule_config), "p": payload.priority, "a": payload.active,
            "tid": payload.tenant_id, "sid": payload.site_id, "stid": payload.store_id
        })
        db.commit()
        log.info("price_rule_created name=%s type=%s", payload.name, payload.rule_type)
        return {"created": True, "name": payload.name}

@app.post("/pricing/rules/{rule_id}/conditions")
def add_rule_condition(rule_id: int = Path(...), payload: PriceRuleConditionCreate = Body(...)):
    """
    Add a condition to an existing pricing rule.
    """
    with SessionLocal() as db:
        # Verify rule exists
        rule = db.execute(text("SELECT 1 FROM price_rules WHERE id=:id"), {"id": rule_id}).first()
        if not rule:
            raise HTTPException(status_code=404, detail="Price rule not found")

        db.execute(text("""
            INSERT INTO price_rule_conditions(rule_id, condition_type, condition_config)
            VALUES(:rid, :t, :c)
        """), {"rid": rule_id, "t": payload.condition_type, "c": json.dumps(payload.condition_config)})
        db.commit()
        log.info("rule_condition_added rule_id=%d type=%s", rule_id, payload.condition_type)
        return {"created": True, "rule_id": rule_id}

@app.get("/pricing/rules")
def list_price_rules(store_id: Optional[str] = Query(None), active: Optional[bool] = Query(None)):
    """
    List pricing rules, optionally filtered by store and active status.
    """
    with SessionLocal() as db:
        where_clauses = []
        params = {}
        
        if store_id:
            where_clauses.append("store_id = :st")
            params["st"] = store_id
        if active is not None:
            where_clauses.append("active = :a")
            params["a"] = active
            
        where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
        
        rows = db.execute(text(f"""
            SELECT id, name, description, rule_type, rule_config, priority, active,
                   tenant_id, site_id, store_id, created_at
              FROM price_rules
             WHERE {where_sql}
             ORDER BY priority, name
        """), params).all()
        
        out = [{
            "id": int(r[0]), "name": r[1], "description": r[2], "rule_type": r[3],
            "rule_config": r[4], "priority": int(r[5]), "active": bool(r[6]),
            "tenant_id": r[7], "site_id": r[8], "store_id": r[9], "created_at": r[10]
        } for r in rows]
        log.info("price_rules_listed count=%d store=%s active=%s", len(out), store_id, active)
        return out

# ---------- promotions ----------
@app.post("/pricing/promotions")
def create_promotion(payload: PromotionCreate = Body(...)):
    """
    Create a new promotion.
    """
    with SessionLocal() as db:
        db.execute(text("""
            INSERT INTO promotions(name, description, promo_type, promo_config, priority, active,
                                 valid_from, valid_until, tenant_id, site_id, store_id)
            VALUES(:n, :d, :t, :c, :p, :a, :vf, :vu, :tid, :sid, :stid)
        """), {
            "n": payload.name, "d": payload.description, "t": payload.promo_type,
            "c": json.dumps(payload.promo_config), "p": payload.priority, "a": payload.active,
            "vf": payload.valid_from, "vu": payload.valid_until,
            "tid": payload.tenant_id, "sid": payload.site_id, "stid": payload.store_id
        })
        db.commit()
        log.info("promotion_created name=%s type=%s", payload.name, payload.promo_type)
        return {"created": True, "name": payload.name}

@app.get("/pricing/promotions")
def list_promotions(store_id: Optional[str] = Query(None), active: Optional[bool] = Query(None)):
    """
    List promotions, optionally filtered by store and active status.
    """
    with SessionLocal() as db:
        where_clauses = []
        params = {}
        
        if store_id:
            where_clauses.append("store_id = :st")
            params["st"] = store_id
        if active is not None:
            where_clauses.append("active = :a")
            params["a"] = active
            
        where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
        
        rows = db.execute(text(f"""
            SELECT id, name, description, promo_type, promo_config, priority, active,
                   valid_from, valid_until, tenant_id, site_id, store_id, created_at
              FROM promotions
             WHERE {where_sql}
             ORDER BY priority, name
        """), params).all()
        
        out = [{
            "id": int(r[0]), "name": r[1], "description": r[2], "promo_type": r[3],
            "promo_config": r[4], "priority": int(r[5]), "active": bool(r[6]),
            "valid_from": r[7], "valid_until": r[8], "tenant_id": r[9], "site_id": r[10],
            "store_id": r[11], "created_at": r[12]
        } for r in rows]
        log.info("promotions_listed count=%d store=%s active=%s", len(out), store_id, active)
        return out

# ---------- price calculation ----------
@app.post("/pricing/calculate")
def calculate_price(payload: PriceCalculationRequest = Body(...)):
    """
    Calculate final price for a product in a store, applying all applicable rules and promotions.
    """
    with SessionLocal() as db:
        # Check if we have a cached calculation
        if not payload.force_recalculate:
            cached = db.execute(text("""
                SELECT base_price_minor, final_price_minor, applied_rules, applied_promotions
                  FROM calculated_prices
                 WHERE store_id=:st AND sku=:s AND user_id=:u AND currency=:c
                   AND expires_at > NOW()
            """), {
                "st": payload.store_id, "s": payload.sku, "u": payload.user_id, "c": payload.currency
            }).first()
            
            if cached:
                log.info("price_cached store=%s sku=%s user=%s price=%d", 
                        payload.store_id, payload.sku, payload.user_id, int(cached[1]))
                return {
                    "store_id": payload.store_id, "sku": payload.sku, "user_id": payload.user_id,
                    "currency": payload.currency, "base_price_minor": float(cached[0]),
                    "final_price_minor": float(cached[1]), "applied_rules": cached[2], 
                    "applied_promotions": cached[3], "cached": True
                }

        # Get base price
        base_price_row = db.execute(text("""
            SELECT base_price_minor FROM store_products
             WHERE store_id=:st AND sku=:s AND active=TRUE
        """), {"st": payload.store_id, "s": payload.sku}).first()
        
        if not base_price_row:
            # Fallback to global price
            global_price_row = db.execute(text("""
                SELECT unit_minor FROM prices
                 WHERE sku=:s AND currency=:c AND active=TRUE
            """), {"s": payload.sku, "c": payload.currency}).first()
            
            if not global_price_row:
                raise HTTPException(status_code=400, detail=f"No price found for SKU {payload.sku}")
            
            base_price = float(global_price_row[0])
        else:
            base_price = float(base_price_row[0]) or 0.0

        # Apply pricing rules and promotions
        final_price = base_price
        applied_rules = []
        applied_promotions = []
        
        # Get applicable pricing rules (ordered by priority)
        rules = db.execute(text("""
            SELECT id, name, rule_type, rule_config, priority
              FROM price_rules
             WHERE active=TRUE AND (store_id=:st OR store_id IS NULL)
             ORDER BY priority, id
        """), {"st": payload.store_id}).all()
        
        # Apply pricing rules
        for rule in rules:
            rule_id, rule_name, rule_type, rule_config, priority = rule
            rule_config = json.loads(rule_config) if isinstance(rule_config, str) else rule_config
            
            # Simple rule application (no conditions for now)
            if rule_type == "percentage":
                percentage = rule_config.get("percentage", 0)
                adjustment = round(final_price * percentage / 100, 2)
                new_price = round(final_price + adjustment, 2)
                if new_price != final_price:
                    applied_rules.append({
                        "rule_id": rule_id,
                        "rule_name": rule_name,
                        "rule_type": rule_type,
                        "old_price": final_price,
                        "new_price": new_price,
                        "adjustment": adjustment
                    })
                    final_price = new_price
            elif rule_type == "fixed":
                amount = rule_config.get("amount_minor", 0)  # Now in pounds
                new_price = round(final_price + amount, 2)
                if new_price != final_price:
                    applied_rules.append({
                        "rule_id": rule_id,
                        "rule_name": rule_name,
                        "rule_type": rule_type,
                        "old_price": final_price,
                        "new_price": new_price,
                        "adjustment": amount
                    })
                    final_price = new_price
            elif rule_type == "override":
                override_price = rule_config.get("price_minor", final_price)  # Now in pounds
                if override_price != final_price:
                    applied_rules.append({
                        "rule_id": rule_id,
                        "rule_name": rule_name,
                        "rule_type": rule_type,
                        "old_price": final_price,
                        "new_price": override_price,
                        "adjustment": override_price - final_price
                    })
                    final_price = override_price
        
        # Get applicable promotions (ordered by priority)
        now = datetime.utcnow()
        promotions = db.execute(text("""
            SELECT id, name, promo_type, promo_config, priority
              FROM promotions
             WHERE active=TRUE AND (store_id=:st OR store_id IS NULL)
               AND (valid_from IS NULL OR valid_from <= :now)
               AND (valid_until IS NULL OR valid_until >= :now)
             ORDER BY priority, id
        """), {"st": payload.store_id, "now": now}).all()
        
        # Apply promotions
        for promo in promotions:
            promo_id, promo_name, promo_type, promo_config, priority = promo
            promo_config = json.loads(promo_config) if isinstance(promo_config, str) else promo_config
            
            # Simple promotion application (no conditions for now)
            if promo_type == "discount":
                discount_pct = promo_config.get("discount_percentage", 0)
                discount_amount = round(final_price * discount_pct / 100, 2)
                new_price = round(max(0, final_price - discount_amount), 2)
                if new_price != final_price:
                    applied_promotions.append({
                        "promotion_id": promo_id,
                        "promotion_name": promo_name,
                        "promo_type": promo_type,
                        "old_price": final_price,
                        "new_price": new_price,
                        "discount": discount_amount
                    })
                    final_price = new_price
            elif promo_type == "fixed_discount":
                discount_amount = promo_config.get("discount_amount_minor", 0)  # Now in pounds
                new_price = round(max(0, final_price - discount_amount), 2)
                if new_price != final_price:
                    applied_promotions.append({
                        "promotion_id": promo_id,
                        "promotion_name": promo_name,
                        "promo_type": promo_type,
                        "old_price": final_price,
                        "new_price": new_price,
                        "discount": discount_amount
                    })
                    final_price = new_price
            elif promo_type == "tax":
                tax_rate = promo_config.get("tax_rate", 0)
                tax_amount = round(final_price * tax_rate / 100, 2)
                new_price = round(final_price + tax_amount, 2)
                if new_price != final_price:
                    applied_promotions.append({
                        "promotion_id": promo_id,
                        "promotion_name": promo_name,
                        "promo_type": promo_type,
                        "old_price": final_price,
                        "new_price": new_price,
                        "tax": tax_amount
                    })
                    final_price = new_price
            elif promo_type == "bulk":
                tiers = promo_config.get("tiers", [])
                for tier in sorted(tiers, key=lambda x: x["min_quantity"], reverse=True):
                    if payload.quantity >= tier["min_quantity"]:
                        new_price = round(tier["price_minor"] * payload.quantity, 2)  # Now in pounds
                        if new_price != round(final_price * payload.quantity, 2):
                            applied_promotions.append({
                                "promotion_id": promo_id,
                                "promotion_name": promo_name,
                                "promo_type": promo_type,
                                "old_price": round(final_price * payload.quantity, 2),
                                "new_price": new_price,
                                "tier": tier
                            })
                            final_price = round(new_price / payload.quantity, 2)  # Convert back to per-unit price
                        break
        
        # Cache the result
        expires_at = datetime.utcnow() + timedelta(hours=1)
        db.execute(text("""
            INSERT INTO calculated_prices(store_id, sku, user_id, currency, base_price_minor,
                                         final_price_minor, applied_rules, applied_promotions, expires_at)
            VALUES(:st, :s, :u, :c, :bp, :fp, :ar, :ap, :exp)
            ON CONFLICT (store_id, sku, user_id, currency)
            DO UPDATE SET final_price_minor=:fp, applied_rules=:ar, applied_promotions=:ap,
                         calculated_at=NOW(), expires_at=:exp
        """), {
            "st": payload.store_id, "s": payload.sku, "u": payload.user_id, "c": payload.currency,
            "bp": base_price, "fp": final_price, "ar": json.dumps(applied_rules), "ap": json.dumps(applied_promotions), "exp": expires_at
        })
        db.commit()

        log.info("price_calculated store=%s sku=%s user=%s base=%d final=%d", 
                payload.store_id, payload.sku, payload.user_id, base_price, final_price)
        
        # Publish price calculated event
        try:
            price_event = Event(
                event_type=EventType.PRICE_CALCULATED,
                tenant_id="system",  # Pricing events are system-wide
                store_id=payload.store_id,
                user_id=payload.user_id,
                data={
                    "sku": payload.sku,
                    "store_id": payload.store_id,
                    "user_id": payload.user_id,
                    "currency": payload.currency,
                    "base_price_minor": base_price,
                    "final_price_minor": final_price,
                    "applied_rules": applied_rules,
                    "applied_promotions": applied_promotions,
                    "quantity": payload.quantity,
                    "cached": False
                },
                metadata={"service": "pricing", "version": "0.1.0"}
            )
            
            celery_app.send_task(
                "zeroque_common.events.pricing_tasks.process_pricing_event",
                args=[price_event.__dict__],
                queue="pricing"
            )
            log.info("price_event_published store=%s sku=%s final=%d", 
                    payload.store_id, payload.sku, final_price)
        except Exception as e:
            log.warning("Failed to publish price calculated event: %s", str(e))
        
        return {
            "store_id": payload.store_id, "sku": payload.sku, "user_id": payload.user_id,
            "currency": payload.currency, "base_price_minor": base_price,
            "final_price_minor": final_price, "applied_rules": applied_rules,
            "applied_promotions": applied_promotions, "cached": False
        }

@app.get("/pricing/calculate/{store_id}/{sku}")
def get_calculated_price(
    store_id: str = Path(...), 
    sku: str = Path(...),
    user_id: Optional[str] = Query(None),
    currency: str = Query("GBP", pattern=r"^[A-Z]{3}$")
):
    """
    Get cached calculated price for a product.
    """
    with SessionLocal() as db:
        row = db.execute(text("""
            SELECT base_price_minor, final_price_minor, applied_rules, applied_promotions, calculated_at
              FROM calculated_prices
             WHERE store_id=:st AND sku=:s AND user_id=:u AND currency=:c
               AND expires_at > NOW()
        """), {"st": store_id, "s": sku, "u": user_id, "c": currency}).first()
        
        if not row:
            raise HTTPException(status_code=404, detail="No cached price found")
        
        return {
            "store_id": store_id, "sku": sku, "user_id": user_id, "currency": currency,
            "base_price_minor": int(row[0]), "final_price_minor": int(row[1]),
            "applied_rules": row[2], "applied_promotions": row[3], "calculated_at": row[4]
        }
