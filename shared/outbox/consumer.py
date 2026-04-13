"""
shared/outbox/consumer.py
--------------------------
Base outbox consumer that graph_service and vector_service use.

Polls ``outbox_event_delivery`` for rows assigned to a specific consumer name,
claims them atomically with ``FOR UPDATE SKIP LOCKED``, dispatches to
registered handlers, and manages retry / dead-letter logic.

Each service instantiates its own ``OutboxConsumer`` with its consumer name
and database URL, then registers handlers and calls ``start_polling()``.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger("outbox_consumer")


class OutboxConsumer:
    """Outbox poller for a named consumer."""

    def __init__(
        self,
        consumer_name: str,
        database_url: str,
        poll_interval: int = 3,
        batch_size: int = 25,
        max_retries: int = 5,
    ):
        self.consumer_name = consumer_name
        self.poll_interval = poll_interval
        self.batch_size = batch_size
        self.max_retries = max_retries

        self._handlers: Dict[str, Callable] = {}
        self._engine = create_engine(database_url, pool_pre_ping=True)
        self._Session = sessionmaker(bind=self._engine)

    def register_handler(self, event_type_prefix: str, handler: Callable):
        """Register a handler for events whose type starts with *event_type_prefix*.

        Example:
            consumer.register_handler("product", product_handler.handle)
            consumer.register_handler("tenant", tenant_handler.handle)
        """
        self._handlers[event_type_prefix] = handler
        logger.info(f"[{self.consumer_name}] Registered handler for '{event_type_prefix}.*'")

    async def start_polling(self):
        """Run the poll loop forever (call from asyncio.create_task)."""
        logger.info(
            f"[{self.consumer_name}] Polling started "
            f"(interval={self.poll_interval}s, batch={self.batch_size})"
        )
        while True:
            try:
                session = self._Session()
                try:
                    batch = self._claim_batch(session)
                    for event in batch:
                        await self._dispatch(session, event)
                finally:
                    session.close()
            except Exception as exc:
                logger.error(f"[{self.consumer_name}] Poll error: {exc}", exc_info=True)
            await asyncio.sleep(self.poll_interval)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _claim_batch(self, session) -> list:
        """Atomically claim a batch of pending deliveries."""
        rows = session.execute(
            text("""
                UPDATE outbox_event_delivery
                SET    status = 'processing'
                WHERE  id IN (
                    SELECT d.id
                    FROM   outbox_event_delivery d
                    WHERE  d.consumer = :consumer
                    AND    d.status = 'pending'
                    ORDER  BY d.created_at
                    LIMIT  :batch
                    FOR UPDATE SKIP LOCKED
                )
                RETURNING id, event_id
            """),
            {"consumer": self.consumer_name, "batch": self.batch_size},
        )
        delivery_rows = rows.fetchall()
        if not delivery_rows:
            return []

        events = []
        for delivery_id, event_id in delivery_rows:
            row = session.execute(
                text("""
                    SELECT id, tenant_id, aggregate_type, aggregate_id,
                           event_type, payload
                    FROM   outbox_events
                    WHERE  id = :eid
                """),
                {"eid": event_id},
            ).fetchone()
            if row:
                events.append({
                    "delivery_id": delivery_id,
                    "event_id": row[0],
                    "tenant_id": str(row[1]) if row[1] else None,
                    "aggregate_type": row[2],
                    "aggregate_id": str(row[3]) if row[3] else None,
                    "event_type": row[4],
                    "payload": row[5] if isinstance(row[5], dict) else {},
                })
        session.commit()
        return events

    async def _dispatch(self, session, event: dict):
        """Route to registered handler and update delivery status."""
        event_type = event.get("event_type", "")
        prefix = event_type.split(".")[0] if "." in event_type else event_type
        handler = self._handlers.get(prefix)

        delivery_id = event["delivery_id"]

        if handler is None:
            # No handler — mark as completed (benign skip)
            self._mark_completed(session, delivery_id)
            return

        try:
            result = handler(event)
            # Support both sync and async handlers
            if asyncio.iscoroutine(result):
                await result
            self._mark_completed(session, delivery_id)
            logger.info(
                f"[{self.consumer_name}] Processed {event_type} "
                f"(event={event['event_id']})"
            )
        except Exception as exc:
            logger.error(
                f"[{self.consumer_name}] Handler error for {event_type}: {exc}",
                exc_info=True,
            )
            self._mark_failed(session, event, str(exc))

    def _mark_completed(self, session, delivery_id):
        session.execute(
            text("""
                UPDATE outbox_event_delivery
                SET    status = 'completed', processed_at = :now
                WHERE  id = :did
            """),
            {"did": delivery_id, "now": datetime.now(timezone.utc)},
        )
        session.commit()

    def _mark_failed(self, session, event: dict, error_msg: str):
        delivery_id = event["delivery_id"]
        result = session.execute(
            text("""
                UPDATE outbox_event_delivery
                SET    retry_count = retry_count + 1,
                       error_message = :err,
                       status = CASE
                           WHEN retry_count + 1 >= :max_r THEN 'dead_letter'
                           ELSE 'pending'
                       END,
                       processed_at = CASE
                           WHEN retry_count + 1 >= :max_r THEN :now
                           ELSE processed_at
                       END
                WHERE  id = :did
                RETURNING status
            """),
            {
                "did": delivery_id,
                "err": error_msg[:500],
                "max_r": self.max_retries,
                "now": datetime.now(timezone.utc),
            },
        )
        new_status = result.fetchone()
        session.commit()
        if new_status and new_status[0] == "dead_letter":
            logger.warning(
                f"[{self.consumer_name}] Dead-lettered delivery {delivery_id} "
                f"for event {event['event_id']}"
            )
