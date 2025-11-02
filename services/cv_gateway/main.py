# CV Gateway Service - Enhanced V4.1 Architecture
# Multi-provider CV order processing with sagas, events, and RLS
import os
import json
from datetime import timezone
from contextlib import asynccontextmanager
from fastapi import FastAPI, Body, HTTPException, Query, Path, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import text
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
import pika
import pybreaker

from core.config import get_settings
from services.cv_gateway.repositories.cv_order_saga import CvOrderSaga
from services.cv_gateway.repositories.database_ops import audit_log, log_audit
from services.cv_gateway.utils.user_auth import get_user_context
from .utils.cv_gateway_logger import logger
from .schemas import *
from .repositories.db_config import get_engine, set_rls_context, check_db, get_db_with_rls, get_db
from .utils.metrics import cv_gateway_requests_total, cv_gateway_request_duration, cv_order_processing_total
# =============================================================================
# CONFIGURATION & LOGGING
# =============================================================================

SERVICE_NAME = "cv_gateway"
SERVICE_VERSION = "4.1.0"

# Configuration
DATABASE_URL = get_settings().DATABASE_URL
REDIS_URL = get_settings().REDIS_URL
RABBITMQ_URL = get_settings().RABBITMQ_URL
ENVIRONMENT = get_settings().ENVIRONMENT
ALLOW_DEMO = get_settings().ALLOW_DEMO
JWT_SECRET_KEY = get_settings().JWT_SECRET_KEY
JWT_ALGORITHM = get_settings().JWT_ALGORITHM
RATE_LIMIT_REQUESTS_PER_MINUTE = 60
MAX_REQUEST_SIZE_BYTES = 10 * 1024 * 1024  # 10MB

# Circuit breaker for external service calls
service_breaker = pybreaker.CircuitBreaker(fail_max=5, reset_timeout=60)

def add_api_call_meter(app):
    return app

def add_idempotency_middleware(app, routes=None):
    return app

def create_trade_invoice_if_applicable(db, tenant_id: str, order_id: int, total_minor: int, currency: str, site_id: str, store_id: str):
    # Placeholder hook for billing integration
    return None

# RabbitMQ Publishing
def publish_to_rabbitmq(event_type: str, event_data: Dict[str, Any], tenant_id: str) -> bool:
    """Publish event directly to RabbitMQ"""
    try:
        connection = pika.BlockingConnection(pika.URLParameters(RABBITMQ_URL))
        channel = connection.channel()
        channel.exchange_declare(exchange='zeroque_events', exchange_type='topic', durable=True)
        message = json.dumps({
            "event_type": event_type,
            "tenant_id": tenant_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": event_data
        })
        channel.basic_publish(
            exchange='zeroque_events',
            routing_key=event_type,
            body=message,
            properties=pika.BasicProperties(delivery_mode=2)
        )
        connection.close()
        logger.info(f"Published {event_type} to RabbitMQ")
        return True
    except Exception as e:
        logger.error(f"RabbitMQ publish failed: {e}")
        return False

# =============================================================================
# FASTAPI APPLICATION
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management"""
    # Startup
    get_engine()
    # init_db()
    yield
    # Shutdown

app = FastAPI(
    title="ZeroQue CV Gateway V4.1",
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

# Add middleware
add_api_call_meter(app)
add_idempotency_middleware(app, routes=[
    ("POST", "/cv/webhook/order"),
])

# =============================================================================
# HEALTH AND ROOT ENDPOINTS
# =============================================================================

@app.get("/")
def root():
    return {"service": SERVICE_NAME, "version": "2.0.0"}

@app.get("/health")
def health():
    return {"status": "ok", "service": SERVICE_NAME}

@app.get("/readiness")
def readiness():
    return {"service": SERVICE_NAME, "db": check_db(), "redis": True}

@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint"""
    from fastapi.responses import Response
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

# =============================================================================
# DEVICE MONITORING ENDPOINTS (Phase 2)
# =============================================================================

@app.get("/devices/status")
async def list_devices(
    tenant_id: str = Query(...),
    site_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    user_context: Dict[str, Any] = Depends(get_user_context),
    db: Session = Depends(get_db_with_rls)
):
    """
    Phase 2: List all devices with health status
    Filter by tenant, site, and status
    """
    try:
        set_rls_context(db, tenant_id)
        
        # Build query
        query = "SELECT * FROM devices WHERE tenant_id = :tenant_id"
        params = {"tenant_id": tenant_id}
        
        if site_id:
            query += " AND site_id = :site_id"
            params["site_id"] = site_id
        
        if status:
            query += " AND status = :status"
            params["status"] = status
        
        query += " ORDER BY created_at DESC"
        
        result = db.execute(text(query), params)
        devices = result.fetchall()
        
        device_list = []
        for device in devices:
            device_list.append({
                "device_id": device[0],
                "tenant_id": str(device[1]),
                "site_id": str(device[2]) if device[2] else None,
                "device_type": device[3],
                "device_name": device[4],
                "zone": device[5],
                "status": device[6],
                "health_score": device[7],
                "last_heartbeat": device[8].isoformat() if device[8] else None,
                "device_metadata": device[9],
                "created_at": device[10].isoformat() if device[10] else None
            })
        
        logger.info(f"Listed {len(device_list)} devices for tenant {tenant_id}")
        
        return {
            "tenant_id": tenant_id,
            "site_id": site_id,
            "status_filter": status,
            "total_devices": len(device_list),
            "devices": device_list
        }
        
    except Exception as e:
        logger.error(f"Failed to list devices: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/devices/{device_id}/status")
async def get_device_status(
    device_id: str,
    tenant_id: str = Query(...),
    user_context: Dict[str, Any] = Depends(get_user_context),
    db: Session = Depends(get_db_with_rls)
):
    """Phase 2: Get single device status"""
    try:
        set_rls_context(db, tenant_id)
        
        device = db.execute(
            text("SELECT * FROM devices WHERE device_id = :device_id AND tenant_id = :tenant_id"),
            {"device_id": device_id, "tenant_id": tenant_id}
        ).first()
        
        if not device:
            raise HTTPException(status_code=404, detail="Device not found")
        
        # Get recent status logs
        logs = db.execute(
            text("""
                SELECT status, health_score, details, created_at 
                FROM device_status_logs 
                WHERE device_id = :device_id 
                ORDER BY created_at DESC LIMIT 10
            """),
            {"device_id": device_id}
        ).fetchall()
        
        # Get open alerts
        alerts = db.execute(
            text("""
                SELECT alert_type, severity, message, status, created_at 
                FROM device_alerts 
                WHERE device_id = :device_id AND status = 'open'
                ORDER BY created_at DESC
            """),
            {"device_id": device_id}
        ).fetchall()
        
        return {
            "device_id": device[0],
            "tenant_id": str(device[1]),
            "site_id": str(device[2]) if device[2] else None,
            "device_type": device[3],
            "device_name": device[4],
            "zone": device[5],
            "status": device[6],
            "health_score": device[7],
            "last_heartbeat": device[8].isoformat() if device[8] else None,
            "device_metadata": device[9],
            "recent_logs": [
                {
                    "status": log[0],
                    "health_score": log[1],
                    "details": log[2],
                    "created_at": log[3].isoformat()
                }
                for log in logs
            ],
            "open_alerts": [
                {
                    "alert_type": alert[0],
                    "severity": alert[1],
                    "message": alert[2],
                    "status": alert[3],
                    "created_at": alert[4].isoformat()
                }
                for alert in alerts
            ]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get device status: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/devices/{device_id}/status")
async def update_device_status(
    device_id: str,
    status_update: DeviceStatusUpdate,
    tenant_id: str = Query(...),
    user_context: Dict[str, Any] = Depends(get_user_context),
    db: Session = Depends(get_db_with_rls)
):
    """
    Phase 2: Update device status (heartbeat, offline, error)
    Called by devices to report health or by monitoring system
    """
    try:
        set_rls_context(db, tenant_id)
        
        # Check if device exists
        device = db.execute(
            text("SELECT status FROM devices WHERE device_id = :device_id AND tenant_id = :tenant_id"),
            {"device_id": device_id, "tenant_id": tenant_id}
        ).first()
        
        if not device:
            raise HTTPException(status_code=404, detail="Device not found")
        
        old_status = device[0]
        
        # Update device
        db.execute(
            text("""
                UPDATE devices 
                SET status = :status, 
                    health_score = :health_score,
                    last_heartbeat = :heartbeat,
                    updated_at = :now
                WHERE device_id = :device_id AND tenant_id = :tenant_id
            """),
            {
                "status": status_update.status,
                "health_score": status_update.health_score,
                "heartbeat": datetime.now(timezone.utc),
                "now": datetime.now(timezone.utc),
                "device_id": device_id,
                "tenant_id": tenant_id
            }
        )
        
        # Log status change
        db.execute(
            text("""
                INSERT INTO device_status_logs (device_id, tenant_id, status, health_score, details)
                VALUES (:device_id, :tenant_id, :status, :health_score, :details)
            """),
            {
                "device_id": device_id,
                "tenant_id": tenant_id,
                "status": status_update.status,
                "health_score": status_update.health_score,
                "details": json.dumps(status_update.details) if status_update.details else None
            }
        )
        
        # Create alert if status changed to offline or error
        if status_update.status in ["offline", "error"] and old_status not in ["offline", "error"]:
            db.execute(
                text("""
                    INSERT INTO device_alerts (device_id, tenant_id, alert_type, severity, message)
                    VALUES (:device_id, :tenant_id, :alert_type, :severity, :message)
                """),
                {
                    "device_id": device_id,
                    "tenant_id": tenant_id,
                    "alert_type": status_update.status,
                    "severity": "critical" if status_update.status == "error" else "warning",
                    "message": f"Device {device_id} is now {status_update.status}"
                }
            )
            
            # TODO: Publish DEVICE_STATUS event for Entitlements usage tracking
            # TODO: Send webhook to Notifications service for alerting
        
        db.commit()
        
        logger.info(f"Updated device {device_id} status to {status_update.status}")
        
        return {
            "success": True,
            "device_id": device_id,
            "old_status": old_status,
            "new_status": status_update.status,
            "health_score": status_update.health_score,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update device status: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/devices/{device_id}/alert")
async def create_device_alert(
    device_id: str,
    alert: DeviceAlertCreate,
    tenant_id: str = Query(...),
    user_context: Dict[str, Any] = Depends(get_user_context),
    db: Session = Depends(get_db_with_rls)
):
    """Phase 2: Create device alert manually"""
    try:
        set_rls_context(db, tenant_id)
        
        # Create alert
        db.execute(
            text("""
                INSERT INTO device_alerts (device_id, tenant_id, alert_type, severity, message)
                VALUES (:device_id, :tenant_id, :alert_type, :severity, :message)
            """),
            {
                "device_id": device_id,
                "tenant_id": tenant_id,
                "alert_type": alert.alert_type,
                "severity": alert.severity,
                "message": alert.message
            }
        )
        
        db.commit()
        
        logger.info(f"Created alert for device {device_id}: {alert.alert_type}")
        
        return {
            "success": True,
            "device_id": device_id,
            "alert_type": alert.alert_type,
            "severity": alert.severity,
            "message": alert.message,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        
    except Exception as e:
        logger.error(f"Failed to create device alert: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

# =============================================================================
# WEBHOOK ENDPOINTS
# =============================================================================

@app.post("/cv/webhook/order", response_model=OrderResponse)
async def cv_order_webhook(
    order: AiFiOrder,
    user_context: Dict[str, Any] = Depends(get_user_context),
    db = Depends(get_db_with_rls)
):
    """Process CV order webhook with saga pattern"""
    # Update metrics
    cv_gateway_requests_total.labels(
        method="POST", endpoint="/cv/webhook/order", provider=order.provider, status="started"
    ).inc()
    
    start_time = datetime.now()
    
    try:
        set_rls_context(db, order.tenant_id or order.tenant_ext_id or "default")
        
        # Create and execute saga
        saga = CvOrderSaga(db, order.model_dump())
        result = await saga.execute()
        
        # Log audit
        await log_audit(
            db, "cv_order_processed", "order",
            details={"provider": order.provider, "order_id": result.get("order_id")},
            tenant_id=order.tenant_id
        )
        
        # Update metrics
        duration = (datetime.now() - start_time).total_seconds()
        cv_gateway_request_duration.labels(
            method="POST", endpoint="/cv/webhook/order", provider=order.provider
        ).observe(duration)
        
        cv_order_processing_total.labels(
            provider=order.provider, status="success", reason="completed"
        ).inc()
        
        cv_gateway_requests_total.labels(
            method="POST", endpoint="/cv/webhook/order", provider=order.provider, status="success"
        ).inc()

        # Audit log
        audit_log(db, "create_cv_order", "cv_orders_new", str(order.order_id), user_context, order.dict(), 201)

        return OrderResponse(**result)
        
    except HTTPException as e:
        # Update metrics for HTTP exceptions
        duration = (datetime.now() - start_time).total_seconds()
        cv_gateway_request_duration.labels(
            method="POST", endpoint="/cv/webhook/order", provider=order.provider
        ).observe(duration)
        
        cv_order_processing_total.labels(
            provider=order.provider, status="failure", reason=f"http_{e.status_code}"
        ).inc()
        
        cv_gateway_requests_total.labels(
            method="POST", endpoint="/cv/webhook/order", provider=order.provider, status="error"
        ).inc()
        raise
    except Exception as e:
        db.rollback()
        
        # Update metrics for other exceptions
        duration = (datetime.now() - start_time).total_seconds()
        cv_gateway_request_duration.labels(
            method="POST", endpoint="/cv/webhook/order", provider=order.provider
        ).observe(duration)
        
        cv_order_processing_total.labels(
            provider=order.provider, status="failure", reason="exception"
        ).inc()
        
        cv_gateway_requests_total.labels(
            method="POST", endpoint="/cv/webhook/order", provider=order.provider, status="error"
        ).inc()
        
        raise HTTPException(status_code=500, detail=f"Order processing failed: {str(e)}")

# =============================================================================
# REVIEW MANAGEMENT ENDPOINTS
# =============================================================================

@app.get("/cv/reviews")
async def list_reviews(
    tenant_id: str = Query(...),
    status: str = Query("pending"),
    limit: int = Query(50),
    db: Session = Depends(get_db)
):
    """List unknown item reviews for reconciliation"""
    try:
        set_rls_context(db, tenant_id)
        
        rows = db.execute(text("""
            SELECT id, provider, external_sku, name, qty, price_minor, status, created_at
              FROM cv_unknown_item_reviews
             WHERE tenant_id=:t AND status=:s
             ORDER BY id DESC
             LIMIT :l
        """), {"t": tenant_id, "s": status, "l": limit}).all()
        
        return [{
            "id": str(r[0]), "provider": r[1], "external_sku": r[2], "name": r[3],
            "qty": int(r[4]), "price_minor": int(r[5] or 0), "status": r[6], "created_at": str(r[7])
        } for r in rows]

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list reviews: {str(e)}")

@app.post("/cv/reviews/{review_id}/resolve")
async def resolve_review(
    review_id: str = Path(...),
    payload: ReviewResolvePayload = Body(...),
    db: Session = Depends(get_db)
):
    """Resolve an unknown item review"""
    try:
        # Get review to find tenant_id
        review = db.execute(text("""
            SELECT tenant_id FROM cv_unknown_item_reviews WHERE id=:id
        """), {"id": review_id}).first()
        
        if not review:
            raise HTTPException(status_code=404, detail="Review not found")
        
        set_rls_context(db, str(review[0]))
        
        # Update review
        db.execute(text("""
            UPDATE cv_unknown_item_reviews
               SET status=:st, mapped_sku=:ms, notes=:n, resolved_at=NOW()
             WHERE id=:id
        """), {"st": payload.status, "ms": payload.mapped_sku, "n": payload.notes, "id": review_id})
        
        db.commit()
        
        # Log audit
        await log_audit(
            db, "review_resolved", "cv_unknown_item_review",
            details={"review_id": review_id, "status": payload.status},
            tenant_id=str(review[0])
        )
        
        return {"id": review_id, "status": payload.status}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to resolve review: {str(e)}")

# =============================================================================
# INTEGRATION ENDPOINTS
# =============================================================================

@app.post("/cv/v4/integration/orders/create-order")
async def create_order_in_orders_service(
    tenant_id: str = Body(...),
    order_data: Dict[str, Any] = Body(...)
):
    """Integration endpoint to create order in Orders service"""
    try:
        logger.info(f"Creating order in Orders service for CV Gateway: tenant_id={tenant_id}")
        
        # Prepare order data for Orders service
        orders_data = {
            "tenant_id": tenant_id,
            "site_id": order_data.get("site_id"),
            "store_id": order_data.get("store_id"),
            "user_id": order_data.get("shopper_id"),
            "currency": order_data.get("currency", "GBP"),
            "total_minor": order_data.get("total_minor", 0),
            "items": order_data.get("items", []),
            "provider": order_data.get("provider"),
            "provider_order_id": order_data.get("provider_order_id"),
            "event_source": "cv_gateway"
        }
        
        # Notify Orders service via HTTP call
        try:
            import httpx
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    "http://localhost:8081/orders/v2",
                    json=orders_data
                )
                
                if response.status_code == 200:
                    result = response.json()
                    logger.info(f"Successfully created order in Orders service: {result}")
                    return {"ok": True, "order_created": True, "order_id": result.get("order_id")}
                else:
                    logger.warning(f"Orders service returned status {response.status_code}")
                    return {"ok": False, "order_created": False, "error": "Orders service error"}
                    
        except Exception as e:
            logger.error(f"Failed to create order in Orders service: {str(e)}")
            return {"ok": False, "order_created": False, "error": str(e)}
            
    except Exception as e:
        logger.error(f"Error creating order in Orders service: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to create order: {str(e)}")

@app.post("/cv/v4/integration/approvals/budget-check")
async def check_budget_with_approvals_service(
    tenant_id: str = Body(...),
    amount_minor: int = Body(...),
    currency: str = Body("GBP"),
    cost_centre_id: str = Body(None),
    site_id: str = Body(None),
    store_id: str = Body(None)
):
    """Integration endpoint to check budget with Approvals service"""
    try:
        logger.info(f"Checking budget with Approvals service: tenant_id={tenant_id}, amount={amount_minor}")
        
        # Prepare budget check data
        budget_check_data = {
            "tenant_id": tenant_id,
            "amount_minor": amount_minor,
            "currency": currency,
            "cost_centre_id": cost_centre_id,
            "site_id": site_id,
            "store_id": store_id
        }
        
        # Notify Approvals service via HTTP call
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    "http://localhost:8084/approvals/v2/integration/cv-gateway/budget-check",
                    json=budget_check_data
                )
                
                if response.status_code == 200:
                    result = response.json()
                    logger.info(f"Successfully checked budget with Approvals service: {result}")
                    return result
                else:
                    logger.warning(f"Approvals service returned status {response.status_code}")
                    return {"ok": False, "error": "Approvals service error"}
                    
        except Exception as e:
            logger.error(f"Failed to check budget with Approvals service: {str(e)}")
            return {"ok": False, "error": str(e)}
            
    except Exception as e:
        logger.error(f"Error checking budget with Approvals service: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to check budget: {str(e)}")

@app.post("/cv/v4/integration/billing/create-invoice")
async def create_invoice_with_billing_service(
    tenant_id: str = Body(...),
    order_id: str = Body(...),
    total_amount_minor: int = Body(...),
    currency: str = Body("GBP"),
    customer_id: str = Body(None),
    items: List[Dict[str, Any]] = Body(...)
):
    """Integration endpoint to create invoice with Billing service"""
    try:
        logger.info(f"Creating invoice with Billing service: tenant_id={tenant_id}, order_id={order_id}")
        
        # Prepare invoice data
        invoice_data = {
            "tenant_id": tenant_id,
            "order_id": order_id,
            "total_amount_minor": total_amount_minor,
            "currency": currency,
            "customer_id": customer_id,
            "items": items
        }
        
        # Notify Billing service via HTTP call
        try:
            import httpx
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    "http://localhost:8083/billing/v2/integration/cv-gateway/invoice-creation",
                    json=invoice_data
                )
                
                if response.status_code == 200:
                    result = response.json()
                    logger.info(f"Successfully created invoice with Billing service: {result}")
                    return result
                else:
                    logger.warning(f"Billing service returned status {response.status_code}")
                    return {"ok": False, "error": "Billing service error"}
                    
        except Exception as e:
            logger.error(f"Failed to create invoice with Billing service: {str(e)}")
            return {"ok": False, "error": str(e)}
            
    except Exception as e:
        logger.error(f"Error creating invoice with Billing service: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to create invoice: {str(e)}")

@app.get("/cv/v4/integration/status")
async def get_integration_status():
    """Get status of all service integrations"""
    try:
        integration_status = {
            "orders_service": {"status": "unknown", "url": "http://localhost:8081"},
            "approvals_service": {"status": "unknown", "url": "http://localhost:8084"},
            "billing_service": {"status": "unknown", "url": "http://localhost:8083"},
            "ledger_service": {"status": "unknown", "url": "http://localhost:8086"},
            "cv_connector_service": {"status": "unknown", "url": "http://localhost:8100"}
        }
        
        # Test each service connectivity
        import httpx
        async with httpx.AsyncClient(timeout=5.0) as client:
            for service_name, config in integration_status.items():
                try:
                    response = await client.get(f"{config['url']}/health")
                    if response.status_code == 200:
                        config["status"] = "healthy"
                        config["response_time_ms"] = response.elapsed.total_seconds() * 1000
                    else:
                        config["status"] = "unhealthy"
                except Exception as e:
                    config["status"] = "unreachable"
                    config["error"] = str(e)
        
        return {
            "integration_status": integration_status,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error getting integration status: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get integration status: {str(e)}")

# =============================================================================
# STATISTICS ENDPOINTS
# =============================================================================

@app.get("/cv/orders")
async def list_cv_orders(
    tenant_id: str = Query(...),
    limit: int = Query(50),
    db: Session = Depends(get_db)
):
    """List CV orders for a tenant"""
    try:
        set_rls_context(db, tenant_id)
        
        rows = db.execute(text("""
            SELECT order_id, provider, provider_order_id, total_minor, currency, status, occurred_at
              FROM orders_new
             WHERE tenant_id=:t AND provider IS NOT NULL
             ORDER BY occurred_at DESC
             LIMIT :l
        """), {"t": tenant_id, "l": limit}).all()
        
        return [{
            "order_id": int(r[0]), "provider": r[1], "provider_order_id": r[2],
            "total_minor": int(r[3]), "currency": r[4], "status": r[5], "occurred_at": str(r[6])
        } for r in rows]
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list CV orders: {str(e)}")

@app.get("/cv/stats/{tenant_id}")
async def get_cv_stats(tenant_id: str = Path(...), db: Session = Depends(get_db)):
    """Get CV statistics for a tenant"""
    try:
        set_rls_context(db, tenant_id)
        
        # Total orders
        total_orders = db.execute(text("""
            SELECT COUNT(*) FROM orders_new WHERE tenant_id=:t AND provider IS NOT NULL
        """), {"t": tenant_id}).scalar()
        
        # Total revenue
        total_revenue = db.execute(text("""
            SELECT COALESCE(SUM(total_minor), 0) FROM orders_new 
            WHERE tenant_id=:t AND provider IS NOT NULL AND status='completed'
        """), {"t": tenant_id}).scalar()
        
        # Pending reviews
        pending_reviews = db.execute(text("""
            SELECT COUNT(*) FROM cv_unknown_item_reviews 
            WHERE tenant_id=:t AND status='pending'
        """), {"t": tenant_id}).scalar()
        
        return {
            "tenant_id": tenant_id,
            "total_orders": int(total_orders),
            "total_revenue_minor": int(total_revenue),
            "pending_reviews": int(pending_reviews)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get CV stats: {str(e)}")

# =============================================================================
# LEGACY ENDPOINTS (DEPRECATED)
# =============================================================================

@app.post("/cv/aifi/webhook/order")
async def aifi_order_legacy(payload: dict = Body(...)):
    """Legacy AiFi order webhook - DEPRECATED"""
    return {
        "deprecated": True,
        "migrate_to": "/cv/webhook/order",
        "message": "This endpoint is deprecated. Please use /cv/webhook/order with provider parameter."
    }

# =============================================================================
# MAIN EXECUTION
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    logger.info(f"Starting {SERVICE_NAME} service v{SERVICE_VERSION}")
    port = int(os.getenv("SERVICE_PORT", os.getenv("PORT", "8217")))
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=ENVIRONMENT == "development"
    )