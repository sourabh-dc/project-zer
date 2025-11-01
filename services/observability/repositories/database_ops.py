from services.observability.models import Metric, Monitor
from services.observability.repositories.db_config import SessionLocal


def create_custom_metric(request):
    with SessionLocal() as db:
        metric = Metric(
            metric_name=request.metric_name,
            metric_type=request.metric_type,
            value=request.value,
            labels=request.labels,
            tenant_id=request.tenant_id,
            service_name=request.service_name
        )
        db.add(metric)
        db.commit()

    return metric

def get_metrics(metric_name=None, service_name=None, limit=100):
    with SessionLocal() as db:
        query = db.query(Metric)

        if metric_name:
            query = query.filter(Metric.metric_name == metric_name)
        if service_name:
            query = query.filter(Metric.service_name == service_name)

        metrics = query.order_by(Metric.timestamp.desc()).limit(limit).all()

        return metrics

def create_monitor_db(request):
    with SessionLocal() as db:
        monitor = Monitor(
            monitor_name=request.monitor_name,
            monitor_type=request.monitor_type,
            target_service=request.target_service,
            target_endpoint=request.target_endpoint,
            check_interval_seconds=request.check_interval_seconds,
            timeout_seconds=request.timeout_seconds,
            threshold_value=request.threshold_value
        )
        db.add(monitor)
        db.commit()

    return monitor

def fetch_monitors():
    with SessionLocal() as db:
        monitors = db.query(Monitor).order_by(Monitor.created_at.desc()).all()

        return monitors