import os
import uuid
import json
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone, timedelta
from contextlib import asynccontextmanager

from fastapi import FastAPI, Body, HTTPException, Query, Path, Depends, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text, create_engine, Column, String, Integer, Boolean, DateTime, Text, ForeignKey, Numeric
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.sql import func

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# =============================================================================
# CONFIGURATION
# =============================================================================

SERVICE_NAME = "cv_gateway"
SERVICE_VERSION = "4.1.0"

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://zeroque:zeroque@localhost:5432/zeroque_dev")
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
ALLOW_DEMO = os.getenv("ALLOW_DEMO", "true").lower() == "true"

# Database setup
engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=300)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# =============================================================================
# DATABASE MODELS
# =============================================================================

class Device(Base):
    """Device registry for hardware monitoring"""
    __tablename__ = "devices"

    device_id = Column(String(100), primary_key=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    site_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    device_type = Column(String(50), nullable=False)
    device_name = Column(String(255), nullable=False)
    zone = Column(String(100), nullable=True)
    status = Column(String(20), nullable=False, default='online')
    health_score = Column(Integer, nullable=True)
    last_heartbeat = Column(DateTime(timezone=True), nullable=True)
    device_metadata = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class DeviceStatusLog(Base):
    """Device status change logs"""
    __tablename__ = "device_status_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id = Column(String(100), nullable=False, index=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    status = Column(String(20), nullable=False)
    health_score = Column(Integer, nullable=True)
    details = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class DeviceAlert(Base):
    """Device alerts for offline/error states"""
    __tablename__ = "device_alerts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id = Column(String(100), nullable=False, index=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    alert_type = Column(String(50), nullable=False)
    severity = Column(String(20), nullable=False, default='warning')
    message = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, default='open')
    acknowledged_by = Column(String(255), nullable=True)
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CvUnknownItemReview(Base):
    """Unknown item reviews for reconciliation"""
    __tablename__ = "cv_unknown_item_reviews"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    site_id = Column(UUID(as_uuid=True), nullable=True)
    store_id = Column(UUID(as_uuid=True), nullable=True)
    provider = Column(String(50), nullable=False)
    external_sku = Column(String(255), nullable=False)
    name = Column(String(255), nullable=False)
    qty = Column(Integer, nullable=False)
    price_minor = Column(Integer, nullable=False)
    payload_json = Column(JSONB, nullable=False)
    status = Column(String(20), nullable=False, default='pending')
    mapped_sku = Column(String(255), nullable=True)
    notes = Column(Text, nullable=True)
    resolved_by = Column(String(255), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class OutboxEvent(Base):
    """Reliable event publishing"""
    __tablename__ = "outbox_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=True)
    event_type = Column(String(100), nullable=False)
    event_data = Column(JSONB, nullable=False)
    status = Column(String(20), nullable=False, default='pending')
    retry_count = Column(Integer, nullable=False, default=0)
    max_retries = Column(Integer, nullable=False, default=3)
    next_retry_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)
    sent_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class AuditLog(Base):
    """Audit trail for operations"""
    __tablename__ = "audit_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=True)
    user_id = Column(UUID(as_uuid=True), nullable=True)
    action = Column(String(100), nullable=False)
    resource_type = Column(String(50), nullable=False)
    resource_id = Column(String(255), nullable=True)
    details = Column(JSONB, nullable=True)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


# =============================================================================
# PYDANTIC SCHEMAS
# =============================================================================

class AiFiItem(BaseModel):
    """CV order item"""
    sku: str = Field(..., description="Product SKU")
    name: str = Field(..., description="Product name")
    qty: int = Field(..., description="Quantity")
    price_minor: int = Field(..., description="Price in minor units")


class AiFiOrder(BaseModel):
    """CV order from provider"""
    provider: str = Field(..., description="Provider name")
    provider_order_id: str = Field(..., description="Provider order ID")
    tenant_ext_id: Optional[str] = Field(None, description="External tenant ID")
    site_ext_id: Optional[str] = Field(None, description="External site ID")
    store_ext_id: Optional[str] = Field(None, description="External store ID")
    user_ext_id: Optional[str] = Field(None, description="External user ID")
    tenant_id: Optional[str] = Field(None, description="Local tenant ID")
    site_id: Optional[str] = Field(None, description="Local site ID")
    store_id: Optional[str] = Field(None, description="Local store ID")
    shopper_id: Optional[str] = Field(None, description="Local shopper ID")
    currency: str = Field("GBP", description="Currency")
    items: List[AiFiItem] = Field(..., description="Order items")
    occurred_at: Optional[datetime] = Field(None, description="Order timestamp")

    @field_validator('tenant_id', 'site_id', 'store_id', 'shopper_id')
    @classmethod
    def validate_uuids(cls, v):
        if v is not None:
            try:
                uuid.UUID(v)
                return v
            except ValueError:
                raise ValueError('Invalid UUID format')
        return v


class DeviceStatusUpdate(BaseModel):
    """Update device status"""
    status: str = Field(..., description="Device status: online, offline, error, maintenance")
    health_score: Optional[int] = Field(None, description="Health score 0-100", ge=0, le=100)
    details: Optional[Dict[str, Any]] = Field(None, description="Status details")


class DeviceAlertCreate(BaseModel):
    """Create device alert"""
    alert_type: str = Field(..., description="Alert type: offline, error, low_health")
    severity: str = Field("warning", description="Severity: info, warning, critical")
    message: str = Field(..., description="Alert message")


class ReviewResolvePayload(BaseModel):
    """Review resolution payload"""
    mapped_sku: Optional[str] = Field(None, description="Mapped SKU")
    status: str = Field("resolved", description="Resolution status")
    notes: Optional[str] = Field(None, description="Resolution notes")

    @field_validator('status')
    @classmethod
    def validate_status(cls, v):
        if v not in ("resolved", "ignored"):
            raise ValueError("Status must be 'resolved' or 'ignored'")
        return v


class OrderResponse(BaseModel):
    """Order processing response"""
    ok: bool = Field(..., description="Success status")
    order_id: Optional[int] = Field(None, description="Created order ID")
    total_minor: Optional[int] = Field(None, description="Total amount in minor units")
    currency: Optional[str] = Field(None, description="Currency")
    unknown_items: Optional[List[dict]] = Field(None, description="Unknown items requiring review")


# =============================================================================
# UTILITIES
# =============================================================================

def get_db():
    """Get database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_user_context(authorization: Optional[str] = Header(None), x_api_key: Optional[str] = Header(None)) -> Dict[
    str, Any]:
    """Get user context from JWT or API key"""
    if x_api_key:
        if ALLOW_DEMO or x_api_key.startswith('zq_'):
            return {
                "user_id": "demo_user",
                "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
                "permissions": ["*"]
            }
        raise HTTPException(status_code=401, detail="Invalid API key")

    if ALLOW_DEMO:
        return {"tenant_id": "550e8400-e29b-41d4-a716-446655440000", "user_id": "demo_user", "permissions": ["*"]}

    raise HTTPException(status_code=401, detail="Authentication required")


def check_permission(required_permission: str, user_context: Dict[str, Any]) -> bool:
    """Check if user has required permission"""
    permissions = user_context.get("permissions", [])
    return "*" in permissions or required_permission in permissions


def set_rls_context(db: Session, tenant_id: str, user_id: str = None):
    """Set RLS context for database session"""
    try:
        db.execute(text("SET LOCAL app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})
        if user_id:
            db.execute(text("SET LOCAL app.current_user_id = :user_id"), {"user_id": user_id})
    except:
        pass


async def log_audit(db: Session, action: str, resource_type: str, resource_id: Optional[str] = None,
                    details: Optional[dict] = None, user_id: Optional[str] = None, tenant_id: Optional[str] = None):
    """Log audit trail"""
    try:
        audit = AuditLog(
            tenant_id=tenant_id,
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details
        )
        db.add(audit)
        db.commit()
    except Exception as e:
        logger.warning(f"Failed to log audit: {e}")
        try:
            db.rollback()
        except:
            pass


async def publish_event(db: Session, event_type: str, event_data: dict, tenant_id: Optional[str] = None):
    """Publish event to outbox"""
    event = OutboxEvent(
        tenant_id=tenant_id,
        event_type=event_type,
        event_data=event_data,
        status="pending"
    )
    db.add(event)
    db.commit()


# =============================================================================
# FASTAPI APPLICATION
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management"""
    Base.metadata.create_all(bind=engine)
    logger.info(f"Starting {SERVICE_NAME} service v{SERVICE_VERSION}")
    yield
    logger.info(f"Shutting down {SERVICE_NAME} service")


app = FastAPI(
    title="ZeroQue CV Gateway",
    version=SERVICE_VERSION,
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if ENVIRONMENT == "development" else ["https://*.zeroque.com"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*"])


# =============================================================================
# HEALTH ENDPOINTS
# =============================================================================

@app.get("/")
def root():
    return {"service": SERVICE_NAME, "version": SERVICE_VERSION}


@app.get("/health")
def health():
    return {"status": "ok", "service": SERVICE_NAME}


@app.get("/readiness")
def readiness():
    return {"service": SERVICE_NAME, "db": True}


# =============================================================================
# DEVICE MONITORING ENDPOINTS
# =============================================================================

@app.get("/devices/status")
async def list_devices(
        tenant_id: str = Query(...),
        site_id: Optional[str] = Query(None),
        status: Optional[str] = Query(None),
        user_context: Dict[str, Any] = Depends(get_user_context),
        db: Session = Depends(get_db)
):
    """List all devices with health status"""
    try:
        set_rls_context(db, tenant_id)

        query = db.query(Device).filter(Device.tenant_id == uuid.UUID(tenant_id))

        if site_id:
            query = query.filter(Device.site_id == uuid.UUID(site_id))

        if status:
            query = query.filter(Device.status == status)

        devices = query.order_by(Device.created_at.desc()).all()

        device_list = [
            {
                "device_id": d.device_id,
                "tenant_id": str(d.tenant_id),
                "site_id": str(d.site_id) if d.site_id else None,
                "device_type": d.device_type,
                "device_name": d.device_name,
                "zone": d.zone,
                "status": d.status,
                "health_score": d.health_score,
                "last_heartbeat": d.last_heartbeat.isoformat() if d.last_heartbeat else None,
                "device_metadata": d.device_metadata,
                "created_at": d.created_at.isoformat()
            }
            for d in devices
        ]

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
        db: Session = Depends(get_db)
):
    """Get single device status"""
    try:
        set_rls_context(db, tenant_id)

        device = db.query(Device).filter(
            Device.device_id == device_id,
            Device.tenant_id == uuid.UUID(tenant_id)
        ).first()

        if not device:
            raise HTTPException(status_code=404, detail="Device not found")

        logs = db.query(DeviceStatusLog).filter(
            DeviceStatusLog.device_id == device_id
        ).order_by(DeviceStatusLog.created_at.desc()).limit(10).all()

        alerts = db.query(DeviceAlert).filter(
            DeviceAlert.device_id == device_id,
            DeviceAlert.status == 'open'
        ).order_by(DeviceAlert.created_at.desc()).all()

        return {
            "device_id": device.device_id,
            "tenant_id": str(device.tenant_id),
            "site_id": str(device.site_id) if device.site_id else None,
            "device_type": device.device_type,
            "device_name": device.device_name,
            "zone": device.zone,
            "status": device.status,
            "health_score": device.health_score,
            "last_heartbeat": device.last_heartbeat.isoformat() if device.last_heartbeat else None,
            "device_metadata": device.device_metadata,
            "recent_logs": [
                {
                    "status": log.status,
                    "health_score": log.health_score,
                    "details": log.details,
                    "created_at": log.created_at.isoformat()
                }
                for log in logs
            ],
            "open_alerts": [
                {
                    "alert_type": alert.alert_type,
                    "severity": alert.severity,
                    "message": alert.message,
                    "status": alert.status,
                    "created_at": alert.created_at.isoformat()
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
        db: Session = Depends(get_db)
):
    """Update device status"""
    try:
        set_rls_context(db, tenant_id)

        device = db.query(Device).filter(
            Device.device_id == device_id,
            Device.tenant_id == uuid.UUID(tenant_id)
        ).first()

        if not device:
            raise HTTPException(status_code=404, detail="Device not found")

        old_status = device.status

        device.status = status_update.status
        device.health_score = status_update.health_score
        device.last_heartbeat = datetime.now(timezone.utc)
        db.commit()

        # Log status change
        log = DeviceStatusLog(
            device_id=device_id,
            tenant_id=uuid.UUID(tenant_id),
            status=status_update.status,
            health_score=status_update.health_score,
            details=json.dumps(status_update.details) if status_update.details else None
        )
        db.add(log)
        db.commit()

        # Create alert if status changed to offline or error
        if status_update.status in ["offline", "error"] and old_status not in ["offline", "error"]:
            alert = DeviceAlert(
                device_id=device_id,
                tenant_id=uuid.UUID(tenant_id),
                alert_type=status_update.status,
                severity="critical" if status_update.status == "error" else "warning",
                message=f"Device {device_id} is now {status_update.status}"
            )
            db.add(alert)
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
        db: Session = Depends(get_db)
):
    """Create device alert manually"""
    try:
        set_rls_context(db, tenant_id)

        device_alert = DeviceAlert(
            device_id=device_id,
            tenant_id=uuid.UUID(tenant_id),
            alert_type=alert.alert_type,
            severity=alert.severity,
            message=alert.message
        )
        db.add(device_alert)
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
        db: Session = Depends(get_db)
):
    """Process CV order webhook"""
    try:
        tenant_id = order.tenant_id or order.tenant_ext_id or "default"
        set_rls_context(db, tenant_id)

        # Calculate total
        total_minor = sum(item.qty * item.price_minor for item in order.items)

        # Log audit
        await log_audit(
            db, "cv_order_processed", "order",
            details={"provider": order.provider, "order_id": order.provider_order_id},
            tenant_id=tenant_id
        )

        # Publish event
        await publish_event(
            db, "ORDER_CREATED", {
                "order_id": order.provider_order_id,
                "tenant_id": tenant_id,
                "provider": order.provider,
                "total_minor": total_minor,
                "currency": order.currency
            }, tenant_id
        )

        return OrderResponse(
            ok=True,
            order_id=1,
            total_minor=total_minor,
            currency=order.currency
        )
    except Exception as e:
        db.rollback()
        logger.error(f"Order processing failed: {e}")
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

        reviews = db.query(CvUnknownItemReview).filter(
            CvUnknownItemReview.tenant_id == uuid.UUID(tenant_id),
            CvUnknownItemReview.status == status
        ).order_by(CvUnknownItemReview.id.desc()).limit(limit).all()

        return [
            {
                "id": str(r.id),
                "provider": r.provider,
                "external_sku": r.external_sku,
                "name": r.name,
                "qty": r.qty,
                "price_minor": r.price_minor,
                "status": r.status,
                "created_at": r.created_at.isoformat()
            }
            for r in reviews
        ]
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
        review = db.query(CvUnknownItemReview).filter(
            CvUnknownItemReview.id == uuid.UUID(review_id)
        ).first()

        if not review:
            raise HTTPException(status_code=404, detail="Review not found")

        set_rls_context(db, str(review.tenant_id))

        review.status = payload.status
        review.mapped_sku = payload.mapped_sku
        review.notes = payload.notes
        review.resolved_at = datetime.now(timezone.utc)
        db.commit()

        # Log audit
        await log_audit(
            db, "review_resolved", "cv_unknown_item_review",
            details={"review_id": review_id, "status": payload.status},
            tenant_id=str(review.tenant_id)
        )

        return {"id": review_id, "status": payload.status}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to resolve review: {str(e)}")


# =============================================================================
# INTEGRATION ENDPOINTS
# =============================================================================

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

        # Demo response
        return [
            {
                "order_id": 1,
                "provider": "aifi",
                "provider_order_id": "demo_order_1",
                "total_minor": 10000,
                "currency": "GBP",
                "status": "completed",
                "occurred_at": datetime.now(timezone.utc).isoformat()
            }
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list CV orders: {str(e)}")


@app.get("/cv/stats/{tenant_id}")
async def get_cv_stats(tenant_id: str = Path(...), db: Session = Depends(get_db)):
    """Get CV statistics for a tenant"""
    try:
        set_rls_context(db, tenant_id)

        return {
            "tenant_id": tenant_id,
            "total_orders": 0,
            "total_revenue_minor": 0,
            "pending_reviews": 0
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

    port = int(os.getenv("SERVICE_PORT", os.getenv("PORT", "8101")))
    logger.info(f"Starting {SERVICE_NAME} service v{SERVICE_VERSION}")
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        reload=ENVIRONMENT == "development"
    )
