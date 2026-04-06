# Event Service

Centralised event pipeline for ZeroQue's multi-tenant SaaS platform. Every database write produces an event that flows through a reliable, exactly-once delivery pipeline into downstream services (graph projection, vector embeddings, notifications, etc.).

## How It Works

```
  API Layer                  PostgreSQL               Publisher              Azure Service Bus           Consumers
 ┌──────────┐  emit()  ┌──────────────────┐   timer  ┌──────────┐  publish  ┌──────────────┐  trigger  ┌──────────┐
 │ FastAPI  │────────▶│ business tables  │◀────────│ Outbox   │─────────▶│ domain-events│─────────▶│ Graph    │──▶ Neo4j
 │ routes   │         │ + outbox_events  │         │ Publisher│          │   topic      │          │ Vector   │──▶ pgvector
 └──────────┘         └──────────────────┘         └──────────┘          │              │          │ Notif    │──▶ Email
                              │                         ▲                └──────────────┘          └──────────┘
                              │  same transaction       │ every 5s
                              └─────────────────────────┘
```

### Step by step

1. **API writes data + event atomically** — `emit(db, tenant_id, "site.created", {...})` inserts into `outbox_events` inside the same Postgres transaction as the business record. If the transaction rolls back, the event is never created.

2. **Publisher polls the outbox** — An Azure Function (timer trigger, every 5 seconds) claims a batch of `pending` events using `SELECT ... FOR UPDATE SKIP LOCKED`, publishes them to Azure Service Bus, and marks them `published`.

3. **Service Bus fans out** — The `domain-events` topic has multiple subscriptions (graph-consumer, vector-consumer, notification-consumer). Each subscription gets a copy of every message independently.

4. **Consumers process events** — Azure Functions (Service Bus triggers) fire per-subscription, deserialise the event, and call the appropriate downstream service API.

## Files

| File | Purpose |
|------|---------|
| `emitter.py` | `emit()` function — called by API routes to write an event to the outbox. Uses raw SQL, zero ORM dependency. |
| `publisher.py` | Core publish logic — claim batch, send to transport, mark published. Handles retries and dead-lettering. |
| `transport.py` | Pluggable message transport. `LocalTransport` (asyncio queues for dev/test) and `ServiceBusTransport` (Azure SB for production). |

## Usage

### Emitting an event (from any API service)

```python
from event_service import emit

# Inside a route handler — db is the SQLAlchemy session
site = Site(name="London HQ", ...)
db.add(site)

emit(db, tenant_id, "site.created", {
    "site_id": str(site.id),
    "name": site.name,
    "tenant_id": str(tenant_id),
})

db.commit()  # business data + event committed atomically
```

### Event lifecycle

| Status | Meaning |
|--------|---------|
| `pending` | Just created, waiting for publisher to pick up |
| `publishing` | Claimed by publisher, being sent to Service Bus |
| `published` | Successfully sent to Service Bus, `published_at` timestamp set |
| `dead_letter` | Failed 5 times, moved to dead letter for manual review |

### Retry logic

If the publisher fails to send an event to Service Bus:
- The event goes back to `pending` with `retry_count` incremented
- After 5 failures (`max_retries`), it moves to `dead_letter`
- Dead-lettered events can be replayed manually

### Transport abstraction

The transport layer is swappable:

```python
# Local development (no Azure needed)
from event_service.transport import LocalTransport
transport = LocalTransport()

# Production (Azure Service Bus)
from event_service.transport import ServiceBusTransport
transport = ServiceBusTransport(connection_string)
```

Both implement the same interface, so publisher and consumer code works identically in both modes.

## Outbox Table Schema

```sql
CREATE TABLE outbox_events (
    id              UUID PRIMARY KEY,
    tenant_id       UUID NOT NULL,
    event_type      VARCHAR(200) NOT NULL,    -- e.g. "site.created"
    aggregate_type  VARCHAR(100),             -- e.g. "site" (auto-derived)
    aggregate_id    UUID,                     -- e.g. the site's UUID (auto-derived)
    payload         JSONB NOT NULL,           -- full event data
    status          VARCHAR(20) NOT NULL,     -- pending / publishing / published / dead_letter
    topic           VARCHAR(100),             -- Service Bus topic name
    retry_count     INTEGER DEFAULT 0,
    max_retries     INTEGER DEFAULT 5,
    error_message   TEXT,
    created_at      TIMESTAMPTZ NOT NULL,
    published_at    TIMESTAMPTZ,
    processed_at    TIMESTAMPTZ
);
```

## Testing

```bash
# Run the 54-test E2E suite (no Azure needed)
python -m tests.test_pipeline

# Run the local pipeline runner (publisher + consumers in one process)
python -m scripts.run_local
```
