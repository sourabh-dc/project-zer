"""
Outbox consumer for the Data Intelligence Service.

WHY an outbox pattern instead of direct event subscriptions?
  The outbox guarantees at-least-once delivery even if this service is down.
  Events written by provisioning_service/orders_service to the outbox_events
  table are never lost — they wait in the DB until we consume them.

WHY poll instead of push (e.g. Service Bus)?
  Polling with FOR UPDATE SKIP LOCKED is simpler, requires no extra
  infrastructure, and is exactly what the other services do. For the volumes
  ZeroQue handles, polling every 2 seconds is plenty fast.

WHY consumer='data_intelligence_service'?
  Each consumer gets its own delivery rows in outbox_event_delivery.
  graph_service, vector_service, and data_intelligence_service all read
  the SAME outbox_events but have independent delivery tracking.
  Delivery rows for 'data_intelligence_service' are created by:
    - provisioning_service/core/helpers/outbox_helpers.py (Sprint 0 fix)
    - orders_service/core/helpers/outbox_helpers.py (Sprint 0 fix)

HOW handlers are registered:
  main.py calls register_handler(prefix, fn) at startup.
  prefix is the first segment of event_type (e.g. 'product' from 'product.created').
  Multiple handlers per prefix are supported (e.g. graph + vector for 'product').
"""
import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from data_intelligence_service.core.config import SETTINGS
from data_intelligence_service.core.logger import logger

_handlers: Dict[str, List[Callable]] = {}

def register_handler(event_type_prefix: str, handler: Callable):
    """Register a handler for an event type prefix (e.g. 'product', 'user').

    Multiple handlers per prefix are allowed and all will be called in order.
    Handlers can be sync or async — the dispatcher handles both.
    """
    if event_type_prefix not in _handlers:
        _handlers[event_type_prefix] = []
    _handlers[event_type_prefix].append(handler)

def _get_engine():
    return create_engine(SETTINGS.POSTGRES_URL, pool_pre_ping=True)

async def start_polling():
    """Main polling loop — runs until cancelled."""
    engine = _get_engine()
    Session = sessionmaker(bind=engine)

    logger.info(
        f"Outbox consumer started (interval={SETTINGS.POLL_INTERVAL_SECONDS}s, batch={SETTINGS.POLL_BATCH_SIZE})"
    )

    while True:
        try:
            session = Session()
            try:
                events = _claim_batch(session)
                if events:
                    logger.info(f"Claimed {len(events)} outbox events")
                for evt in events:
                    await _dispatch(session, evt)
            finally:
                session.close()
        except Exception as exc:
            logger.error(f"Poll cycle error: {exc}", exc_info=True)

        await asyncio.sleep(SETTINGS.POLL_INTERVAL_SECONDS)

def _claim_batch(session) -> List[dict]:
    # Poll for 'data_intelligence_service' consumer instead of separate ones
    result = session.execute(
        text("""
            UPDATE outbox_event_delivery
            SET    status = 'processing'
            WHERE  id IN (
                SELECT d.id FROM outbox_event_delivery d
                WHERE  d.consumer = 'data_intelligence_service'
                  AND  d.status = 'pending'
                ORDER  BY d.created_at
                LIMIT  :limit
                FOR UPDATE SKIP LOCKED
            )
            RETURNING id, event_id, retry_count, max_retries
        """),
        {"limit": SETTINGS.POLL_BATCH_SIZE},
    )
    session.commit()

    delivery_rows = result.fetchall()
    if not delivery_rows:
        return []

    delivery_map = {}
    event_ids = []
    for r in delivery_rows:
        eid_str = str(r.event_id)
        delivery_map[eid_str] = {
            "delivery_id": r.id,
            "delivery_retry_count": r.retry_count,
            "delivery_max_retries": r.max_retries,
        }
        event_ids.append(r.event_id)

    event_result = session.execute(
        text("""
            SELECT id, tenant_id, aggregate_type, aggregate_id,
                   event_type, payload
            FROM   outbox_events
            WHERE  id = ANY(:event_ids)
        """),
        {"event_ids": event_ids},
    )

    events = []
    for r in event_result.fetchall():
        payload = r.payload if isinstance(r.payload, dict) else json.loads(r.payload or "{}")
        dm = delivery_map[str(r.id)]
        events.append({
            "id": r.id,
            "delivery_id": dm["delivery_id"],
            "delivery_retry_count": dm["delivery_retry_count"],
            "delivery_max_retries": dm["delivery_max_retries"],
            "tenant_id": r.tenant_id,
            "aggregate_type": r.aggregate_type,
            "aggregate_id": r.aggregate_id,
            "event_type": r.event_type,
            "payload": payload,
        })
    return events

async def _dispatch(session, event: dict):
    event_type: str = event["event_type"]
    prefix = event_type.split(".")[0]

    handlers = _handlers.get(prefix)
    if not handlers:
        logger.debug(f"No handler for event type '{event_type}', marking completed")
        _mark_completed(session, event["delivery_id"])
        return

    try:
        for handler in handlers:
            # Check if it's an async handler
            if asyncio.iscoroutinefunction(handler):
                await handler(event)
            else:
                handler(event)
        _mark_completed(session, event["delivery_id"])
    except Exception as exc:
        logger.error(f"Handler error for {event_type} (id={event['id']}): {exc}", exc_info=True)
        _mark_failed(session, event)

def _mark_completed(session, delivery_id):
    session.execute(
        text("""
            UPDATE outbox_event_delivery
            SET    status = 'completed', processed_at = NOW()
            WHERE  id = :did
        """),
        {"did": delivery_id},
    )
    session.commit()

def _mark_failed(session, event: dict):
    delivery_id = event["delivery_id"]
    new_retry = event["delivery_retry_count"] + 1
    max_retries = event.get("delivery_max_retries", 3)
    new_status = "dead_letter" if new_retry >= max_retries else "pending"

    session.execute(
        text("""
            UPDATE outbox_event_delivery
            SET    status = :st, retry_count = :rc
            WHERE  id = :did
        """),
        {"st": new_status, "rc": new_retry, "did": delivery_id},
    )
    session.commit()
    if new_status == "dead_letter":
        logger.warning(f"Delivery {delivery_id} moved to dead_letter after {new_retry} retries")
