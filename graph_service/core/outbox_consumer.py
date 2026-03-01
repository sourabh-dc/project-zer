"""
Graph Service — Outbox event consumer.

Polls the `outbox_events` table in PostgreSQL and dispatches
events to the appropriate graph handler for projection into Neo4j.

Follows the Transactional Outbox pattern:
  1. Claim a batch (status='pending' → 'processing')
  2. Dispatch each event to a handler
  3. Mark as 'processed' on success or increment retry_count on failure
"""
import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from graph_service.core.config import SETTINGS
from graph_service.core.logger import logger

_handlers: Dict[str, Callable] = {}


def register_handler(event_type_prefix: str, handler: Callable):
    """Register a handler for an event type prefix.
    E.g. register_handler("site", handle_site_events) will match
    site.created, site.updated, site.deleted.
    """
    _handlers[event_type_prefix] = handler


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
    """Atomically claim a batch of pending events."""
    result = session.execute(
        text("""
            UPDATE outbox_events
            SET    status = 'processing', updated_at = NOW()
            WHERE  id IN (
                SELECT id FROM outbox_events
                WHERE  status = 'pending'
                ORDER  BY created_at
                LIMIT  :limit
                FOR UPDATE SKIP LOCKED
            )
            RETURNING id, tenant_id, aggregate_type, aggregate_id,
                      event_type, payload, retry_count, max_retries
        """),
        {"limit": SETTINGS.POLL_BATCH_SIZE},
    )
    session.commit()

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
            "max_retries": r.max_retries,
        })
    return events


async def _dispatch(session, event: dict):
    """Route an event to its handler and update status."""
    event_type: str = event["event_type"]
    prefix = event_type.split(".")[0]

    handler = _handlers.get(prefix)
    if not handler:
        logger.debug(f"No handler for event type '{event_type}', marking processed")
        _mark_processed(session, event["id"])
        return

    try:
        handler(event)
        _mark_processed(session, event["id"])
    except Exception as exc:
        logger.error(f"Handler error for {event_type} (id={event['id']}): {exc}", exc_info=True)
        _mark_failed(session, event)


def _mark_processed(session, event_id: uuid.UUID):
    session.execute(
        text("""
            UPDATE outbox_events
            SET    status = 'processed', processed_at = NOW(), updated_at = NOW()
            WHERE  id = :eid
        """),
        {"eid": event_id},
    )
    session.commit()


def _mark_failed(session, event: dict):
    new_retry = event["retry_count"] + 1
    new_status = "dead_letter" if new_retry >= event["max_retries"] else "pending"

    session.execute(
        text("""
            UPDATE outbox_events
            SET    status = :st, retry_count = :rc, updated_at = NOW()
            WHERE  id = :eid
        """),
        {"st": new_status, "rc": new_retry, "eid": event["id"]},
    )
    session.commit()
    if new_status == "dead_letter":
        logger.warning(f"Event {event['id']} moved to dead_letter after {new_retry} retries")
