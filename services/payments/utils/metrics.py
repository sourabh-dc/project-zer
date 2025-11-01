# =============================================================================
# PROMETHEUS METRICS
# =============================================================================
from prometheus_client import Counter, Histogram

# Payment metrics
payment_requests_total = Counter(
    'payment_requests_total',
    'Total payment requests',
    ['provider', 'status', 'currency']
)

payment_amount_total = Counter(
    'payment_amount_total',
    'Total payment amounts',
    ['provider', 'currency']
)

payment_duration_seconds = Histogram(
    'payment_duration_seconds',
    'Payment processing duration',
    ['provider', 'operation']
)

webhook_requests_total = Counter(
    'webhook_requests_total',
    'Total webhook requests',
    ['provider', 'event_type', 'status']
)

# Use unique metric name to avoid duplicate registration across services
saga_duration_seconds = Histogram(
    'payments_saga_duration_seconds',
    'Saga processing duration',
    ['saga_type', 'status']
)