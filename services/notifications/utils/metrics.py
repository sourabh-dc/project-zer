# Prometheus metrics
from prometheus_client import Histogram, Counter, Gauge

notification_operations_total = Counter('notification_operations_total', 'Total notification operations', ['operation', 'status'])
notification_failures_total = Counter('notification_failures_total', 'Total notification failures', ['operation', 'error_type'])
notification_request_duration = Histogram('notification_request_duration_seconds', 'Notification request duration', ['operation'])
notification_queue_size = Gauge('notification_queue_size', 'Current notification queue size')
saga_duration = Histogram('saga_duration_seconds', 'Saga duration', ['saga_type'])