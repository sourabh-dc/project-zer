import time
import uuid
from typing import Dict

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..repositories.database_ops import get_pricebooks_db, audit, create_price_rule_db, get_cached_price
from ..repositories.pricing_saga import PricebookSaga
from ..schemas import PricebookRequest, PriceRuleRequest, PriceCalculationRequest, PriceCalculationResponse
from ..utils.metrics import pricing_operations_total, pricing_operation_duration
from ..utils.pricing_logger import logger

def calculate_price(db, product_id, variant_id, pricebook_id, quantity, base_price_minor):
    """Calculate price based on rules"""
    try:
        # Get applicable rules
        rules = db.execute(text("""
                                SELECT *
                                FROM price_rules_v2
                                WHERE pricebook_id = :pricebook_id
                                  AND (product_id = :product_id OR product_id IS NULL)
                                  AND (variant_id = :variant_id OR variant_id IS NULL)
                                  AND is_active = true
                                  AND (valid_from IS NULL OR valid_from <= NOW())
                                  AND (valid_until IS NULL OR valid_until >= NOW())
                                  AND (min_quantity IS NULL OR min_quantity <= :quantity)
                                  AND (max_quantity IS NULL OR max_quantity >= :quantity)
                                ORDER BY product_id DESC, variant_id DESC, created_at DESC
                                """), {
                               "pricebook_id": pricebook_id,
                               "product_id": product_id,
                               "variant_id": variant_id,
                               "quantity": quantity
                           }).fetchall()

        calculated_price = base_price_minor
        applied_rules = []

        for rule in rules:
            if rule.rule_type == "fixed":
                calculated_price = rule.rule_value * 100  # Convert to minor units
            elif rule.rule_type == "percentage":
                calculated_price = int(calculated_price * (1 + rule.rule_value / 100))
            elif rule.rule_type == "formula":
                # TODO: Implement formula evaluation
                pass

            applied_rules.append({
                "rule_id": str(rule.rule_id),
                "rule_type": rule.rule_type,
                "rule_value": float(rule.rule_value),
                "applied_price": calculated_price
            })

        return calculated_price, applied_rules

    except Exception as e:
        logger.error("Price calculation failed", error=str(e))
        return base_price_minor, []


async def create_pricebook(req: PricebookRequest, db: Session, uctx: Dict):
    """Create a new pricebook"""
    start = time.time()
    try:
        pricing_operations_total.labels(operation="create_pricebook", status="start").inc()

        pricebook_id = uuid.uuid4()
        tenant_id = uctx["tenant_id"]

        saga = PricebookSaga(db)
        result = await saga.exec(pricebook_id, tenant_id, req, uctx)

        pricing_operations_total.labels(operation="create_pricebook", status="ok").inc()
        pricing_operation_duration.labels(operation="create_pricebook").observe(time.time() - start)

        return result

    except ValueError as e:
        pricing_operations_total.labels(operation="create_pricebook", status="fail").inc()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        pricing_operations_total.labels(operation="create_pricebook", status="fail").inc()
        logger.error("Pricebook creation failed", error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")


async def get_pricebooks(tenant_id: str, limit: int, offset: int, db: Session):
    """List pricebooks for a tenant"""
    try:
        pricebooks = get_pricebooks_db(tenant_id, limit, offset, db)

        return pricebooks

    except Exception as e:
        logger.error("Failed to list pricebooks", error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")


async def create_price_rule(pricebook_id: str, req: PriceRuleRequest, db: Session, uctx: Dict):
    """Create a price rule"""
    try:
        rule_id = uuid.uuid4()
        create_price_rule_db(db, pricebook_id, rule_id, req)

        # Audit log
        audit(db, uctx["tenant_id"], uctx["user_id"], "CREATE", "price_rule", str(rule_id), req.dict())

        return {"rule_id": str(rule_id), "created": True}

    except Exception as e:
        logger.error("Failed to create price rule", error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")


async def calculate_price_service(
        req: PriceCalculationRequest,
        db: Session
):
    """Calculate price for a product"""
    try:
        # Check cache first
        cached = get_cached_price(db, req)

        if cached:
            return PriceCalculationResponse(
                product_id=req.product_id,
                variant_id=req.variant_id,
                pricebook_id=req.pricebook_id,
                quantity=req.quantity,
                base_price_minor=req.base_price_minor,
                calculated_price_minor=cached.calculated_price_minor,
                currency="GBP",
                applied_rules=[]
            )

        # Calculate price
        calculated_price, applied_rules = calculate_price(
            db, req.product_id, req.variant_id, req.pricebook_id, req.quantity, req.base_price_minor
        )

        return PriceCalculationResponse(
            product_id=req.product_id,
            variant_id=req.variant_id,
            pricebook_id=req.pricebook_id,
            quantity=req.quantity,
            base_price_minor=req.base_price_minor,
            calculated_price_minor=calculated_price,
            currency="GBP",
            applied_rules=applied_rules
        )

    except Exception as e:
        logger.error("Price calculation failed", error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")