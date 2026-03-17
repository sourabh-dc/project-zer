"""
Vector Service — Outbox consumer.

Polls the `outbox_event_delivery` table for delivery rows assigned to
'vector_service' and dispatches events to embedding handlers.

Each consumer has independent delivery tracking — the vector service
no longer depends on the graph service finishing first.
"""
import asyncio
import json
import uuid
from typing import Callable, Dict, List

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from vector_service.core.config import SETTINGS
from vector_service.core.logger import logger

_handlers: Dict[str, Callable] = {}


def register_handler(event_type_prefix: str, handler: Callable):
    _handlers[event_type_prefix] = handler


def _get_engine():
    return create_engine(SETTINGS.POSTGRES_URL, pool_pre_ping=True)


async def start_polling():
    engine = _get_engine()
    Session = sessionmaker(bind=engine)

    logger.info(
        f"Vector outbox consumer started (interval={SETTINGS.POLL_INTERVAL_SECONDS}s, batch={SETTINGS.POLL_BATCH_SIZE})"
    )

    while True:
        try:
            session = Session()
            try:
                events = _claim_batch(session)
                if events:
                    logger.info(f"[Vector] Claimed {len(events)} outbox events")
                for evt in events:
                    await _dispatch(session, evt)
            finally:
                session.close()
        except Exception as exc:
            logger.error(f"[Vector] Poll cycle error: {exc}", exc_info=True)

        await asyncio.sleep(SETTINGS.POLL_INTERVAL_SECONDS)


def _claim_batch(session) -> List[dict]:
    """Atomically claim a batch of pending delivery rows for vector_service."""
    result = session.execute(
        text("""
            UPDATE outbox_event_delivery
            SET    status = 'processing'
            WHERE  id IN (
                SELECT d.id FROM outbox_event_delivery d
                WHERE  d.consumer = 'vector_service'
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

    # Build a map from event_id → delivery metadata
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

    # Load the actual event data for each claimed delivery
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

    handler = _handlers.get(prefix)
    if not handler:
        _mark_completed(session, event["delivery_id"])
        return

    try:
        await handler(event)
        _mark_completed(session, event["delivery_id"])
    except Exception as exc:
        logger.error(f"[Vector] Handler error for {event_type}: {exc}", exc_info=True)
        _mark_failed(session, event)


def _mark_completed(session, delivery_id):
    """Mark a delivery row as completed."""
    try:
        session.execute(
            text("""
                UPDATE outbox_event_delivery
                SET    status = 'completed', processed_at = NOW()
                WHERE  id = :did
            """),
            {"did": delivery_id},
        )
        session.commit()
    except Exception:
        session.rollback()


def _mark_failed(session, event: dict):
    """Retry or dead-letter a failed delivery."""
    delivery_id = event["delivery_id"]
    new_retry = event["delivery_retry_count"] + 1
    max_retries = event.get("delivery_max_retries", 3)
    new_status = "dead_letter" if new_retry >= max_retries else "pending"

    try:
        session.execute(
            text("""
                UPDATE outbox_event_delivery
                SET    status = :st, retry_count = :rc
                WHERE  id = :did
            """),
            {"st": new_status, "rc": new_retry, "did": delivery_id},
        )
        session.commit()
    except Exception:
        session.rollback()

    if new_status == "dead_letter":
        logger.warning(f"[Vector] Delivery {delivery_id} moved to dead_letter after {new_retry} retries")
