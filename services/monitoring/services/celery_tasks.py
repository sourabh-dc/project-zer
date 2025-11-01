import time
from typing import Dict, Any

import httpx
from datetime import datetime, timedelta, timezone
from sqlalchemy import text

from ..repositories.db_config import SessionLocal
from ..core.celery_config import celery_app
from ..models import ServiceHealth, Alert
from ..utils.metrics import (
    monitoring_checks_total,
    monitoring_check_duration,
    service_health_status, monitoring_operations_total
)
from ..utils.monitoring_logger import logger
# =============================================================================
# CELERY TASKS
# =============================================================================

@celery_app.task(bind=True, max_retries=3)
def check_service_health(self, service_name: str, endpoint: str, timeout: int = 30):
    """Check health of a specific service"""
    start_time = time.time()

    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.get(endpoint)

        response_time_ms = int((time.time() - start_time) * 1000)
        status = "healthy" if response.status_code == 200 else "unhealthy"

        # Store result in database
        with SessionLocal() as db:
            health_record = ServiceHealth(
                service_name=service_name,
                status=status,
                response_time_ms=response_time_ms,
                error_message=None if status == "healthy" else f"HTTP {response.status_code}"
            )
            db.add(health_record)
            db.commit()

        # Update metrics
        monitoring_checks_total.labels(service=service_name, status=status).inc()
        monitoring_check_duration.labels(service=service_name).observe(time.time() - start_time)
        service_health_status.labels(service=service_name).set(1 if status == "healthy" else 0)

        logger.info("Service health check completed",
                    service=service_name, status=status, response_time_ms=response_time_ms)

        return {"status": status, "response_time_ms": response_time_ms}

    except Exception as e:
        logger.error("Service health check failed", service=service_name, error=str(e))

        # Store failure in database
        with SessionLocal() as db:
            health_record = ServiceHealth(
                service_name=service_name,
                status="unhealthy",
                response_time_ms=None,
                error_message=str(e)
            )
            db.add(health_record)
            db.commit()

        # Update metrics
        monitoring_checks_total.labels(service=service_name, status="unhealthy").inc()
        service_health_status.labels(service=service_name).set(0)

        # Retry if not exceeded max retries
        if self.request.retries < self.max_retries:
            raise self.retry(countdown=60 * (2 ** self.request.retries))

        return {"status": "unhealthy", "error": str(e)}


@celery_app.task
def cleanup_old_health_records():
    """Clean up old health check records"""
    try:
        with SessionLocal() as db:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=7)
            deleted = db.execute(
                text("DELETE FROM service_health_new WHERE created_at < :cutoff"),
                {"cutoff": cutoff_date}
            )
            db.commit()

        logger.info("Cleaned up old health records", deleted_count=deleted.rowcount)
        return {"deleted_count": deleted.rowcount}

    except Exception as e:
        logger.error("Failed to cleanup health records", error=str(e))
        return {"error": str(e)}


@celery_app.task(bind=True, max_retries=3)
def process_health_check(self, service_name: str, service_url: str):
    """Process health check for a service (sync httpx client)"""
    try:
        with httpx.Client(timeout=5.0) as client:
            response = client.get(f"{service_url}/health")
            status = "healthy" if response.status_code == 200 else "unhealthy"
            monitoring_checks_total.labels(service=service_name, status=status).inc()
            logger.info("Health check completed", service=service_name, status=status)
    except Exception as e:
        logger.error("Failed to process health check", service=service_name, error=str(e))
        monitoring_checks_total.labels(service=service_name, status="failed").inc()
        raise self.retry(exc=e, countdown=60)


@celery_app.task(bind=True, max_retries=3)
def process_alert_notification(self, alert_id: str, notification_data: Dict[str, Any]):
    """Process alert notification asynchronously"""
    try:
        with SessionLocal() as db:
            # Get alert
            alert = db.query(Alert).filter(Alert.id == alert_id).first()
            if not alert:
                raise ValueError(f"Alert {alert_id} not found")

            # Process notification logic here
            logger.info(f"Processing alert notification for alert {alert_id}")

            # Update metrics
            monitoring_operations_total.labels(operation="notification", status="success").inc()

    except Exception as e:
        logger.error(f"Failed to process alert notification for alert {alert_id}: {e}")
        monitoring_operations_total.labels(operation="notification", status="failed").inc()
        raise self.retry(exc=e, countdown=60)


@celery_app.task(bind=True, max_retries=3)
def cleanup_old_monitoring_data(self):
    """Clean up old monitoring data"""
    try:
        with SessionLocal() as db:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=90)

            # Clean up old alerts
            alert_result = db.execute(text("""
                                           DELETE
                                           FROM alerts_new
                                           WHERE created_at < :cutoff_date
                                             AND status IN ('resolved', 'acknowledged')
                                           """), {"cutoff_date": cutoff_date})

            # Clean up old metrics
            metric_result = db.execute(text("""
                                            DELETE
                                            FROM metrics_new
                                            WHERE created_at < :cutoff_date
                                            """), {"cutoff_date": cutoff_date})

            db.commit()

            logger.info(f"Cleaned up {alert_result.rowcount} old alerts and {metric_result.rowcount} old metrics")

    except Exception as e:
        logger.error(f"Failed to cleanup old monitoring data: {e}")
        raise self.retry(exc=e, countdown=300)