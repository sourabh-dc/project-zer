# Prometheus metrics
from prometheus_client import Counter, Histogram, Gauge

try:
    billing_requests_total = Counter('billing_requests_total', 'Total billing requests', ['endpoint', 'status'])
    billing_request_duration = Histogram('billing_request_duration_seconds', 'Billing request duration', ['endpoint'])
    settlements_processed = Counter('settlements_processed_total', 'Total settlements processed',
                                    ['tenant_id', 'status'])
    active_invoices = Gauge('active_invoices_total', 'Total active invoices', ['tenant_id'])
    billing_requests = Counter('billing_requests_total', 'Total billing requests', ['method', 'endpoint', 'status'])
    billing_requests_duration = Histogram('billing_requests_duration_seconds', 'Billing request duration')
    billing_requests_in_flight = Gauge('billing_requests_in_flight', 'Billing requests currently being processed')
    billing_saga_duration = Histogram('billing_saga_duration_seconds', 'Billing saga execution duration', ['saga_type'])
    billing_saga_failures = Counter('billing_saga_failures_total', 'Total billing saga failures', ['saga_type', 'step'])
    billing_operations_total = Counter('billing_operations_total', 'Total billing operations', ['operation', 'status'])
except ValueError:
    # Metrics already registered
    pass