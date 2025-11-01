# Prometheus metrics
from prometheus_client import Counter, Gauge, Histogram

monitoring_checks_total = Counter('monitoring_checks_total', 'Total monitoring checks', ['service', 'status'])
monitoring_check_duration = Histogram('monitoring_check_duration_seconds', 'Monitoring check duration', ['service'])
service_health_status = Gauge('service_health_status', 'Service health status', ['service'])
active_alerts = Gauge('active_alerts_total', 'Total active alerts', ['severity'])
monitoring_operations_total = Counter('monitoring_operations_total', 'Total monitoring operations', ['operation', 'status'])