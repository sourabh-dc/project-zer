from services.monitoring.repositories.db_config import SessionLocal
from services.monitoring.models import ServiceHealth, Alert


def get_latest_service_health(service_name: str):
    """Retrieve the latest health check record for a given service"""
    with SessionLocal() as db:
        latest_health = db.query(ServiceHealth).filter(
            ServiceHealth.service_name == service_name
        ).order_by(ServiceHealth.last_check.desc()).first()

        return latest_health

def fetch_services():
    """Fetch all distinct monitored services"""
    with SessionLocal() as db:
        services = db.query(ServiceHealth).distinct(ServiceHealth.service_name).all()

        return services

def create_alert_db(request):
    with SessionLocal() as db:
        alert = Alert(
            service_name=request.service_name,
            alert_type=request.alert_type,
            severity=request.severity,
            message=request.message,
            metadata=request.metadata
        )
        db.add(alert)
        db.commit()
        return alert

def fetch_alerts(service_name: str = None, severity: str = None, status: str = "active"):
    with SessionLocal() as db:
        query = db.query(Alert).filter(Alert.status == status)

        if service_name:
            query = query.filter(Alert.service_name == service_name)
        if severity:
            query = query.filter(Alert.severity == severity)

        alerts = query.order_by(Alert.created_at.desc()).limit(100).all()
        return alerts