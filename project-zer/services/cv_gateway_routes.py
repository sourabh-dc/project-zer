import uuid
import json
from typing import Optional, Dict, Any
from datetime import datetime, timezone
from fastapi import Body, HTTPException, Query, Path, Depends, APIRouter
from sqlalchemy.orm import Session

from Models import Device, DeviceAlert, DeviceStatusLog, CvUnknownItemReview
from Schemas import DeviceStatusUpdate, DeviceAlertCreate, AiFiOrder, OrderResponse, ReviewResolvePayload
from core.db_config import get_db
from core.user_auth import get_user_context, set_rls_context
from utils.logger import logger

# =============================================================================
# FASTAPI APPLICATION
# =============================================================================
app = APIRouter()

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
