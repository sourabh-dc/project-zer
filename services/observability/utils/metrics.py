# Prometheus metrics
from prometheus_client import Counter, Histogram, Gauge

observability_requests_total = Counter('observability_requests_total', 'Total observability requests', ['endpoint', 'status'])
observability_request_duration = Histogram('observability_request_duration_seconds', 'Observability request duration', ['endpoint'])
system_metrics_collected = Counter('system_metrics_collected_total', 'Total system metrics collected', ['metric_type'])
active_monitors = Gauge('active_monitors_total', 'Total active monitors', ['monitor_type'])
observability_operations_total = Counter('observability_operations_total', 'Observability operations processed', ['operation', 'status'])