from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

from services.observability.repositories.database_ops import create_custom_metric, get_metrics, create_monitor_db, \
    fetch_monitors
from services.observability.schemas import MetricRequest, MonitorRequest, SystemMetrics
from services.observability.utils.metrics import observability_requests_total, active_monitors
from services.observability.utils.observability_logger import logger


async def create_metric(request: MetricRequest):
    """Record a custom metric"""
    try:
        metric = create_custom_metric(request)

        # Update Prometheus metrics
        observability_requests_total.labels(endpoint="record_metric", status="success").inc()

        logger.info("Metric recorded", metric_name=request.metric_name, value=request.value)

        return {
            "metric_id": metric.id,
            "status": "recorded"
        }

    except Exception as e:
        logger.error("Failed to record metric", error=str(e))
        observability_requests_total.labels(endpoint="record_metric", status="error").inc()
        raise HTTPException(status_code=500, detail=str(e))

async def fetch_metrics(metric_name: Optional[str], service_name: Optional[str], limit: int):
    """Get metrics with optional filtering"""
    try:
        metrics = get_metrics(metric_name, service_name, limit)

        return [
            {
                "id": metric.id,
                "metric_name": metric.metric_name,
                "metric_type": metric.metric_type,
                "value": float(metric.value),
                "labels": metric.labels,
                "timestamp": metric.timestamp,
                "tenant_id": metric.tenant_id,
                "service_name": metric.service_name
            }
            for metric in metrics
        ]

    except Exception as e:
        logger.error("Failed to get metrics", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


async def create_monitor(request: MonitorRequest):
    """Create a new monitor"""
    try:
        monitor = create_monitor_db(request)

        # Update metrics
        active_monitors.labels(monitor_type=request.monitor_type).inc()

        logger.info("Monitor created",
                    monitor_name=request.monitor_name, monitor_type=request.monitor_type)

        return {
            "monitor_id": monitor.id,
            "status": "created"
        }

    except Exception as e:
        logger.error("Failed to create monitor", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


async def get_monitors():
    """List all monitors"""
    try:
        monitors = fetch_monitors()
        return [
        {
            "id": monitor.id,
            "monitor_name": monitor.monitor_name,
            "monitor_type": monitor.monitor_type,
            "target_service": monitor.target_service,
            "target_endpoint": monitor.target_endpoint,
            "is_active": monitor.is_active,
            "last_check": monitor.last_check,
            "last_status": monitor.last_status,
            "created_at": monitor.created_at
        }
        for monitor in monitors
    ]

    except Exception as e:
        logger.error("Failed to list monitors", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

async def get_system_metrics():
    """Get current system metrics"""
    try:
        import psutil

        # Get current system metrics
        cpu_percent = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        network = psutil.net_io_counters()

        return SystemMetrics(
            cpu_usage_percent=cpu_percent,
            memory_usage_percent=memory.percent,
            disk_usage_percent=(disk.used / disk.total) * 100,
            network_bytes_sent=network.bytes_sent,
            network_bytes_received=network.bytes_recv,
            timestamp=datetime.now(timezone.utc)
        )

    except Exception as e:
        logger.error("Failed to get system metrics", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))