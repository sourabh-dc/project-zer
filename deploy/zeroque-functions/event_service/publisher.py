"""
event_service.publisher
-----------------------
Outbox publisher — reads pending events from the outbox_events table,
publishes them to the message broker, and marks them as published.

This is the core logic. It's called by:
    - publisher_func/function_app.py  (Azure Function timer trigger)
    - scripts/run_local.py            (local development loop)

The publish cycle:
    1. Claim a batch of pending events (SELECT ... FOR UPDATE SKIP LOCKED)
    2. Publish them to the transport (Service Bus or local queue)
    3. Mark as 'published' with timestamp
    4. On failure: increment retry, dead-letter if exhausted
"""
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from sqlalchemy import text
from sqlalchemy.orm import Session

from event_service.transport import EventTransport

logger = logging.getLogger("event_service.publisher")


async def publish_pending_events(
    session: Session,
    transport: EventTransport,
    batch_size: int = 100,
) -> int:
    """Run one publish cycle. Returns the number of events published."""

    # 1. Claim a batch
    events = _claim_batch(session, batch_size)
    if not events:
        return 0

    logger.info(f"Publisher: claimed {len(events)} pending events")

    # 2. Group by topic and publish
    by_topic: Dict[str, List[dict]] = {}
    for evt in events:
        topic = evt["topic"] or "domain-events"
        by_topic.setdefault(topic, []).append(evt)

    published_ids = []
    failed = []

    for topic, batch in by_topic.items():
        try:
            messages = [
                {
                    "event_id": str(e["id"]),
                    "tenant_id": str(e["tenant_id"]),
                    "event_type": e["event_type"],
                    "aggregate_type": e["aggregate_type"],
                    "aggregate_id": str(e["aggregate_id"]) if e["aggregate_id"] else None,
                    "payload": e["payload"],
                    "created_at": e["created_at"].isoformat() if e["created_at"] else None,
                }
                for e in batch
            ]
            await transport.publish(topic, messages)
            published_ids.extend(e["id"] for e in batch)
        except Exception as exc:
            logger.error(f"Publisher: failed to publish to topic '{topic}': {exc}")
            failed.extend(batch)

    # 3. Mark published
    if published_ids:
        _mark_published(session, published_ids)
        logger.info(f"Publisher: marked {len(published_ids)} events as published")

    # 4. Handle failures
    for evt in failed:
        _mark_failed(session, evt)

    return len(published_ids)


def _claim_batch(session: Session, batch_size: int) -> List[Dict[str, Any]]:
    """Atomically claim pending outbox events for publishing."""
    result = session.execute(
        text("""
            UPDATE outbox_events
            SET    status = 'publishing'
            WHERE  id IN (
                SELECT id FROM outbox_events
                WHERE  status = 'pending'
                ORDER  BY created_at
                LIMIT  :limit
                FOR UPDATE SKIP LOCKED
            )
            RETURNING id, tenant_id, event_type, aggregate_type, aggregate_id,
                      payload, topic, retry_count, max_retries, created_at
        """),
        {"limit": batch_size},
    )
    session.commit()

    rows = result.fetchall()
    events = []
    for r in rows:
        payload = r.payload if isinstance(r.payload, dict) else json.loads(r.payload or "{}")
        events.append({
            "id": r.id,
            "tenant_id": r.tenant_id,
            "event_type": r.event_type,
            "aggregate_type": r.aggregate_type,
            "aggregate_id": r.aggregate_id,
            "payload": payload,
            "topic": r.topic,
            "retry_count": r.retry_count,
            "max_retries": r.max_retries,
            "created_at": r.created_at,
        })
    return events


def _mark_published(session: Session, event_ids: list) -> None:
    now = datetime.now(timezone.utc)
    session.execute(
        text("""
            UPDATE outbox_events
            SET    status = 'published', published_at = :now
            WHERE  id = ANY(:ids)
        """),
        {"ids": event_ids, "now": now},
    )
    session.commit()


def _mark_failed(session: Session, event: dict) -> None:
    new_retry = event["retry_count"] + 1
    max_retries = event.get("max_retries", 5)
    new_status = "dead_letter" if new_retry >= max_retries else "pending"

    session.execute(
        text("""
            UPDATE outbox_events
            SET    status = :st, retry_count = :rc
            WHERE  id = :eid
        """),
        {"st": new_status, "rc": new_retry, "eid": event["id"]},
    )
    session.commit()
    if new_status == "dead_letter":
        logger.warning(f"Publisher: event {event['id']} → dead_letter after {new_retry} retries")
