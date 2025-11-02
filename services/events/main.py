# services/events/main.py - ZeroQue Events Service V4.1
import os
import uuid
import httpx
from datetime import datetime
from typing import Optional, Dict, Any
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from sqlalchemy import text, select
from prometheus_client import generate_latest

from core.config import get_settings
from .utils.events_logger import logger
from .utils.metrics import event_publish_total, event_consume_total, event_retry_total, consumer_failures
from .repositories.db_config import AsyncSessionLocal, set_rls_context
from .utils.user_auth import check_permission, check_rate_limit, get_user_context
from .models import EventNew, EventSubscription, EventMetric
from .repositories.db_config import init_db, check_db
from .core.celery_config import celery_app
from .schemas import EventPublishRequest, EventRetryRequest, EventHistoryResponse, EventStatsResponse, EventSubscriptionRequest
from .repositories.event_publish_saga import EventPublishSaga
from .repositories.event_retry_saga import EventRetrySaga
# =============================================================================
# CONFIGURATION & LOGGING
# =============================================================================

SERVICE_NAME = "events"
SERVICE_VERSION = "4.1.0"

# Configuration
DATABASE_URL = get_settings().DATABASE_URL
REDIS_URL = get_settings().REDIS_URL
RABBITMQ_URL = get_settings().RABBITMQ_URL
ENVIRONMENT = get_settings().ENVIRONMENT
ALLOW_DEMO = get_settings().ALLOW_DEMO
JWT_SECRET_KEY = get_settings().JWT_SECRET_KEY
JWT_ALGORITHM = get_settings().JWT_ALGORITHM
EVENT_RETENTION_DAYS = int(os.getenv("EVENT_RETENTION_DAYS", "30"))
MAX_EVENTS_PER_REQUEST = int(os.getenv("MAX_EVENTS_PER_REQUEST", "100"))

# RabbitMQ configuration
try:
    import pika
    RABBITMQ_AVAILABLE = True
except ImportError:
    RABBITMQ_AVAILABLE = False
    logger.warning("pika not available, RabbitMQ integration disabled")

# Event consumption workers (if needed for this service)
# The Events service primarily publishes events, so event consumption may not be needed

# =============================================================================
# FASTAPI APPLICATION
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    logger.info("Starting Events Service V2", version="2.0.0", environment="production")
    
    # Initialize database
    await init_db()
    
    # Check database connectivity
    if not await check_db():
        logger.error("Database connectivity check failed")
        raise Exception("Database not available")
    
    logger.info("Events Service V2 started successfully")
    yield
    
    logger.info("Shutting down Events Service V2")

app = FastAPI(
    title="ZeroQue Events Service V2",
    description="Centralized event processing and management service",
    version="2.0.0",
    lifespan=lifespan
)

# Production Middleware - Restrict CORS origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8501",  # Streamlit apps
        "http://localhost:8502",
        "http://localhost:8503",
        "http://localhost:8510",
        "https://*.zeroque.com"
    ] if ENVIRONMENT == "development" else ["https://*.zeroque.com", "https://zeroque.com"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

app.add_middleware(GZipMiddleware, minimum_size=1000)

if ENVIRONMENT == "production":
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*.zeroque.com", "zeroque.com"])
else:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*"])

# =============================================================================
# HEALTH & METRICS ENDPOINTS
# =============================================================================

@app.get("/events/v4/health")
async def health():
    """Health check endpoint"""
    return {"status": "healthy", "service": "events", "version": "2.0.0"}

@app.get("/events/v4/readiness")
async def readiness():
    """Readiness check endpoint"""
    db_healthy = await check_db()
    return {
        "status": "ready" if db_healthy else "not_ready",
        "database": "connected" if db_healthy else "disconnected",
        "service": "events"
    }

@app.get("/events/v4/metrics")
async def metrics():
    """Prometheus metrics endpoint"""
    return generate_latest()

@app.get("/events/v4/metrics/queues")
async def get_queue_metrics(
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """Get queue metrics and health"""
    try:
        # Check permissions
        if not check_permission("events.admin", user_context):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        
        metrics_data = {
            "queue_metrics": {
                "total_events_published": event_publish_total._value.sum() if event_publish_total else 0,
                "total_events_consumed": event_consume_total._value.sum() if event_consume_total else 0,
                "total_event_retries": event_retry_total._value.sum() if event_retry_total else 0,
                "consumer_failures": consumer_failures._value.sum() if consumer_failures else 0
            },
            "queue_health": {
                "rabbitmq_available": RABBITMQ_AVAILABLE,
                "celery_available": celery_app is not None,
                "retention_days": EVENT_RETENTION_DAYS
            },
            "timestamp": datetime.utcnow().isoformat()
        }
        
        return metrics_data
        
    except Exception as e:
        logger.error(f"Failed to get queue metrics: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# =============================================================================
# CORE EVENT ENDPOINTS
# =============================================================================

@app.post("/events/v4/publish")
async def publish_event(
    payload: EventPublishRequest,
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """Publish an event to the event bus"""
    try:
        # Check rate limit
        if not await check_rate_limit(user_context["user_id"]):
            raise HTTPException(status_code=429, detail="Rate limit exceeded")

        # Check permissions
        if not check_permission("events.publish", user_context):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        
        async with AsyncSessionLocal() as db:
            await set_rls_context(db, payload.tenant_id, user_context["user_id"])
            
            # Execute saga
            saga = EventPublishSaga(db, user_context)
            result = await saga.execute(payload)
            
            # Update metrics
            if event_publish_total is not None:
                event_publish_total.labels(event_type=payload.event_type, status="success").inc()
            
            return result
        
    except Exception as e:
        logger.error(f"Failed to publish event: {str(e)}")
        if event_publish_total is not None:
            event_publish_total.labels(event_type=payload.event_type, status="failed").inc()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/events/v4/history")
async def get_event_history(
    tenant_id: str = Query(...),
    event_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    limit: int = Query(50, le=MAX_EVENTS_PER_REQUEST),
    offset: int = Query(0, ge=0),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """Get event history with filtering"""
    try:
        # Check permissions
        if not check_permission("events.view", user_context):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        
        async with AsyncSessionLocal() as db:
            await set_rls_context(db, tenant_id, user_context["user_id"])
            
            # Build query
            query = select(EventNew).where(
                EventNew.tenant_id == uuid.UUID(tenant_id)
            )
            
            if event_type:
                query = query.where(EventNew.event_type == event_type)
            
            if status:
                query = query.where(EventNew.status == status)
            
            if start_date:
                query = query.where(EventNew.created_at >= start_date)
            
            if end_date:
                query = query.where(EventNew.created_at <= end_date)
            
            # Get total count
            count_query = select(text("COUNT(*)")).select_from(query.subquery())
            total_result = await db.execute(count_query)
            total_count = total_result.scalar()
            
            # Get events with pagination
            query = query.order_by(EventNew.created_at.desc()).limit(limit).offset(offset)
            result = await db.execute(query)
            events = result.scalars().all()
            
            # Format response
            event_list = []
            for event in events:
                event_list.append({
                    "id": str(event.id),
                    "event_type": event.event_type,
                    "event_data": event.event_data,
                    "status": event.status,
                    "retry_count": event.retry_count,
                    "created_at": event.created_at.isoformat(),
                    "updated_at": event.updated_at.isoformat() if event.updated_at else None,
                    "published_at": event.published_at.isoformat() if event.published_at else None
                })
            
            return EventHistoryResponse(
                events=event_list,
                total_count=total_count,
                has_more=(offset + len(events)) < total_count
            )
            
    except Exception as e:
        logger.error(f"Failed to get event history: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/events/v4/retry")
async def retry_events(
    payload: EventRetryRequest,
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """Retry pending events"""
    try:
        # Check admin permissions
        if not check_permission("events.admin", user_context):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        
        async with AsyncSessionLocal() as db:
            await set_rls_context(db, payload.tenant_id, user_context["user_id"])
            
            # Execute retry saga
            saga = EventRetrySaga(db, user_context)
            result = await saga.execute(payload)
            
            return result
            
    except Exception as e:
        logger.error(f"Failed to retry events: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/events/v4/stats")
async def get_event_stats(
    tenant_id: str = Query(...),
    event_type: Optional[str] = Query(None),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """Get event statistics"""
    try:
        # Check permissions
        if not check_permission("events.view", user_context):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        
        async with AsyncSessionLocal() as db:
            await set_rls_context(db, tenant_id, user_context["user_id"])
            
            # Build base query
            base_query = select(EventMetric).where(
                EventMetric.tenant_id == uuid.UUID(tenant_id)
            )
            
            if event_type:
                base_query = base_query.where(EventMetric.event_type == event_type)
            
            if start_date:
                base_query = base_query.where(EventMetric.timestamp >= start_date)
            
            if end_date:
                base_query = base_query.where(EventMetric.timestamp <= end_date)
            
            # Get statistics
            result = await db.execute(base_query)
            metrics = result.scalars().all()
            
            # Aggregate stats
            stats = {
                "total_events": len(metrics),
                "by_event_type": {},
                "by_status": {},
                "avg_duration": 0,
                "total_duration": 0
            }
            
            duration_sum = 0
            duration_count = 0
            
            for metric in metrics:
                # Count by event type
                if metric.event_type not in stats["by_event_type"]:
                    stats["by_event_type"][metric.event_type] = 0
                stats["by_event_type"][metric.event_type] += 1
                
                # Count by status
                status = metric.metric_metadata.get("status", "unknown") if metric.metric_metadata else "unknown"
                if status not in stats["by_status"]:
                    stats["by_status"][status] = 0
                stats["by_status"][status] += 1
                
                # Calculate duration stats
                if metric.metric_type == "publish_duration":
                    duration_sum += metric.metric_value
                    duration_count += 1
            
            if duration_count > 0:
                stats["avg_duration"] = duration_sum / duration_count
                stats["total_duration"] = duration_sum
            
            return EventStatsResponse(
                stats=stats,
                period=f"{(start_date or datetime.min).isoformat()} to {(end_date or datetime.utcnow()).isoformat()}"
            )
        
    except Exception as e:
        logger.error(f"Failed to get event stats: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# =============================================================================
# ADMIN ENDPOINTS
# =============================================================================

@app.post("/events/v4/admin/subscriptions")
async def create_event_subscription(
    payload: EventSubscriptionRequest,
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """Create event subscription"""
    try:
        # Check admin permissions
        if not check_permission("events.admin", user_context):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        
        async with AsyncSessionLocal() as db:
            await set_rls_context(db, payload.tenant_id, user_context["user_id"])
            
            # Create subscription
            subscription = EventSubscription(
                tenant_id=uuid.UUID(payload.tenant_id),
                service_name=payload.service_name,
                event_type=payload.event_type,
                queue_name=payload.queue_name,
                active=True
            )
            
            db.add(subscription)
            await db.commit()
            await db.refresh(subscription)
            
            return {
                "subscription_id": str(subscription.id),
                "status": "created",
                "message": "Event subscription created successfully"
            }
            
    except Exception as e:
        logger.error(f"Failed to create event subscription: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/events/v4/admin/subscriptions")
async def list_event_subscriptions(
    tenant_id: str = Query(...),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """List event subscriptions"""
    try:
        # Check admin permissions
        if not check_permission("events.admin", user_context):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        
        async with AsyncSessionLocal() as db:
            await set_rls_context(db, tenant_id, user_context["user_id"])
            
            query = select(EventSubscription).where(
                EventSubscription.tenant_id == uuid.UUID(tenant_id)
            ).order_by(EventSubscription.created_at.desc())
            
            result = await db.execute(query)
            subscriptions = result.scalars().all()
            
            subscription_list = []
            for sub in subscriptions:
                subscription_list.append({
                    "id": str(sub.id),
                    "service_name": sub.service_name,
                    "event_type": sub.event_type,
                    "queue_name": sub.queue_name,
                    "active": sub.active,
                    "created_at": sub.created_at.isoformat()
                })
            
            return {"subscriptions": subscription_list}
            
    except Exception as e:
        logger.error(f"Failed to list event subscriptions: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# =============================================================================
# INTEGRATION ENDPOINTS
# =============================================================================

@app.post("/events/v4/integration/entry/entry-granted")
async def handle_entry_granted_event(
    event_data: Dict[str, Any],
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """Handle ENTRY_GRANTED event from Entry service"""
    try:
        tenant_id = event_data.get("tenant_id")
        if not tenant_id:
            raise HTTPException(status_code=400, detail="Missing tenant_id")
        
        # Publish to event bus
        payload = EventPublishRequest(
            tenant_id=tenant_id,
            event_type="ENTRY_GRANTED",
            event_data=event_data
        )
        
        saga = EventPublishSaga(None, user_context)
        result = await saga.execute(payload)
        
        return {"status": "processed", "event_id": result.event_id}
        
    except Exception as e:
        logger.error(f"Failed to handle ENTRY_GRANTED event: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/events/v4/integration/identity/user-created")
async def handle_user_created_event(
    event_data: Dict[str, Any],
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """Handle USER_CREATED event from Identity service"""
    try:
        tenant_id = event_data.get("tenant_id")
        if not tenant_id:
            raise HTTPException(status_code=400, detail="Missing tenant_id")
        
        # Publish to event bus
        payload = EventPublishRequest(
            tenant_id=tenant_id,
            event_type="USER_CREATED",
            event_data=event_data
        )
        
        saga = EventPublishSaga(None, user_context)
        result = await saga.execute(payload)
        
        return {"status": "processed", "event_id": result.event_id}
        
    except Exception as e:
        logger.error(f"Failed to handle USER_CREATED event: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/events/v4/integration/orders/order-completed")
async def handle_order_completed_event(
    event_data: Dict[str, Any],
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """Handle ORDER_COMPLETED event from Orders service"""
    try:
        tenant_id = event_data.get("tenant_id")
        if not tenant_id:
            raise HTTPException(status_code=400, detail="Missing tenant_id")
        
        # Publish to event bus
        payload = EventPublishRequest(
            tenant_id=tenant_id,
            event_type="ORDER_COMPLETED",
            event_data=event_data
        )
        
        saga = EventPublishSaga(None, user_context)
        result = await saga.execute(payload)
        
        return {"status": "processed", "event_id": result.event_id}
        
    except Exception as e:
        logger.error(f"Failed to handle ORDER_COMPLETED event: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/events/v4/integration/approvals/approval-resolved")
async def handle_approval_resolved_event(
    event_data: Dict[str, Any],
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """Handle APPROVAL_RESOLVED event from Approvals service"""
    try:
        tenant_id = event_data.get("tenant_id")
        if not tenant_id:
            raise HTTPException(status_code=400, detail="Missing tenant_id")
        
        # Publish to event bus
        payload = EventPublishRequest(
            tenant_id=tenant_id,
            event_type="APPROVAL_RESOLVED",
            event_data=event_data
        )
        
        saga = EventPublishSaga(None, user_context)
        result = await saga.execute(payload)
        
        return {"status": "processed", "event_id": result.event_id}
        
    except Exception as e:
        logger.error(f"Failed to handle APPROVAL_RESOLVED event: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/events/v4/integration/billing/invoice-posted")
async def handle_invoice_posted_event(
    event_data: Dict[str, Any],
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """Handle INVOICE_POSTED event from Billing service"""
    try:
        tenant_id = event_data.get("tenant_id")
        if not tenant_id:
            raise HTTPException(status_code=400, detail="Missing tenant_id")
        
        # Publish to event bus
        payload = EventPublishRequest(
            tenant_id=tenant_id,
            event_type="INVOICE_POSTED",
            event_data=event_data
        )
        
        saga = EventPublishSaga(None, user_context)
        result = await saga.execute(payload)
        
        return {"status": "processed", "event_id": result.event_id}
        
    except Exception as e:
        logger.error(f"Failed to handle INVOICE_POSTED event: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/events/v4/integration/status")
async def get_integration_status(
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """Get integration status for all connected services"""
    try:
        # Check permissions
        if not check_permission("events.admin", user_context):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        
        # Test connections to other services
        service_status = {}
        
        services = [
            ("entry", "http://localhost:8085"),
            ("identity", "http://localhost:8086"),
            ("orders", "http://localhost:8080"),
            ("approvals", "http://localhost:8081"),
            ("billing", "http://localhost:8083")
        ]
        
        async with httpx.AsyncClient(timeout=5.0) as client:
            for service_name, service_url in services:
                try:
                    response = await client.get(f"{service_url}/{service_name}/v4/health")
                    service_status[service_name] = {
                        "status": "connected" if response.status_code == 200 else "error",
                        "response_time": response.elapsed.total_seconds() if hasattr(response, 'elapsed') else 0,
                        "url": service_url
                    }
                except Exception as e:
                    service_status[service_name] = {
                        "status": "disconnected",
                        "error": str(e),
                        "url": service_url
                    }
        
        return {
            "integration_status": service_status,
            "events_service": "operational",
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Failed to get integration status: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# =============================================================================
# LEGACY ENDPOINTS (DEPRECATED)
# =============================================================================

@app.post("/publish")
async def publish_event_legacy(
    payload: EventPublishRequest,
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """Legacy publish endpoint - redirects to v4"""
    logger.warning("Using deprecated /publish endpoint, redirecting to /events/v4/publish")
    return await publish_event(payload, user_context)

@app.get("/history")
async def get_event_history_legacy(
    tenant_id: str = Query(...),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """Legacy history endpoint - redirects to v4"""
    logger.warning("Using deprecated /history endpoint, redirecting to /events/v4/history")
    return await get_event_history(tenant_id, None, None, None, None, 50, 0, user_context)

@app.get("/stats")
async def get_event_stats_legacy(
    tenant_id: str = Query(...),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """Legacy stats endpoint - redirects to v4"""
    logger.warning("Using deprecated /stats endpoint, redirecting to /events/v4/stats")
    return await get_event_stats(tenant_id, None, None, None, user_context)

#=============================================================================
# APPLICATION STARTUP
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("SERVICE_PORT", os.getenv("PORT", "8012")))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)