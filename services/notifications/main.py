#!/usr/bin/env python3
"""
ZeroQue Notifications Service V4.1
Enhanced notifications with multi-provider support, event-driven architecture, and v4.1 compliance
"""

import os
import json
from datetime import datetime, timezone
from typing import Dict, Optional, Any
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Depends, Body, Query, Path, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session
from prometheus_client import generate_latest
import redis
import pybreaker

from core.config import get_settings
from services.notifications.utils.user_auth import get_user_context, check_permission
from .schemas import SendNotificationRequest, ReplayRequest, NotificationHistoryResponse, RailRequest, \
    NotificationResponse
from .utils.notifications_logger import logger
from .repositories.db_config import SessionLocal, get_db, set_rls_context
from .utils.metrics import notification_operations_total, notification_failures_total
from .repositories.send_notification_saga import SendNotificationSaga
from .repositories.reply_saga import ReplaySaga
from .services.notifications_services import handle_entry_granted, handle_user_created, \
    handle_order_completed, handle_invoice_posted

# Service configuration
SERVICE_NAME = "notifications"
SERVICE_VERSION = "4.1.0"
ENVIRONMENT = get_settings().ENVIRONMENT
DATABASE_URL = get_settings().DATABASE_URL
REDIS_URL = get_settings().REDIS_URL
RABBITMQ_URL = get_settings().RABBITMQ_URL

# Redis setup
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# Circuit breaker for external service calls
service_breaker = pybreaker.CircuitBreaker(fail_max=5, reset_timeout=60)

# ---- Application Setup ----
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    logger.info(f"Starting {SERVICE_NAME} service", version=SERVICE_VERSION, environment=ENVIRONMENT)
    
    # Create tables if they don't exist
    # Base.metadata.create_all(bind=engine)
    
    # Start background tasks
    # Note: In production, these would be separate Celery workers
    
    yield
    
    logger.info(f"Shutting down {SERVICE_NAME} service")

app = FastAPI(
    title=f"ZeroQue {SERVICE_NAME.title()} Service V4.1",
    description=f"Enhanced {SERVICE_NAME} management with multi-provider support and event-driven architecture",
    version=SERVICE_VERSION
    # lifespan=lifespan  # Temporarily disabled for debugging
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- Health Endpoints ----
@app.get("/health")
async def health():
    """Health check endpoint"""
    return {
        "status": "ok",
        "service": SERVICE_NAME,
        "version": SERVICE_VERSION,
        "environment": ENVIRONMENT
    }

@app.get("/readiness")
async def readiness():
    """Readiness check endpoint"""
    try:
        # Check database connectivity
        with SessionLocal() as db:
            db.execute(text("SELECT 1")).fetchone()
        
        return {
            "service": SERVICE_NAME,
            "status": "ready",
            "database": "connected"
        }
    except Exception as e:
        logger.error("Readiness check failed", error=str(e))
        raise HTTPException(status_code=503, detail="Service not ready")

@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint"""
    return generate_latest()

# ---- Notification Endpoints ----
@app.post("/notifications/v4/send", response_model=NotificationResponse)
async def send_notification(
    request: SendNotificationRequest = Body(...),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: Session = Depends(get_db),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """Send notification via configured provider"""
    if not check_permission("notifications.send", user_context):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    # Set RLS context
    set_rls_context(db, request.tenant_id, request.user_id)
    
    try:
        saga = SendNotificationSaga(db)
        result = await saga.execute(request, user_context)
        
        # Update metrics
        if notification_operations_total:
            notification_operations_total.labels(
                channel=request.channel,
                provider=result["provider"],
                status="success"
            ).inc()
        
        return NotificationResponse(
            delivery_id=result["delivery_id"],
            status=result["status"],
            provider=result["provider"],
            channel=request.channel,
            created_at=datetime.now(timezone.utc)
        )
        
    except Exception as e:
        # Update failure metrics
        if notification_failures_total:
            notification_failures_total.labels(
                channel=request.channel,
                provider=request.provider or "unknown",
                error_type=type(e).__name__
            ).inc()
        
        logger.error("Notification send failed", error=str(e), request=request.dict())
        raise HTTPException(status_code=500, detail=f"Notification send failed: {str(e)}")

@app.post("/notifications/v4/replay")
async def replay_notification(
    request: ReplayRequest = Body(...),
    db: Session = Depends(get_db),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """Replay failed notification"""
    if not check_permission("notifications.send", user_context):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    try:
        saga = ReplaySaga(db)
        result = await saga.execute(request, user_context)
        
        return result
        
    except Exception as e:
        logger.error("Notification replay failed", error=str(e), request=request.dict())
        raise HTTPException(status_code=500, detail=f"Notification replay failed: {str(e)}")

@app.get("/notifications/v4/history", response_model=NotificationHistoryResponse)
async def get_notification_history(
    tenant_id: str = Query(...),
    status: Optional[str] = Query(None),
    channel: Optional[str] = Query(None),
    limit: int = Query(50, le=100),
    page: int = Query(1, ge=1),
    db: Session = Depends(get_db),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """Get notification delivery history"""
    if not check_permission("notifications.view", user_context):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    # Set RLS context
    set_rls_context(db, tenant_id)
    
    try:
        offset = (page - 1) * limit
        
        # Build query
        query = """
            SELECT id, tenant_id, user_id, channel, provider, status, template_id,
                   payload, error, retry_count, created_at, updated_at
            FROM notification_deliveries_new
            WHERE tenant_id = :tenant_id
        """
        params = {"tenant_id": tenant_id}
        
        if status:
            query += " AND status = :status"
            params["status"] = status
        
        if channel:
            query += " AND channel = :channel"
            params["channel"] = channel
        
        query += " ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
        params.update({"limit": limit, "offset": offset})
        
        # Get deliveries
        deliveries = db.execute(text(query), params).fetchall()
        
        # Get total count
        count_query = """
            SELECT COUNT(*) FROM notification_deliveries_new
            WHERE tenant_id = :tenant_id
        """
        count_params = {"tenant_id": tenant_id}
        
        if status:
            count_query += " AND status = :status"
            count_params["status"] = status
        
        if channel:
            count_query += " AND channel = :channel"
            count_params["channel"] = channel
        
        total_count = db.execute(text(count_query), count_params).scalar()
        
        # Convert to dict format
        delivery_list = []
        for delivery in deliveries:
            delivery_dict = dict(delivery._mapping)
            delivery_dict["payload"] = json.loads(delivery_dict["payload"]) if delivery_dict["payload"] else {}
            delivery_dict["error"] = json.loads(delivery_dict["error"]) if delivery_dict["error"] else None
            delivery_list.append(delivery_dict)
        
        return NotificationHistoryResponse(
            deliveries=delivery_list,
            count=total_count,
            page=page,
            limit=limit
        )
        
    except Exception as e:
        logger.error("Failed to get notification history", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to get notification history")

# ---- Admin Endpoints ----
@app.post("/admin/rails/notification")
async def configure_notification_provider(
    request: RailRequest = Body(...),
    db: Session = Depends(get_db),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """Configure notification provider"""
    if not check_permission("notifications.admin", user_context):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    try:
        tenant_id = user_context.get("tenant_id")
        
        # Check if provider already exists
        existing = db.execute(text("""
            SELECT id FROM zeroque_rails 
            WHERE tenant_id = :tenant_id AND type = :type AND name = :name
        """), {
            "tenant_id": tenant_id,
            "type": request.type,
            "name": request.name
        }).first()
        
        if existing:
            # Update existing provider
            db.execute(text("""
                UPDATE zeroque_rails 
                SET config = :config, active = :active, updated_at = NOW()
                WHERE id = :id
            """), {
                "id": existing[0],
                "config": json.dumps(request.config),
                "active": request.active
            })
        else:
            # Create new provider
            db.execute(text("""
                INSERT INTO zeroque_rails (tenant_id, type, name, config, active, created_at)
                VALUES (:tenant_id, :type, :name, :config, :active, NOW())
            """), {
                "tenant_id": tenant_id,
                "type": request.type,
                "name": request.name,
                "config": json.dumps(request.config),
                "active": request.active
            })
        
        db.commit()
        
        return {"message": f"Provider {request.name} configured successfully", "active": request.active}
        
    except Exception as e:
        logger.error("Failed to configure provider", error=str(e), request=request.dict())
        raise HTTPException(status_code=500, detail="Failed to configure provider")

# ---- Event Integration Endpoints ----
@app.post("/notifications/v4/integration/entry-granted")
async def handle_entry_granted_webhook(
    event_data: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db)
):
    """Handle ENTRY_GRANTED event from Entry service"""
    try:
        await handle_entry_granted(event_data, db)
        return {"status": "processed", "event": "ENTRY_GRANTED"}
    except Exception as e:
        logger.error("Failed to process ENTRY_GRANTED event", error=str(e))
        raise HTTPException(status_code=500, detail="Event processing failed")

@app.post("/notifications/v4/integration/user-created")
async def handle_user_created_webhook(
    event_data: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db)
):
    """Handle USER_CREATED event from Identity service"""
    try:
        await handle_user_created(event_data, db)
        return {"status": "processed", "event": "USER_CREATED"}
    except Exception as e:
        logger.error("Failed to process USER_CREATED event", error=str(e))
        raise HTTPException(status_code=500, detail="Event processing failed")

@app.post("/notifications/v4/integration/order-completed")
async def handle_order_completed_webhook(
    event_data: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db)
):
    """Handle ORDER_COMPLETED event from Orders service"""
    try:
        await handle_order_completed(event_data, db)
        return {"status": "processed", "event": "ORDER_COMPLETED"}
    except Exception as e:
        logger.error("Failed to process ORDER_COMPLETED event", error=str(e))
        raise HTTPException(status_code=500, detail="Event processing failed")

@app.post("/notifications/v4/integration/invoice-posted")
async def handle_invoice_posted_webhook(
    event_data: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db)
):
    """Handle INVOICE_POSTED event from Billing service"""
    try:
        await handle_invoice_posted(event_data, db)
        return {"status": "processed", "event": "INVOICE_POSTED"}
    except Exception as e:
        logger.error("Failed to process INVOICE_POSTED event", error=str(e))
        raise HTTPException(status_code=500, detail="Event processing failed")

# ---- Legacy Endpoint (Deprecated) ----
@app.post("/notifications/replay/{delivery_id}")
async def replay_legacy(
    delivery_id: str = Path(...),
    db: Session = Depends(get_db),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """Legacy replay endpoint - deprecated"""
    logger.warning("Legacy replay endpoint used", delivery_id=delivery_id)
    
    request = ReplayRequest(delivery_id=delivery_id)
    saga = ReplaySaga(db)
    result = await saga.execute(request, user_context)
    
    return {"replayed": delivery_id, "status": result["status"]}



# =============================================================================
# MAIN EXECUTION
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("SERVICE_PORT", os.getenv("PORT", "8222")))
    logger.info(f"Starting {SERVICE_NAME} service v{SERVICE_VERSION}")
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=ENVIRONMENT == "development"
    )