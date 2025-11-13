import uuid
from datetime import datetime, timezone
from typing import Optional
from fastapi import Depends, APIRouter, HTTPException, Query
from sqlalchemy.orm import Session

from Models import Pricebook, Store, Product, Variant, PriceRule
from Schemas import UserContext, PricebookRequest, PriceRuleRequest, PriceCalculationRequest
from core.db_config import get_db
from core.permission_check_helpers import require_permission
from utils.logger import logger
from utils.metrics import req_total, req_duration

app = APIRouter()

# ==================================================================================
# PRICING SERVICE - SIMPLE IMPLEMENTATION
# ==================================================================================

@app.post("/v1/pricing/pricebooks", status_code=201)
async def create_pricebook(
        req: PricebookRequest,
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(require_permission("catalog.products.manage"))
):
    """Create a new pricebook for a store"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_pricebook", status="start").inc()

        # Verify store exists
        store = db.query(Store).filter(Store.store_id == uuid.UUID(req.store_id)).first()
        if not store:
            raise HTTPException(status_code=404, detail="Store not found")

        # Create pricebook
        pricebook = Pricebook(
            pricebook_id=uuid.uuid4(),
            store_id=uuid.UUID(req.store_id),
            tenant_id=store.tenant_id,
            name=req.name,
            description=req.description,
            currency=req.currency,
            is_active=True
        )
        db.add(pricebook)
        db.commit()
        db.refresh(pricebook)

        req_total.labels(operation="create_pricebook", status="success").inc()
        req_duration.labels(operation="create_pricebook").observe(
            (datetime.now() - start).total_seconds()
        )

        logger.info(f"✅ Created pricebook: {pricebook.pricebook_id} ({pricebook.name})")

        return {
            "pricebook_id": str(pricebook.pricebook_id),
            "store_id": str(pricebook.store_id),
            "tenant_id": str(pricebook.tenant_id),
            "name": pricebook.name,
            "description": pricebook.description,
            "currency": pricebook.currency,
            "is_active": pricebook.is_active,
            "created_at": pricebook.created_at.isoformat()
        }
    except ValueError:
        req_total.labels(operation="create_pricebook", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid store ID format")
    except HTTPException:
        req_total.labels(operation="create_pricebook", status="error").inc()
        raise
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_pricebook", status="error").inc()
        logger.error(f"❌ Pricebook creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/pricing/pricebooks")
async def list_pricebooks(
        store_id: Optional[str] = Query(None, description="Filter by store ID"),
        limit: int = Query(100, le=1000, ge=1),
        offset: int = Query(0, ge=0),
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(require_permission("catalog.products.view"))
):
    """List pricebooks with optional store filtering"""
    try:
        q = db.query(Pricebook).filter(Pricebook.is_active == True)
        if store_id:
            q = q.filter(Pricebook.store_id == uuid.UUID(store_id))

        total = q.count()
        pricebooks = q.order_by(Pricebook.created_at.desc()).limit(limit).offset(offset).all()

        return {
            "pricebooks": [
                {
                    "pricebook_id": str(p.pricebook_id),
                    "store_id": str(p.store_id),
                    "tenant_id": str(p.tenant_id),
                    "name": p.name,
                    "description": p.description,
                    "currency": p.currency,
                    "is_active": p.is_active,
                    "created_at": p.created_at.isoformat()
                }
                for p in pricebooks
            ],
            "total": total,
            "limit": limit,
            "offset": offset
        }
    except Exception as e:
        logger.error(f"❌ List pricebooks failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/v1/pricing/pricebooks/{pricebook_id}/rules", status_code=201)
async def create_price_rule(
        pricebook_id: str,
        req: PriceRuleRequest,
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(require_permission("catalog.products.manage"))
):
    """Create a price rule for a pricebook"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_price_rule", status="start").inc()

        # Verify pricebook exists
        pricebook = db.query(Pricebook).filter(Pricebook.pricebook_id == uuid.UUID(pricebook_id)).first()
        if not pricebook:
            raise HTTPException(status_code=404, detail="Pricebook not found")

        # Verify product if provided
        if req.product_id:
            product = db.query(Product).filter(Product.product_id == uuid.UUID(req.product_id)).first()
            if not product:
                raise HTTPException(status_code=404, detail="Product not found")

        # Verify variant if provided
        if req.variant_id:
            variant = db.query(Variant).filter(Variant.variant_id == uuid.UUID(req.variant_id)).first()
            if not variant:
                raise HTTPException(status_code=404, detail="Variant not found")

        # Create price rule
        rule = PriceRule(
            rule_id=uuid.uuid4(),
            pricebook_id=uuid.UUID(pricebook_id),
            product_id=uuid.UUID(req.product_id) if req.product_id else None,
            variant_id=uuid.UUID(req.variant_id) if req.variant_id else None,
            rule_type=req.rule_type,
            rule_value=req.rule_value,
            min_quantity=req.min_quantity,
            max_quantity=req.max_quantity,
            valid_from=req.valid_from,
            valid_until=req.valid_until,
            is_active=True
        )
        db.add(rule)
        db.commit()
        db.refresh(rule)

        req_total.labels(operation="create_price_rule", status="success").inc()
        req_duration.labels(operation="create_price_rule").observe(
            (datetime.now() - start).total_seconds()
        )

        logger.info(f"✅ Created price rule: {rule.rule_id} for pricebook {pricebook_id}")

        return {
            "rule_id": str(rule.rule_id),
            "pricebook_id": str(rule.pricebook_id),
            "product_id": str(rule.product_id) if rule.product_id else None,
            "variant_id": str(rule.variant_id) if rule.variant_id else None,
            "rule_type": rule.rule_type,
            "rule_value": rule.rule_value,
            "min_quantity": rule.min_quantity,
            "max_quantity": rule.max_quantity,
            "valid_from": rule.valid_from.isoformat() if rule.valid_from else None,
            "valid_until": rule.valid_until.isoformat() if rule.valid_until else None,
            "is_active": rule.is_active,
            "created_at": rule.created_at.isoformat()
        }
    except ValueError:
        req_total.labels(operation="create_price_rule", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid ID format")
    except HTTPException:
        req_total.labels(operation="create_price_rule", status="error").inc()
        raise
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_price_rule", status="error").inc()
        logger.error(f"❌ Price rule creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/pricing/pricebooks/{pricebook_id}/rules")
async def list_price_rules(
        pricebook_id: str,
        limit: int = Query(100, le=1000, ge=1),
        offset: int = Query(0, ge=0),
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(require_permission("catalog.products.view"))
):
    """List all price rules for a pricebook"""
    try:
        # Verify pricebook exists
        pricebook = db.query(Pricebook).filter(Pricebook.pricebook_id == uuid.UUID(pricebook_id)).first()
        if not pricebook:
            raise HTTPException(status_code=404, detail="Pricebook not found")

        q = db.query(PriceRule).filter(PriceRule.pricebook_id == uuid.UUID(pricebook_id))
        total = q.count()
        rules = q.order_by(PriceRule.created_at.desc()).limit(limit).offset(offset).all()

        return {
            "pricebook_id": pricebook_id,
            "rules": [
                {
                    "rule_id": str(r.rule_id),
                    "product_id": str(r.product_id) if r.product_id else None,
                    "variant_id": str(r.variant_id) if r.variant_id else None,
                    "rule_type": r.rule_type,
                    "rule_value": r.rule_value,
                    "min_quantity": r.min_quantity,
                    "max_quantity": r.max_quantity,
                    "valid_from": r.valid_from.isoformat() if r.valid_from else None,
                    "valid_until": r.valid_until.isoformat() if r.valid_until else None,
                    "is_active": r.is_active,
                    "created_at": r.created_at.isoformat()
                }
                for r in rules
            ],
            "total": total,
            "limit": limit,
            "offset": offset
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid pricebook ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ List price rules failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/v1/pricing/calculate")
async def calculate_price(
        req: PriceCalculationRequest,
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(require_permission("catalog.products.view"))
):
    """Calculate price for a product based on pricebook rules"""
    start = datetime.now()
    try:
        req_total.labels(operation="calculate_price", status="start").inc()

        # Get base price from product or variant
        base_price_minor = 0
        currency = "GBP"
        product_name = ""

        if req.variant_id:
            # Get variant price
            variant = db.query(Variant).filter(Variant.variant_id == uuid.UUID(req.variant_id)).first()
            if not variant:
                raise HTTPException(status_code=404, detail="Variant not found")
            base_price_minor = variant.price_minor
            currency = variant.currency
            product_name = variant.name
        else:
            # Get product price
            product = db.query(Product).filter(Product.product_id == uuid.UUID(req.product_id)).first()
            if not product:
                raise HTTPException(status_code=404, detail="Product not found")
            base_price_minor = product.base_price_minor
            currency = product.currency
            product_name = product.name

        # Verify pricebook exists
        pricebook = db.query(Pricebook).filter(Pricebook.pricebook_id == uuid.UUID(req.pricebook_id)).first()
        if not pricebook:
            raise HTTPException(status_code=404, detail="Pricebook not found")

        # Get all active rules for this product in this pricebook
        now = datetime.now(timezone.utc)
        q = db.query(PriceRule).filter(
            PriceRule.pricebook_id == uuid.UUID(req.pricebook_id),
            PriceRule.is_active == True
        )

        # Filter by product or variant
        if req.variant_id:
            q = q.filter(
                (PriceRule.variant_id == uuid.UUID(req.variant_id)) |
                (PriceRule.product_id == uuid.UUID(req.product_id)) |
                ((PriceRule.product_id == None) & (PriceRule.variant_id == None))
            )
        else:
            q = q.filter(
                (PriceRule.product_id == uuid.UUID(req.product_id)) |
                ((PriceRule.product_id == None) & (PriceRule.variant_id == None))
            )

        # Filter by date validity
        q = q.filter(
            (PriceRule.valid_from == None) | (PriceRule.valid_from <= now)
        ).filter(
            (PriceRule.valid_until == None) | (PriceRule.valid_until >= now)
        )

        # Filter by quantity
        q = q.filter(
            (PriceRule.min_quantity == None) | (PriceRule.min_quantity <= req.quantity)
        ).filter(
            (PriceRule.max_quantity == None) | (PriceRule.max_quantity >= req.quantity)
        )

        # Order by specificity: variant-specific > product-specific > general
        rules = q.order_by(
            PriceRule.variant_id.desc().nullslast(),
            PriceRule.product_id.desc().nullslast(),
            PriceRule.created_at.desc()
        ).all()

        # Apply rules
        calculated_price_minor = base_price_minor
        applied_rules = []

        for rule in rules:
            old_price = calculated_price_minor

            if rule.rule_type == "fixed":
                # Fixed price overrides
                calculated_price_minor = rule.rule_value
            elif rule.rule_type == "percentage":
                # Percentage adjustment (rule_value in basis points, e.g., 1000 = 10%)
                adjustment = (calculated_price_minor * rule.rule_value) // 10000
                calculated_price_minor = calculated_price_minor + adjustment
            elif rule.rule_type == "discount":
                # Discount (rule_value in basis points, e.g., 1000 = 10% off)
                discount = (calculated_price_minor * rule.rule_value) // 10000
                calculated_price_minor = calculated_price_minor - discount

            applied_rules.append({
                "rule_id": str(rule.rule_id),
                "rule_type": rule.rule_type,
                "rule_value": rule.rule_value,
                "price_before": old_price,
                "price_after": calculated_price_minor
            })

        req_total.labels(operation="calculate_price", status="success").inc()
        req_duration.labels(operation="calculate_price").observe(
            (datetime.now() - start).total_seconds()
        )

        logger.info(f"✅ Calculated price for product {req.product_id}: {base_price_minor} -> {calculated_price_minor}")

        return {
            "product_id": req.product_id,
            "variant_id": req.variant_id,
            "pricebook_id": req.pricebook_id,
            "quantity": req.quantity,
            "product_name": product_name,
            "base_price_minor": base_price_minor,
            "calculated_price_minor": calculated_price_minor,
            "currency": currency,
            "rules_applied_count": len(applied_rules),
            "applied_rules": applied_rules
        }
    except ValueError:
        req_total.labels(operation="calculate_price", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid ID format")
    except HTTPException:
        req_total.labels(operation="calculate_price", status="error").inc()
        raise
    except Exception as e:
        req_total.labels(operation="calculate_price", status="error").inc()
        logger.error(f"❌ Price calculation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")