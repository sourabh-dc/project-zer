#!/usr/bin/env python3
"""
ZeroQue Notifications Service V4.1
Enhanced notifications with multi-provider support, event-driven architecture, and v4.1 compliance
"""
import os
from typing import Dict, Optional, Any
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Depends, Body, Query, Path
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session
from prometheus_client import generate_latest
import redis
import pybreaker

from core.config import get_settings
from services.notifications.utils.user_auth import get_user_context
from .schemas import SendNotificationRequest, ReplayRequest, NotificationHistoryResponse, RailRequest, \
    NotificationResponse
from .utils.notifications_logger import logger
from .repositories.db_config import SessionLocal, get_db
from .services.notifications_services import handle_entry_granted, handle_user_created, \
    handle_order_completed, handle_invoice_posted, send_notification, replay_notification, get_notification_history, \
    configure_notification_provider, replay_legacy

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
async def send_notification_route(
    request: SendNotificationRequest = Body(...),
    db: Session = Depends(get_db),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """Send notification via configured provider"""
    return await send_notification(request, db, user_context)

@app.post("/notifications/v4/replay")
async def replay_notification_route(
    request: ReplayRequest = Body(...),
    db: Session = Depends(get_db),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """Replay failed notification"""
    return await replay_notification(request, db, user_context)

@app.get("/notifications/v4/history", response_model=NotificationHistoryResponse)
async def get_notification_history_route(
    tenant_id: str = Query(...),
    status: Optional[str] = Query(None),
    channel: Optional[str] = Query(None),
    limit: int = Query(50, le=100),
    page: int = Query(1, ge=1),
    db: Session = Depends(get_db),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """Get notification delivery history"""
    return await get_notification_history(tenant_id, status, channel, limit, page, db, user_context)

# ---- Admin Endpoints ----
@app.post("/admin/rails/notification")
async def configure_notification_provider_route(
    request: RailRequest = Body(...),
    db: Session = Depends(get_db),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """Configure notification provider"""
    return await configure_notification_provider(request, db, user_context)

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
async def replay_legacy_route(
    delivery_id: str = Path(...),
    db: Session = Depends(get_db),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """Legacy replay endpoint - deprecated"""
    return await replay_legacy(delivery_id, db, user_context)

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