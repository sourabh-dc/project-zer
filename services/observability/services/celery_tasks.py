# =============================================================================
# CELERY TASKS
# =============================================================================
from datetime import datetime, timezone, timedelta
import time
from sqlalchemy import text
import httpx
from typing import Dict, Any

from services.observability.core.celery_config import celery_app
from services.observability.repositories.db_config import SessionLocal, set_rls_context
from services.observability.models import Monitor, Metric
from services.observability.utils.observability_logger import logger
from ..schemas import SystemMetrics
from ..utils.metrics import active_monitors, system_metrics_collected, observability_operations_total


SERVICE_NAME = "observability"

@celery_app.task(bind=True, max_retries=3)
def collect_system_metrics(self):
    """Collect system metrics"""
    try:
        import psutil

        # Collect system metrics
        cpu_percent = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        network = psutil.net_io_counters()

        metrics_data = {
            "cpu_usage_percent": cpu_percent,
            "memory_usage_percent": memory.percent,
            "disk_usage_percent": (disk.used / disk.total) * 100,
            "network_bytes_sent": network.bytes_sent,
            "network_bytes_received": network.bytes_recv,
            "timestamp": datetime.now(timezone.utc)
        }

        # Store metrics in database
        with SessionLocal() as db:
            for metric_name, value in metrics_data.items():
                if metric_name != "timestamp":
                    metric = Metric(
                        metric_name=metric_name,
                        metric_type="gauge",
                        value=value,
                        labels={"source": "system"},
                        service_name=SERVICE_NAME
                    )
                    db.add(metric)
            db.commit()

        # Update Prometheus metrics
        system_metrics_collected.labels(metric_type="system").inc()

        logger.info("System metrics collected", **metrics_data)
        return metrics_data

    except Exception as e:
        logger.error("Failed to collect system metrics", error=str(e))

        # Retry if not exceeded max retries
        if self.request.retries < self.max_retries:
            raise self.retry(countdown=60 * (2 ** self.request.retries))

        return {"error": str(e)}


@celery_app.task(bind=True, max_retries=3)
def run_monitor_check(self, monitor_id: str):
    """Run a specific monitor check"""
    try:
        with SessionLocal() as db:
            monitor = db.query(Monitor).filter(Monitor.id == monitor_id).first()
            if not monitor:
                logger.error("Monitor not found", monitor_id=monitor_id)
                return {"error": "Monitor not found"}

            if not monitor.is_active:
                logger.info("Monitor is inactive", monitor_id=monitor_id)
                return {"status": "inactive"}

            # Perform health check
            start_time = time.time()
            try:
                with httpx.Client(timeout=monitor.timeout_seconds) as client:
                    response = client.get(monitor.target_endpoint)

                response_time = time.time() - start_time
                status = "healthy" if response.status_code == 200 else "unhealthy"

                # Store result
                monitor.last_check = datetime.now(timezone.utc)
                monitor.last_status = status
                db.commit()

                # Update metrics
                active_monitors.labels(monitor_type=monitor.monitor_type).set(1)

                logger.info("Monitor check completed",
                            monitor_id=monitor_id, status=status, response_time=response_time)

                return {
                    "monitor_id": monitor_id,
                    "status": status,
                    "response_time": response_time,
                    "response_code": response.status_code
                }

            except Exception as e:
                monitor.last_check = datetime.now(timezone.utc)
                monitor.last_status = "error"
                db.commit()

                logger.error("Monitor check failed", monitor_id=monitor_id, error=str(e))

                # Retry if not exceeded max retries
                if self.request.retries < self.max_retries:
                    raise self.retry(countdown=60 * (2 ** self.request.retries))

                return {"status": "error", "error": str(e)}

    except Exception as e:
        logger.error("Failed to run monitor check", monitor_id=monitor_id, error=str(e))
        return {"error": str(e)}


@celery_app.task
def cleanup_old_metrics():
    """Clean up old metrics"""
    try:
        with SessionLocal() as db:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=30)
            deleted = db.execute(
                text("DELETE FROM metrics_new WHERE timestamp < :cutoff"),
                {"cutoff": cutoff_date}
            )
            db.commit()

        logger.info("Cleaned up old metrics", deleted_count=deleted.rowcount)
        return {"deleted_count": deleted.rowcount}

    except Exception as e:
        logger.error("Failed to cleanup metrics", error=str(e))
        return {"error": str(e)}


@celery_app.task(bind=True, max_retries=3)
def collect_system_metrics(self):
    """Collect system metrics asynchronously"""
    try:
        import psutil

        # Collect system metrics
        cpu_percent = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        network = psutil.net_io_counters()

        # Store metrics in database
        with SessionLocal() as db:
            metrics = SystemMetrics(
                cpu_usage_percent=cpu_percent,
                memory_usage_percent=memory.percent,
                disk_usage_percent=(disk.used / disk.total) * 100,
                network_bytes_sent=network.bytes_sent,
                network_bytes_received=network.bytes_recv,
                timestamp=datetime.now(timezone.utc)
            )

            db.add(metrics)
            db.commit()

            # Update metrics
            observability_operations_total.labels(operation="metrics_collection", status="success").inc()

            logger.info(f"System metrics collected successfully")

    except Exception as e:
        logger.error(f"Failed to collect system metrics: {e}")
        observability_operations_total.labels(operation="metrics_collection", status="failed").inc()
        raise self.retry(exc=e, countdown=60)


@celery_app.task(bind=True, max_retries=3)
def process_log_aggregation(self, tenant_id: str, log_data: Dict[str, Any]):
    """Process log aggregation asynchronously"""
    try:
        with SessionLocal() as db:
            # Set RLS context
            set_rls_context(db, tenant_id)

            # Process log aggregation logic here
            logger.info(f"Processing log aggregation for tenant {tenant_id}")

            # Update metrics
            observability_operations_total.labels(operation="log_aggregation", status="success").inc()

    except Exception as e:
        logger.error(f"Failed to process log aggregation for tenant {tenant_id}: {e}")
        observability_operations_total.labels(operation="log_aggregation", status="failed").inc()
        raise self.retry(exc=e, countdown=60)


@celery_app.task(bind=True, max_retries=3)
def cleanup_old_observability_data(self):
    """Clean up old observability data"""
    try:
        with SessionLocal() as db:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=30)

            # Clean up old system metrics
            metrics_result = db.execute(text("""
                                             DELETE
                                             FROM system_metrics_new
                                             WHERE timestamp < :cutoff_date
                                             """), {"cutoff_date": cutoff_date})

            # Clean up old log entries
            log_result = db.execute(text("""
                                         DELETE
                                         FROM log_entries_new
                                         WHERE timestamp < :cutoff_date
                                         """), {"cutoff_date": cutoff_date})

            db.commit()

            logger.info(
                f"Cleaned up {metrics_result.rowcount} old system metrics and {log_result.rowcount} old log entries")

    except Exception as e:
        logger.error(f"Failed to cleanup old observability data: {e}")
        raise self.retry(exc=e, countdown=300)