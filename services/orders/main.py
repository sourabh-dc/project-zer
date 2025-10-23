# services/orders/main.py - ZeroQue Orders Service V2
# Production-ready orders service with Celery, RabbitMQ, and saga patterns

import os
import uuid
import time
import json
from datetime import datetime, timezone, timedelta
from typing import Dict, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import Response
from sqlalchemy import text
from celery import Celery
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
import redis
import pika
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential
import pybreaker

from .utils.orders_logger import logger
from core.config import get_settings
from .repositories.db_config import SessionLocal
from .utils.metrics import *
from .schemas import OrderRequest, OrderUpdateRequest
from .repositories.order_saga import OrderSaga
from .repositories.db_config import get_db
from .utils.user_auth import get_user_context
from .repositories.database_ops import audit

# =============================================================================
# CONFIGURATION
# =============================================================================

SERVICE_NAME = "orders"
SERVICE_VERSION = "4.1.0"

# Configuration
DATABASE_URL = get_settings().DATABASE_URL
REDIS_URL = get_settings().REDIS_URL
RABBITMQ_URL = get_settings().RABBITMQ_URL
ENVIRONMENT = get_settings().ENVIRONMENT

# Redis setup
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# Celery setup
celery_app = Celery(
    SERVICE_NAME,
    broker=RABBITMQ_URL,
    backend=REDIS_URL,
    include=[f'{SERVICE_NAME}.tasks']
)

# Load Celery configuration
try:
    celery_app.config_from_object('celeryconfig')
except ImportError:
    pass

# Circuit breaker for external service calls
service_breaker = pybreaker.CircuitBreaker(fail_max=5, reset_timeout=60)

# External service URLs
PAYMENTS_BASE = os.getenv("PAYMENTS_BASE", "http://localhost:8005")
BILLING_BASE = os.getenv("BILLING_BASE", "http://localhost:8002")
PRICING_BASE = os.getenv("PRICING_BASE", "http://localhost:8007")
INVENTORY_BASE = os.getenv("INVENTORY_BASE", "http://localhost:8008")

# Circuit breaker for external services
circuit_breaker = pybreaker.CircuitBreaker(fail_max=5, reset_timeout=60)

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def call_external_service(url: str, method: str = "GET", data: Dict = None):
    """Call external service with retry"""
    with httpx.Client() as client:
        if method == "GET":
            response = client.get(url)
        elif method == "POST":
            response = client.post(url, json=data)
        elif method == "PUT":
            response = client.put(url, json=data)
        else:
            raise ValueError(f"Unsupported method: {method}")
        
        response.raise_for_status()
        return response.json()

# =============================================================================
# CELERY TASKS
# =============================================================================

@celery_app.task(bind=True, max_retries=3, name='orders.publish_outbox_events')
def publish_outbox_events(self):
    """Publish outbox events to RabbitMQ"""
    try:
        with SessionLocal() as db:
            events = db.execute(text("SELECT * FROM outbox_events WHERE status = 'pending' LIMIT 100")).fetchall()
            
            for event in events:
                try:
                    # Publish to RabbitMQ
                    connection = pika.BlockingConnection(pika.URLParameters(RABBITMQ_URL))
                    channel = connection.channel()
                    
                    channel.basic_publish(
                        exchange='orders_events',
                        routing_key=event.event_type.lower(),
                        body=event.event_data
                    )
                    
                    # Update status
                    db.execute(
                        text("UPDATE outbox_events SET status = 'published', published_at = NOW() WHERE event_id = :id"),
                        {"id": event.event_id}
                    )
                    db.commit()
                    
                    connection.close()
                    
                except Exception as e:
                    logger.error("Failed to publish event", event_id=event.event_id, error=str(e))
                    # Increment retry count
                    db.execute(
                        text("UPDATE outbox_events SET retry_count = retry_count + 1 WHERE event_id = :id"),
                        {"id": event.event_id}
                    )
                    db.commit()
                    
    except Exception as e:
        logger.error("Outbox publishing failed", error=str(e))
        raise self.retry(exc=e, countdown=60)

@celery_app.task(bind=True, max_retries=3)
def process_order_fulfillment(self, order_id: str):
    """Process order fulfillment"""
    try:
        with SessionLocal() as db:
            order = db.execute(text("SELECT * FROM orders_v2 WHERE order_id = :id"), {"id": order_id}).fetchone()
            if not order:
                raise ValueError("Order not found")
            
            # Call inventory service
            inventory_response = call_external_service(f"{INVENTORY_BASE}/inventory/reserve", "POST", {
                "order_id": order_id,
                "items": []  # TODO: Get order items
            })
            
            # Update order status
            db.execute(
                text("UPDATE orders_v2 SET fulfillment_status = 'fulfilled' WHERE order_id = :id"),
                {"id": order_id}
            )
            db.commit()
            
            logger.info("Order fulfillment processed", order_id=order_id)
            
    except Exception as e:
        logger.error("Order fulfillment failed", order_id=order_id, error=str(e))
        raise self.retry(exc=e, countdown=60)

@celery_app.task(bind=True, max_retries=3)
def cleanup_old_orders(self):
    """Cleanup old orders"""
    try:
        with SessionLocal() as db:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=90)
            result = db.execute(
                text("DELETE FROM orders_v2 WHERE created_at < :cutoff"),
                {"cutoff": cutoff_date}
            )
            db.commit()
            logger.info("Cleaned up old orders", count=result.rowcount)
    except Exception as e:
        logger.error("Order cleanup failed", error=str(e))
        raise self.retry(exc=e, countdown=60)

# =============================================================================
# FASTAPI APPLICATION
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan"""
    # Startup
    logger.info("Starting orders service", version=SERVICE_VERSION)
    yield
    # Shutdown
    logger.info("Shutting down orders service")

app = FastAPI(
    title="ZeroQue Orders Service",
    description="Production-ready orders service with Celery and RabbitMQ",
    version=SERVICE_VERSION,
    lifespan=lifespan
)

# Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*"])

# =============================================================================
# API ENDPOINTS
# =============================================================================

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": SERVICE_NAME,
        "version": SERVICE_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint"""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.post("/orders")
async def create_order(
    req: OrderRequest,
    db: SessionLocal = Depends(get_db),
    uctx: Dict = Depends(get_user_context)
):
    """Create a new order"""
    start = time.time()
    try:
        orders_requests_total.labels(endpoint="create_order", status="start").inc()
        
        order_id = uuid.uuid4()
        tenant_id = uctx["tenant_id"]
        
        saga = OrderSaga(db)
        result = await saga.exec(order_id, tenant_id, req, uctx)
        
        orders_requests_total.labels(endpoint="create_order", status="ok").inc()
        orders_request_duration.labels(endpoint="create_order").observe(time.time() - start)
        
        return result
        
    except ValueError as e:
        orders_requests_total.labels(endpoint="create_order", status="fail").inc()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        orders_requests_total.labels(endpoint="create_order", status="fail").inc()
        logger.error("Order creation failed", error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/orders")
async def list_orders(
    tenant_id: str = Query(...),
    limit: int = Query(100, le=1000),
    offset: int = Query(0, ge=0),
    db: SessionLocal = Depends(get_db)
):
    """List orders for a tenant"""
    try:
        orders = db.execute(
            text("SELECT * FROM orders_v2 WHERE tenant_id = :tenant_id ORDER BY created_at DESC LIMIT :limit OFFSET :offset"),
            {"tenant_id": tenant_id, "limit": limit, "offset": offset}
        ).fetchall()
        
        return [dict(order._mapping) for order in orders]
        
    except Exception as e:
        logger.error("Failed to list orders", error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/orders/{order_id}")
async def get_order(
    order_id: str,
    db: SessionLocal = Depends(get_db)
):
    """Get order by ID"""
    try:
        order = db.execute(
            text("SELECT * FROM orders_v2 WHERE order_id = :id"),
            {"id": order_id}
        ).fetchone()
        
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
        
        return dict(order._mapping)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get order", order_id=order_id, error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")

@app.put("/orders/{order_id}")
async def update_order(
    order_id: str,
    req: OrderUpdateRequest,
    db: SessionLocal = Depends(get_db),
    uctx: Dict = Depends(get_user_context)
):
    """Update order"""
    try:
        # Build update query
        updates = []
        params = {"id": order_id}
        
        if req.order_status:
            updates.append("order_status = :order_status")
            params["order_status"] = req.order_status
        
        if req.payment_status:
            updates.append("payment_status = :payment_status")
            params["payment_status"] = req.payment_status
        
        if req.fulfillment_status:
            updates.append("fulfillment_status = :fulfillment_status")
            params["fulfillment_status"] = req.fulfillment_status
        
        if req.metadata:
            updates.append("metadata = :metadata")
            params["metadata"] = json.dumps(req.metadata)
        
        if not updates:
            raise HTTPException(status_code=400, detail="No updates provided")
        
        updates.append("updated_at = NOW()")
        
        db.execute(
            text(f"UPDATE orders_v2 SET {', '.join(updates)} WHERE order_id = :id"),
            params
        )
        db.commit()
        
        # Audit log
        audit(db, uctx["tenant_id"], uctx["user_id"], "UPDATE", "order", order_id, req.dict())
        
        return {"order_id": order_id, "updated": True}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to update order", order_id=order_id, error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")

@app.delete("/orders/{order_id}")
async def cancel_order(
    order_id: str,
    db: SessionLocal = Depends(get_db),
    uctx: Dict = Depends(get_user_context)
):
    """Cancel order"""
    try:
        db.execute(
            text("UPDATE orders_v2 SET order_status = 'cancelled', updated_at = NOW() WHERE order_id = :id"),
            {"id": order_id}
        )
        db.commit()
        
        # Audit log
        audit(db, uctx["tenant_id"], uctx["user_id"], "CANCEL", "order", order_id, {})
        
        return {"order_id": order_id, "cancelled": True}
        
    except Exception as e:
        logger.error("Failed to cancel order", order_id=order_id, error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")

# =============================================================================
# CELERY TASKS
# =============================================================================

@celery_app.task(bind=True, max_retries=3)
def process_order_fulfillment(self, order_id: str, fulfillment_data: Dict[str, Any]):
    """Process order fulfillment asynchronously"""
    try:
        with SessionLocal() as db:
            # Get order
            order = db.execute(text("""
                SELECT * FROM orders_v2 WHERE order_id = :id
            """), {"id": order_id}).fetchone()
            
            if not order:
                raise ValueError(f"Order {order_id} not found")
            
            # Process fulfillment logic here
            logger.info(f"Processing order fulfillment for order {order_id}")
            
            # Update status
            db.execute(text("""
                UPDATE orders_v2 
                SET fulfillment_status = 'fulfilled', updated_at = NOW()
                WHERE order_id = :id
            """), {"id": order_id})
            
            db.commit()
            
            # Update metrics
            orders_operations_total.labels(operation="fulfillment", status="success").inc()
            
    except Exception as e:
        logger.error(f"Failed to process order fulfillment for order {order_id}: {e}")
        orders_operations_total.labels(operation="fulfillment", status="failed").inc()
        raise self.retry(exc=e, countdown=60)

@celery_app.task(bind=True, max_retries=3)
def process_order_cancellation(self, order_id: str, cancellation_reason: str):
    """Process order cancellation asynchronously"""
    try:
        with SessionLocal() as db:
            # Get order
            order = db.execute(text("""
                SELECT * FROM orders_v2 WHERE order_id = :id
            """), {"id": order_id}).fetchone()
            
            if not order:
                raise ValueError(f"Order {order_id} not found")
            
            # Process cancellation logic here
            logger.info(f"Processing order cancellation for order {order_id}, reason: {cancellation_reason}")
            
            # Update status
            db.execute(text("""
                UPDATE orders_v2 
                SET order_status = 'cancelled', updated_at = NOW()
                WHERE order_id = :id
            """), {"id": order_id})
            
            db.commit()
            
            # Update metrics
            orders_operations_total.labels(operation="cancellation", status="success").inc()
            
    except Exception as e:
        logger.error(f"Failed to process order cancellation for order {order_id}: {e}")
        orders_operations_total.labels(operation="cancellation", status="failed").inc()
        raise self.retry(exc=e, countdown=60)

@celery_app.task(bind=True, max_retries=3)
def cleanup_old_orders(self):
    """Clean up old orders"""
    try:
        with SessionLocal() as db:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=365)
            
            # Clean up old completed orders
            order_result = db.execute(text("""
                DELETE FROM orders_v2 
                WHERE created_at < :cutoff_date AND order_status IN ('completed', 'cancelled')
            """), {"cutoff_date": cutoff_date})
            
            db.commit()
            
            logger.info(f"Cleaned up {order_result.rowcount} old orders")
            
    except Exception as e:
        logger.error(f"Failed to cleanup old orders: {e}")
        raise self.retry(exc=e, countdown=300)

# =============================================================================
# MAIN EXECUTION
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("SERVICE_PORT", os.getenv("PORT", "8224")))
    logger.info(f"Starting {SERVICE_NAME} service v{SERVICE_VERSION}")
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=ENVIRONMENT == "development"
    )