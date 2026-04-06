"""
End-to-End Event Pipeline Test
===============================
Tests the full flow:  emit → outbox → publisher → transport → consumer → graph

Runs everything in-process using LocalTransport (no Azure needed).

Usage:
    cd project-zer-new
    python -m tests.test_pipeline
"""
import asyncio
import json
import logging
import sys
import os
import uuid
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.db import engine, SessionFactory, get_session
from shared.models import Base, OutboxEvent
from shared.config import SERVICE_BUS_TOPIC
from event_service.emitter import emit
from event_service.publisher import publish_pending_events
from event_service.transport import LocalTransport

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("test_pipeline")

pass_count = 0
fail_count = 0
errors = []

def check(name, condition, detail=None):
    global pass_count, fail_count
    if condition:
        pass_count += 1
        print(f"  PASS  {name}")
    else:
        fail_count += 1
        msg = f"  FAIL  {name}"
        if detail:
            msg += f" — {detail}"
        print(msg)
        errors.append(name)
    return condition


TENANT_ID = str(uuid.uuid4())
processed_events = []


def mock_graph_handler(event: dict):
    processed_events.append(event)


async def run_tests():
    global processed_events

    print("\n" + "=" * 64)
    print("  EVENT PIPELINE — END-TO-END TEST")
    print("=" * 64)

    # ── Phase 0: Setup ────────────────────────────────────────────
    print("\n--- Phase 0: Database Setup ---")
    try:
        Base.metadata.create_all(engine)
        print("  Tables created")
    except Exception as e:
        print(f"  Table creation note: {e}")

    # Clean up old test data
    with get_session() as db:
        from sqlalchemy import text
        db.execute(text("DELETE FROM outbox_events WHERE tenant_id = :tid"), {"tid": uuid.UUID(TENANT_ID)})
    print("  Cleanup done")

    # ── Phase 1: Emit Events ──────────────────────────────────────
    print("\n--- Phase 1: Emit Events (write to outbox) ---")

    events_to_emit = [
        ("tenant.signup", {"tenant_id": TENANT_ID, "tenant_name": "Test Corp", "email": "admin@test.com"}),
        ("site.created", {"site_id": str(uuid.uuid4()), "name": "London HQ", "site_type": "headquarters", "tenant_id": TENANT_ID}),
        ("store.created", {"store_id": str(uuid.uuid4()), "name": "Oxford St", "store_type": "retail", "site_id": str(uuid.uuid4()), "tenant_id": TENANT_ID}),
        ("user.created", {"user_id": str(uuid.uuid4()), "email": "john@test.com", "first_name": "John", "last_name": "Doe", "tenant_id": TENANT_ID}),
        ("vendor.created", {"vendor_id": str(uuid.uuid4()), "name": "Acme Supplies", "tenant_id": TENANT_ID}),
        ("cost_centre.created", {"cost_centre_id": str(uuid.uuid4()), "name": "Marketing", "tenant_id": TENANT_ID}),
        ("org_unit.created", {"org_unit_id": str(uuid.uuid4()), "name": "Engineering", "type": "department", "tenant_id": TENANT_ID}),
        ("role.created", {"role_id": str(uuid.uuid4()), "code": "admin", "description": "Administrator"}),
        ("product.created", {"product_id": str(uuid.uuid4()), "name": "Blue Widget", "sku": "BW-001", "tenant_id": TENANT_ID}),
    ]

    event_ids = []
    with get_session() as db:
        for event_type, payload in events_to_emit:
            eid = emit(db, TENANT_ID, event_type, payload)
            event_ids.append(eid)
            check(f"Emitted {event_type}", eid is not None)

    # Verify they're in the outbox
    with get_session() as db:
        from sqlalchemy import text
        result = db.execute(
            text("SELECT COUNT(*) FROM outbox_events WHERE tenant_id = :tid AND status = 'pending'"),
            {"tid": uuid.UUID(TENANT_ID)},
        )
        count = result.scalar()
        check(f"Outbox has {len(events_to_emit)} pending events", count == len(events_to_emit), f"got {count}")

    # ── Phase 2: Publisher ────────────────────────────────────────
    print("\n--- Phase 2: Publisher (outbox → transport) ---")

    transport = LocalTransport()
    transport._get_queue(SERVICE_BUS_TOPIC, "graph-consumer")
    transport._get_queue(SERVICE_BUS_TOPIC, "vector-consumer")

    session = SessionFactory()
    try:
        published_count = await publish_pending_events(session, transport, 100)
        check("Publisher processed batch", published_count == len(events_to_emit), f"published={published_count}")
    finally:
        session.close()

    # Verify all events are now 'published'
    with get_session() as db:
        from sqlalchemy import text
        result = db.execute(
            text("SELECT COUNT(*) FROM outbox_events WHERE tenant_id = :tid AND status = 'published'"),
            {"tid": uuid.UUID(TENANT_ID)},
        )
        pub_count = result.scalar()
        check("All events marked 'published'", pub_count == len(events_to_emit), f"got {pub_count}")

        result = db.execute(
            text("SELECT COUNT(*) FROM outbox_events WHERE tenant_id = :tid AND status = 'pending'"),
            {"tid": uuid.UUID(TENANT_ID)},
        )
        pending = result.scalar()
        check("Zero pending events remaining", pending == 0, f"got {pending}")

    # ── Phase 3: Consumer ─────────────────────────────────────────
    print("\n--- Phase 3: Consumer (transport → handlers) ---")

    processed_events.clear()

    # Drain the graph-consumer queue
    graph_queue = transport._get_queue(SERVICE_BUS_TOPIC, "graph-consumer")
    while not graph_queue.empty():
        event = await graph_queue.get()
        mock_graph_handler(event)

    check(
        f"Graph consumer received {len(events_to_emit)} events",
        len(processed_events) == len(events_to_emit),
        f"got {len(processed_events)}",
    )

    # Verify event types received
    received_types = {e["event_type"] for e in processed_events}
    for event_type, _ in events_to_emit:
        check(f"Consumer got {event_type}", event_type in received_types)

    # Verify event payloads are intact
    for event in processed_events:
        check(
            f"Payload intact for {event['event_type']}",
            event.get("tenant_id") == TENANT_ID and event.get("payload") is not None,
        )

    # Check vector consumer only got product event
    vector_queue = transport._get_queue(SERVICE_BUS_TOPIC, "vector-consumer")
    vector_events = []
    while not vector_queue.empty():
        vector_events.append(await vector_queue.get())
    check(
        "Vector consumer received all events (fan-out)",
        len(vector_events) == len(events_to_emit),
        f"got {len(vector_events)}",
    )

    # ── Phase 4: Retry / Dead Letter ─────────────────────────────
    print("\n--- Phase 4: Publisher Retry Behavior ---")

    # Emit an event, simulate publish failure by using a broken transport
    with get_session() as db:
        eid = emit(db, TENANT_ID, "test.retry_event", {"test": True})

    class FailingTransport(LocalTransport):
        async def publish(self, topic, events):
            raise ConnectionError("Simulated Service Bus outage")

    bad_transport = FailingTransport()
    session = SessionFactory()
    try:
        await publish_pending_events(session, bad_transport, 10)
    finally:
        session.close()

    # Verify retry_count incremented but still pending (not dead_letter yet)
    with get_session() as db:
        from sqlalchemy import text
        result = db.execute(
            text("SELECT status, retry_count FROM outbox_events WHERE id = :eid"),
            {"eid": uuid.UUID(eid)},
        )
        row = result.fetchone()
        check("Failed event back to pending", row.status == "pending", f"status={row.status}")
        check("Retry count incremented", row.retry_count == 1, f"retry_count={row.retry_count}")

    # Exhaust retries → dead_letter
    for _ in range(5):
        session = SessionFactory()
        try:
            await publish_pending_events(session, bad_transport, 10)
        finally:
            session.close()

    with get_session() as db:
        result = db.execute(
            text("SELECT status, retry_count FROM outbox_events WHERE id = :eid"),
            {"eid": uuid.UUID(eid)},
        )
        row = result.fetchone()
        check("Exhausted retries → dead_letter", row.status == "dead_letter", f"status={row.status}")

    # ── Phase 5: Event Metadata ───────────────────────────────────
    print("\n--- Phase 5: Event Metadata & Audit ---")

    with get_session() as db:
        from sqlalchemy import text

        result = db.execute(
            text("SELECT event_type, aggregate_type, published_at FROM outbox_events WHERE tenant_id = :tid AND status = 'published' ORDER BY created_at"),
            {"tid": uuid.UUID(TENANT_ID)},
        )
        rows = result.fetchall()

        for row in rows:
            check(
                f"Aggregate type derived: {row.event_type} → {row.aggregate_type}",
                row.aggregate_type is not None,
            )
            check(
                f"Published timestamp set: {row.event_type}",
                row.published_at is not None,
            )

    # ── Results ───────────────────────────────────────────────────
    print("\n" + "=" * 64)
    print(f"  RESULTS: {pass_count} passed, {fail_count} failed out of {pass_count + fail_count}")
    if errors:
        print(f"  FAILED: {errors}")
    print("=" * 64 + "\n")

    return fail_count == 0


if __name__ == "__main__":
    success = asyncio.run(run_tests())
    sys.exit(0 if success else 1)
