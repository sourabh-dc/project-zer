import logging

from zeroque_common.observability import get_metrics

logger = logging.getLogger(__name__)

def record_provisioning_metric(operation: str, status: str, tenant_id: str = None):
    """Record custom provisioning metrics"""
    try:
        metrics = get_metrics()
        metrics.counter(
            "provisioning_operations_total",
            labels={"operation": operation, "status": status, "tenant_id": tenant_id or "unknown"}
        ).inc()
    except Exception as e:
        logger.error(f"Error recording provisioning metric: {e}")

def record_subscription_limit_check(tenant_id: str, operation: str, allowed: bool):
    """Record subscription limit check metrics"""
    try:
        metrics = get_metrics()
        metrics.counter(
            "subscription_limit_checks_total",
            labels={"tenant_id": tenant_id, "operation": operation, "allowed": str(allowed)}
        ).inc()
    except Exception as e:
        logger.error(f"Error recording subscription limit metric: {e}")

def record_database_operation(operation: str, table: str, status: str, duration_ms: float):
    """Record database operation metrics"""
    try:
        metrics = get_metrics()
        metrics.histogram(
            "database_operations_duration_seconds",
            labels={"operation": operation, "table": table, "status": status}
        ).observe(duration_ms / 1000.0)
    except Exception as e:
        logger.error(f"Error recording database operation metric: {e}")