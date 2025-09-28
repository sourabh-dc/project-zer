# services/events/main.py
"""
ZeroQue Event Service - Centralized event processing and management
"""
import os
import logging
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
import asyncio

from zeroque_common.events.bus import (
    Event, EventType, event_bus, publish_event, 
    create_order_event, create_inventory_event, 
    create_user_event, create_budget_event
)
from zeroque_common.events.celery_app import celery_app
from zeroque_common.db.session import SessionLocal, init_db, check_db
from sqlalchemy import text

# Service configuration
SERVICE_NAME = "events"
app = FastAPI(title="ZeroQue Event Service", version="0.1.0")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Logging
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(SERVICE_NAME)

# Event schemas
class EventRequest(BaseModel):
    event_type: str
    tenant_id: str
    site_id: Optional[str] = None
    store_id: Optional[str] = None
    user_id: Optional[str] = None
    data: Dict[str, Any] = {}
    metadata: Dict[str, Any] = {}

class EventResponse(BaseModel):
    event_id: str
    status: str
    timestamp: datetime

# Startup/shutdown events
@app.on_event("startup")
def on_startup():
    init_db()
    log.info("Event service started", extra={"service": SERVICE_NAME, "version": "0.1.0"})

@app.get("/health")
def health():
    return {"status": "ok", "service": SERVICE_NAME}

@app.get("/readiness")
def readiness():
    return {"service": SERVICE_NAME, "db": check_db(), "redis": True}

# Event publishing endpoints
@app.post("/events/publish", response_model=EventResponse)
async def publish_event_endpoint(event_request: EventRequest, background_tasks: BackgroundTasks):
    """Publish an event to the event bus"""
    try:
        # Validate event type
        try:
            event_type = EventType(event_request.event_type)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid event type: {event_request.event_type}")
        
        # Create event
        event = Event(
            event_type=event_type,
            tenant_id=event_request.tenant_id,
            site_id=event_request.site_id,
            store_id=event_request.store_id,
            user_id=event_request.user_id,
            data=event_request.data,
            metadata=event_request.metadata
        )
        
        # Publish event
        message_id = await publish_event(
            event_type=event_type,
            tenant_id=event_request.tenant_id,
            site_id=event_request.site_id,
            store_id=event_request.store_id,
            user_id=event_request.user_id,
            data=event_request.data,
            metadata=event_request.metadata
        )
        
        # Trigger async processing based on event type
        background_tasks.add_task(trigger_event_processing, event_type, event_request.dict())
        
        return EventResponse(
            event_id=message_id,
            status="published",
            timestamp=event.timestamp
        )
        
    except Exception as e:
        log.error("Failed to publish event: %s", str(e))
        raise HTTPException(status_code=500, detail=str(e))

async def trigger_event_processing(event_type: EventType, event_data: Dict[str, Any]):
    """Trigger appropriate Celery tasks based on event type"""
    try:
        if event_type in [EventType.ORDER_CREATED, EventType.ORDER_UPDATED, EventType.ORDER_COMPLETED]:
            celery_app.send_task(
                "zeroque_common.events.tasks.process_order_event",
                args=[event_data],
                queue="orders"
            )
        elif event_type in [EventType.INVENTORY_UPDATED, EventType.INVENTORY_LOW_STOCK, EventType.INVENTORY_OUT_OF_STOCK]:
            celery_app.send_task(
                "zeroque_common.events.tasks.process_inventory_event",
                args=[event_data],
                queue="inventory"
            )
        elif event_type in [EventType.BUDGET_EXCEEDED, EventType.BUDGET_WARNING, EventType.APPROVAL_REQUESTED]:
            celery_app.send_task(
                "zeroque_common.events.tasks.process_budget_event",
                args=[event_data],
                queue="budget"
            )
        
        log.info("Event processing triggered for %s", event_type.value)
        
    except Exception as e:
        log.error("Failed to trigger event processing: %s", str(e))

# Convenience endpoints for common events
@app.post("/events/orders/{order_id}")
async def publish_order_event(
    order_id: int,
    event_type: str,
    tenant_id: str,
    site_id: Optional[str] = None,
    store_id: Optional[str] = None,
    user_id: Optional[str] = None,
    data: Dict[str, Any] = {}
):
    """Publish an order-related event"""
    try:
        event_type_enum = EventType(event_type)
        event = create_order_event(event_type_enum, tenant_id, order_id, **data)
        
        message_id = await publish_event(
            event_type=event_type_enum,
            tenant_id=tenant_id,
            site_id=site_id,
            store_id=store_id,
            user_id=user_id,
            data={"order_id": order_id, **data}
        )
        
        return {"event_id": message_id, "status": "published"}
        
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid event type: {event_type}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/events/inventory/{sku}")
async def publish_inventory_event(
    sku: str,
    event_type: str,
    tenant_id: str,
    store_id: str,
    data: Dict[str, Any] = {}
):
    """Publish an inventory-related event"""
    try:
        event_type_enum = EventType(event_type)
        message_id = await publish_event(
            event_type=event_type_enum,
            tenant_id=tenant_id,
            store_id=store_id,
            data={"sku": sku, **data}
        )
        
        return {"event_id": message_id, "status": "published"}
        
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid event type: {event_type}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Event history and monitoring
@app.get("/events/history")
def get_event_history(
    tenant_id: str,
    event_type: Optional[str] = None,
    limit: int = 100
):
    """Get event history for a tenant"""
    try:
        # For now, return a simple response since we're using Redis Streams
        # In a production system, you'd want to persist events to a database
        return {
            "events": [],
            "count": 0,
            "message": "Event history stored in Redis Streams. Use Redis CLI to query: XRANGE zeroque:events - +"
        }
        
    except Exception as e:
        log.error("Failed to get event history: %s", str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/events/stats")
def get_event_stats(tenant_id: str):
    """Get event statistics for a tenant"""
    try:
        # For now, return basic stats
        # In production, you'd query Redis Streams or a database
        return {
            "tenant_id": tenant_id,
            "message": "Event statistics available via Redis Streams",
            "redis_stream": "zeroque:events"
        }
        
    except Exception as e:
        log.error("Failed to get event stats: %s", str(e))
        raise HTTPException(status_code=500, detail=str(e))

# Enhanced monitoring endpoints
@app.get("/events/metrics")
def get_event_metrics():
    """Get comprehensive event metrics"""
    try:
        import redis
        redis_client = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:4000/0"))
        
        # Get Redis Stream info
        stream_info = redis_client.xinfo_stream("zeroque:events")
        
        # Get Celery worker stats
        inspect = celery_app.control.inspect()
        stats = inspect.stats()
        active = inspect.active()
        scheduled = inspect.scheduled()
        reserved = inspect.reserved()
        
        return {
            "redis_stream": {
                "length": stream_info.get("length", 0),
                "first_entry": stream_info.get("first-entry"),
                "last_entry": stream_info.get("last-entry"),
                "groups": stream_info.get("groups", 0)
            },
            "celery_workers": {
                "count": len(stats) if stats else 0,
                "workers": list(stats.keys()) if stats else [],
                "active_tasks": sum(len(tasks) for tasks in active.values()) if active else 0,
                "scheduled_tasks": sum(len(tasks) for tasks in scheduled.values()) if scheduled else 0,
                "reserved_tasks": sum(len(tasks) for tasks in reserved.values()) if reserved else 0
            },
            "queues": {
                "default": redis_client.llen("celery"),
                "webhooks": redis_client.llen("celery:webhooks"),
                "notifications": redis_client.llen("celery:notifications"),
                "pricing": redis_client.llen("celery:pricing"),
                "catalog": redis_client.llen("celery:catalog"),
                "provisioning": redis_client.llen("celery:provisioning"),
                "identity": redis_client.llen("celery:identity"),
                "orders": redis_client.llen("celery:orders"),
                "inventory": redis_client.llen("celery:inventory"),
                "budget": redis_client.llen("celery:budget"),
                "analytics": redis_client.llen("celery:analytics"),
                "security": redis_client.llen("celery:security"),
                "cache": redis_client.llen("celery:cache"),
                "search": redis_client.llen("celery:search"),
                "user_management": redis_client.llen("celery:user_management")
            }
        }
        
    except Exception as e:
        log.error("Failed to get event metrics: %s", str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/events/health/detailed")
def get_detailed_health():
    """Get detailed health status of event system components"""
    try:
        import redis
        redis_client = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:4000/0"))
        
        # Check Redis connection
        redis_status = "healthy"
        try:
            redis_client.ping()
        except Exception:
            redis_status = "unhealthy"
        
        # Check Celery workers
        inspect = celery_app.control.inspect()
        stats = inspect.stats()
        worker_status = "healthy" if stats and len(stats) > 0 else "unhealthy"
        
        # Check event stream
        stream_status = "healthy"
        try:
            redis_client.xinfo_stream("zeroque:events")
        except Exception:
            stream_status = "unhealthy"
        
        overall_status = "healthy" if all([
            redis_status == "healthy",
            worker_status == "healthy", 
            stream_status == "healthy"
        ]) else "unhealthy"
        
        return {
            "overall_status": overall_status,
            "components": {
                "redis": redis_status,
                "celery_workers": worker_status,
                "event_stream": stream_status,
                "event_service": "healthy"
            },
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
    except Exception as e:
        log.error("Failed to get detailed health: %s", str(e))
        return {
            "overall_status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

@app.get("/events/queues/status")
def get_queue_status():
    """Get detailed status of all Celery queues"""
    try:
        import redis
        redis_client = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:4000/0"))
        
        queues = [
            "celery", "celery:webhooks", "celery:notifications", "celery:pricing",
            "celery:catalog", "celery:provisioning", "celery:identity", "celery:orders",
            "celery:inventory", "celery:budget", "celery:analytics", "celery:security",
            "celery:cache", "celery:search", "celery:user_management"
        ]
        
        queue_status = {}
        for queue in queues:
            try:
                length = redis_client.llen(queue)
                queue_status[queue] = {
                    "length": length,
                    "status": "active" if length > 0 else "idle"
                }
            except Exception as e:
                queue_status[queue] = {
                    "length": 0,
                    "status": "error",
                    "error": str(e)
                }
        
        return {
            "queues": queue_status,
            "total_pending": sum(q["length"] for q in queue_status.values()),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
    except Exception as e:
        log.error("Failed to get queue status: %s", str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/events/stream/info")
def get_stream_info():
    """Get detailed Redis Stream information"""
    try:
        import redis
        redis_client = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:4000/0"))
        
        # Get stream info
        stream_info = redis_client.xinfo_stream("zeroque:events")
        
        # Get consumer groups
        groups = redis_client.xinfo_groups("zeroque:events")
        
        # Get recent events (last 10)
        recent_events = redis_client.xrevrange("zeroque:events", count=10)
        
        return {
            "stream_info": stream_info,
            "consumer_groups": groups,
            "recent_events": [
                {
                    "id": event_id,
                    "fields": dict(zip(fields[::2], fields[1::2]))
                }
                for event_id, fields in recent_events
            ],
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
    except Exception as e:
        log.error("Failed to get stream info: %s", str(e))
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8213))
    uvicorn.run(app, host="0.0.0.0", port=port)
