"""
Vector Service — Outbox consumer.

Same pattern as graph_service/core/outbox_consumer.py but runs
independently. Only consumes product and category events
(entities that need semantic search).
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
    """Claim events that the vector service cares about.

    Uses a separate status column approach: we only pick events
    whose aggregate_type is product or category AND status is 'processed'
    (already handled by graph service) but vector_status is 'pending'.

    Fallback: if vector_status column doesn't exist, we use a
    separate tracking table.
    """
    try:
        result = session.execute(
            text("""
                SELECT id, tenant_id, aggregate_type, aggregate_id,
                       event_type, payload, retry_count
                FROM   outbox_events
                WHERE  status = 'processed'
                  AND  aggregate_type IN ('product', 'category')
                  AND  id NOT IN (SELECT event_id FROM vector_event_log)
                ORDER  BY created_at
                LIMIT  :limit
            """),
            {"limit": SETTINGS.POLL_BATCH_SIZE},
        )
        rows = result.fetchall()
    except Exception:
        result = session.execute(
            text("""
                SELECT id, tenant_id, aggregate_type, aggregate_id,
                       event_type, payload, retry_count
                FROM   outbox_events
                WHERE  status = 'processed'
                  AND  aggregate_type IN ('product', 'category')
                ORDER  BY created_at
                LIMIT  :limit
            """),
            {"limit": SETTINGS.POLL_BATCH_SIZE},
        )
        rows = result.fetchall()

    events = []
    for r in rows:
        payload = r.payload if isinstance(r.payload, dict) else json.loads(r.payload or "{}")
        events.append({
            "id": r.id,
            "tenant_id": r.tenant_id,
            "aggregate_type": r.aggregate_type,
            "aggregate_id": r.aggregate_id,
            "event_type": r.event_type,
            "payload": payload,
            "retry_count": r.retry_count,
        })
    return events


async def _dispatch(session, event: dict):
    event_type: str = event["event_type"]
    prefix = event_type.split(".")[0]

    handler = _handlers.get(prefix)
    if not handler:
        _mark_vector_processed(session, event["id"])
        return

    try:
        await handler(event)
        _mark_vector_processed(session, event["id"])
    except Exception as exc:
        logger.error(f"[Vector] Handler error for {event_type}: {exc}", exc_info=True)


def _mark_vector_processed(session, event_id):
    try:
        session.execute(
            text("""
                INSERT INTO vector_event_log (event_id, processed_at)
                VALUES (:eid, NOW())
                ON CONFLICT (event_id) DO NOTHING
            """),
            {"eid": event_id},
        )
        session.commit()
    except Exception:
        session.rollback()
