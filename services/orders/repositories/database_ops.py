import json
import uuid

from fastapi import HTTPException
from sqlalchemy import text

from services.orders.models import AuditLog
from services.orders.utils.orders_logger import logger


def store_outbox(db, event_type, tenant_id, entity_id, event_data):
    """Store outbox event"""
    event_id = f"evt_{uuid.uuid4().hex[:12]}"
    # Use direct SQL to avoid schema caching issues
    db.execute(text("""
        INSERT INTO outbox_events 
        (event_id, event_type, aggregate_id, event_data, status, retry_count, event_version, max_retries)
        VALUES (:eid, :etype, :aid, :data, 'pending', 0, 1, 3)
    """), {
        "eid": event_id,
        "etype": event_type,
        "aid": tenant_id,
        "data": json.dumps(event_data)
    })
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

def get_orders_from_db(db, tenant_id: str, limit: int = 50, offset: int = 0):
    orders = db.execute(
        text(
            "SELECT * FROM orders_v2 WHERE tenant_id = :tenant_id ORDER BY created_at DESC LIMIT :limit OFFSET :offset"),
        {"tenant_id": tenant_id, "limit": limit, "offset": offset}
    ).fetchall()

    return [dict(order._mapping) for order in orders]

def get_order_by_id(db, order_id: str):
    order = db.execute(
        text("SELECT * FROM orders_v2 WHERE order_id = :id"),
        {"id": order_id}
    ).fetchone()

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    return dict(order._mapping)

def update_order_db(req, order_id: str, db):
    # Build update query
    updates = []
    params = {"id": order_id}

    if req.order_status:
        updates.append("order_status = :order_status")
        params["order_status"] = req.order_status

    if req.payment_status:
        updates.append("payment_status = :payment_status")
        params["payment_status"] = req.payment_status

    if req.fulfillment_status:
        updates.append("fulfillment_status = :fulfillment_status")
        params["fulfillment_status"] = req.fulfillment_status

    if req.metadata:
        updates.append("metadata = :metadata")
        params["metadata"] = json.dumps(req.metadata)

    if not updates:
        raise HTTPException(status_code=400, detail="No updates provided")

    updates.append("updated_at = NOW()")

    db.execute(
        text(f"UPDATE orders_v2 SET {', '.join(updates)} WHERE order_id = :id"),
        params
    )
    db.commit()

def cancel_order_db(order_id: str, db):
    db.execute(
        text("UPDATE orders_v2 SET order_status = 'cancelled', updated_at = NOW() WHERE order_id = :id"),
        {"id": order_id}
    )
    db.commit()