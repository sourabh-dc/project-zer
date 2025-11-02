# Audit logging
import json
from datetime import datetime
from typing import Optional, Dict, Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from services.cv_gateway.models import OutboxEvent, AuditLog
from services.cv_gateway.utils.cv_gateway_logger import logger


def audit_log(db_session, action: str, resource_type: str, resource_id: str, user_context: Dict[str, Any],
              request_data: Dict[str, Any] = None, response_status: int = None, error_message: str = None,
              ip_address: str = None, user_agent: str = None):
    """Create audit log entry"""
    try:
        # Create audit log entry
        from sqlalchemy import text

        db_session.execute(text("""
                                INSERT INTO audit_logs (tenant_id, table_name, record_id, operation, new_values,
                                                        changed_by, ip_address, user_agent)
                                VALUES (:tenant_id, :table_name, :record_id, :operation, :new_values, :changed_by,
                                        :ip_address, :user_agent)
                                """), {
                               "tenant_id": user_context["tenant_id"],
                               "table_name": resource_type,
                               "record_id": resource_id,
                               "operation": action,
                               "new_values": json.dumps({
                                   "request_data": request_data,
                                   "response_status": response_status,
                                   "error_message": error_message,
                                   "user_id": user_context.get("user_id"),
                                   "tenant_id": user_context.get("tenant_id")
                               }),
                               "changed_by": user_context.get("user_id"),
                               "ip_address": ip_address,
                               "user_agent": user_agent
                           })

        db_session.commit()

    except Exception as e:
        logger.warning(f"Failed to create audit log: {e}")
        # Don't fail the main operation if audit logging fails


async def _map_provider(db: Session, provider: str, entity_type: str, external_id: str) -> Optional[str]:
    """Map external provider ID to local ID"""
    row = db.execute(text("""
                          SELECT local_id
                          FROM provider_mappings
                          WHERE provider = :p
                            AND entity_type = :et
                            AND external_id = :eid LIMIT 1
                          """), {"p": provider, "et": entity_type, "eid": external_id}).first()
    return row[0] if row else None


async def _update_daily(db: Session, when: datetime, tenant_id: str, site_id: Optional[str],
                        store_id: Optional[str], meter_code: str, delta: int):
    """Update daily usage aggregates"""
    day = when.date()
    upd = db.execute(text("""
                          UPDATE usage_aggregates_daily
                          SET value = value + :delta
                          WHERE day =:d
                            AND tenant_id=:t
                            AND COALESCE (site_id
                              , '')= COALESCE (:s
                              , '')
                            AND COALESCE (store_id
                              , '')= COALESCE (:st
                              , '')
                            AND meter_code=:m
                          """),
                     {"delta": delta, "d": day, "t": tenant_id, "s": site_id, "st": store_id, "m": meter_code}).rowcount

    if upd == 0:
        try:
            db.execute(text("""
                            INSERT INTO usage_aggregates_daily(day, tenant_id, site_id, store_id, meter_code, value)
                            VALUES (:d, :t, :s, :st, :m, :v)
                            """), {"d": day, "t": tenant_id, "s": site_id, "st": store_id, "m": meter_code, "v": delta})
        except Exception:
            # Race condition - try update again
            db.execute(text("""
                            UPDATE usage_aggregates_daily
                            SET value = value + :delta
                            WHERE day =:d
                              AND tenant_id=:t
                              AND COALESCE (site_id
                                , '')= COALESCE (:s
                                , '')
                              AND COALESCE (store_id
                                , '')= COALESCE (:st
                                , '')
                              AND meter_code=:m
                            """),
                       {"delta": delta, "d": day, "t": tenant_id, "s": site_id, "st": store_id, "m": meter_code})


async def _approval_cover_and_consume(db: Session, cost_centre_id: str, user_id: str, amount: int) -> bool:
    """Check and consume approval coverage for budget overspend"""
    need = amount
    for scoped in (True, False):
        rows = db.execute(text("""
                               SELECT id, remaining_minor
                               FROM approval_requests_new
                               WHERE cost_centre_id = :cc
                                 AND status = 'approved'
                                 AND (:u IS NULL OR (user_scope_id = :u))
                                 AND (:scoped = TRUE AND user_scope_id IS NOT NULL OR
                                      :scoped = FALSE AND user_scope_id IS NULL)
                               ORDER BY approved_at DESC NULLS LAST, id DESC
                               """), {"cc": cost_centre_id, "u": user_id, "scoped": scoped}).all()

        for r in rows:
            if need <= 0:
                break
            ar_id, rem = int(r[0]), int(r[1] or 0)
            if rem <= 0:
                continue
            take = min(rem, need)
            db.execute(text("UPDATE approval_requests_new SET remaining_minor = remaining_minor - :take WHERE id=:id"),
                       {"take": take, "id": ar_id})
            need -= take
    return need == 0


async def _review_unknown_item(db: Session, provider: str, tenant_id: str, site_id: str, store_id: str,
                               external_sku: str, name: str, qty: int, price_minor: int, payload_fragment: dict):
    """Record unknown item for review"""
    db.execute(text("""
                    INSERT INTO cv_unknown_item_reviews(tenant_id, site_id, store_id, provider,
                                                        external_sku, name, qty, price_minor, payload_json, status)
                    VALUES (:t, :si, :st, :p, :esk, :n, :q, :pm, :pl, 'pending')
                    """), {"t": tenant_id, "si": site_id, "st": store_id, "p": provider,
                           "esk": external_sku, "n": name, "q": qty, "pm": price_minor,
                           "pl": json.dumps(payload_fragment)})


async def _apply_inventory_decrements(db: Session, store_id: str, items: list[dict]):
    """Apply inventory decrements for sold items"""
    for item in items:
        sku = item["sku"]
        qty = int(item["qty"])

        # Update inventory_new table
        upd = db.execute(text("UPDATE inventory_new SET qty = qty - :q WHERE store_id=:st AND sku=:s"),
                         {"q": qty, "st": store_id, "s": sku}).rowcount
        if upd == 0:
            db.execute(text("INSERT INTO inventory_new(store_id, sku, qty) VALUES(:st, :s, :q)"),
                       {"st": store_id, "s": sku, "q": -qty})

        # Record inventory movement
        db.execute(text("""
                        INSERT INTO inventory_movements(store_id, sku, delta, reason, created_at)
                        VALUES (:st, :s, :d, 'cv_sale', NOW())
                        """), {"st": store_id, "s": sku, "d": -qty})


async def publish_event(db: Session, event_type: str, event_data: dict, tenant_id: Optional[str] = None):
    """Publish event to outbox for reliable delivery"""
    event = OutboxEvent(
        tenant_id=tenant_id,
        event_type=event_type,
        event_data=event_data,
        status="pending"
    )
    db.add(event)
    db.commit()


async def log_audit(db: Session, action: str, resource_type: str, resource_id: Optional[str] = None,
                    details: Optional[dict] = None, user_id: Optional[str] = None, tenant_id: Optional[str] = None):
    """Log audit trail"""
    audit = AuditLog(
        tenant_id=tenant_id,
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details
    )
    db.add(audit)
    db.commit()