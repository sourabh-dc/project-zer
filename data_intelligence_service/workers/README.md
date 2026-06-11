# workers/

Standalone background process — runs the outbox consumer independently of the web server.

---

## Why a separate worker?

The FastAPI app starts an outbox polling loop via `asyncio.create_task()` on startup.
This works fine in single-process deployments.

However, in Kubernetes (multiple replicas of the web server), you don't want every replica
polling the outbox simultaneously — that would process the same events multiple times,
despite the `FOR UPDATE SKIP LOCKED` guard.

The worker is a **separate Deployment** with a single replica:
- Web server replicas handle HTTP requests (scale freely)
- Worker replica handles outbox events (always exactly 1)

---

## `consumer_standalone.py`

Starts the same `outbox_consumer.start_polling()` loop from `core/outbox_consumer.py`
as a standalone Python process. No HTTP server — just the event loop.

```bash
python -m data_intelligence_service.workers.consumer_standalone
```

Or via Docker:
```bash
docker run zeroque/data-intelligence-worker
```
