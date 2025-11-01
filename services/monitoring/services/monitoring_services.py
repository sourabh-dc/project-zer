from typing import Optional

from fastapi import HTTPException

from services.monitoring.schemas import HealthCheckRequest, ServiceStatus, AlertRequest
from services.monitoring.utils.monitoring_logger import logger
from .celery_tasks import check_service_health
from ..repositories.database_ops import get_latest_service_health, fetch_services, create_alert_db, fetch_alerts
from ..utils.metrics import active_alerts


async def check_health(request: HealthCheckRequest):
    """Initiate health check for a service"""
    try:
        # Queue health check task
        task = check_service_health.delay(
            request.service_name,
            request.endpoint,
            request.timeout_seconds
        )

        logger.info("Health check initiated",
                    service=request.service_name, task_id=task.id)

        return {
            "task_id": task.id,
            "service_name": request.service_name,
            "status": "initiated"
        }

    except Exception as e:
        logger.error("Failed to initiate health check", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


async def get_service_health_status(service_name: str):
    """Get current status of a service"""
    try:
        latest_health = get_latest_service_health(service_name)

        if not latest_health:
            raise HTTPException(status_code=404, detail="Service not found")

        return ServiceStatus(
            service_name=latest_health.service_name,
            status=latest_health.status,
            response_time_ms=latest_health.response_time_ms,
            last_check=latest_health.last_check,
            error_message=latest_health.error_message
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get service status", service=service_name, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


async def get_services():
    """List all monitored services"""
    try:
        services = fetch_services()

        return [
            {
                "service_name": service.service_name,
                "last_status": service.status,
                "last_check": service.last_check
            }
            for service in services
        ]

    except Exception as e:
        logger.error("Failed to list services", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


async def create_alert(request: AlertRequest):
    """Create a new alert"""
    try:
        alert = create_alert_db(request)

        # Update metrics
        active_alerts.labels(severity=request.severity).inc()

        logger.info("Alert created",
                    service=request.service_name, severity=request.severity)

        return {
            "alert_id": alert.id,
            "status": "created"
        }

    except Exception as e:
        logger.error("Failed to create alert", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


async def get_alerts(service_name: Optional[str], severity: Optional[str], status: str):
    """List alerts with optional filtering"""
    try:
        alerts = fetch_alerts(service_name, severity, status)

        return [
            {
                "id": alert.id,
                "service_name": alert.service_name,
                "alert_type": alert.alert_type,
                "severity": alert.severity,
                "message": alert.message,
                "status": alert.status,
                "created_at": alert.created_at,
                "metadata": alert.metadata
            }
            for alert in alerts
        ]

    except Exception as e:
        logger.error("Failed to list alerts", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))