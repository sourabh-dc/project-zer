import json
import uuid

from sqlalchemy import text

from services.pricing.models import OutboxEvent, AuditLog, PriceRuleV2
from ..utils.pricing_logger import logger

def store_outbox_event(db, event_type, tenant_id, entity_id, event_data):
    """Store outbox event"""
    event_id = f"evt_{uuid.uuid4().hex[:12]}"
    outbox_event = OutboxEvent(
        event_id=event_id,
        event_type=event_type,
        aggregate_id=tenant_id,
        event_data=json.dumps(event_data),
        status='pending'
    )
    db.add(outbox_event)
    db.commit()
    return event_id

def audit(db, tenant_id, user_id, action, entity_type, entity_id, changes):
    """Audit logging"""
    try:
        log_id = f"aud_{uuid.uuid4().hex[:12]}"
        audit_log = AuditLog(
            log_id=log_id,
            aggregate_id=tenant_id,
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            changes=json.dumps(changes) if changes else None
        )
        db.add(audit_log)
        db.commit()
    except Exception as e:
        logger.warning("Audit failed", error=str(e))


def get_pricebooks_db(tenant_id: str, limit: int, offset: int, db):
    """Get pricebooks from the database"""
    pricebooks = db.execute(
        text(
            "SELECT * FROM pricebooks_v2 WHERE tenant_id = :tenant_id ORDER BY created_at DESC LIMIT :limit OFFSET :offset"),
        {"tenant_id": tenant_id, "limit": limit, "offset": offset}
    ).fetchall()

    return [dict(pricebook._mapping) for pricebook in pricebooks]

def create_price_rule_db(db, pricebook_id: str, rule_id, req):
    """Create a price rule in the database"""
    rule = PriceRuleV2(
        rule_id=rule_id,
        pricebook_id=pricebook_id,
        product_id=req.product_id,
        variant_id=req.variant_id,
        rule_type=req.rule_type,
        rule_value=req.rule_value,
        min_quantity=req.min_quantity,
        max_quantity=req.max_quantity,
        valid_from=req.valid_from,
        valid_until=req.valid_until
    )
    db.add(rule)
    db.commit()
    return {"rule_id": str(rule_id), "created": True}

def get_cached_price(db, req):
    """Get cached calculated price from the database"""
    price = db.execute(text("""
                    SELECT *
                    FROM calculated_prices_v2
                    WHERE product_id = :product_id
                      AND (variant_id = :variant_id OR variant_id IS NULL)
                      AND pricebook_id = :pricebook_id
                      AND quantity = :quantity
                      AND expires_at > NOW()
                    ORDER BY calculated_at DESC LIMIT 1
                    """), {
                   "product_id": req.product_id,
                   "variant_id": req.variant_id,
                   "pricebook_id": req.pricebook_id,
                   "quantity": req.quantity
               }).fetchone()
    return price