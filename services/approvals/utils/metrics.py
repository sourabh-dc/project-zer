# Clear registry to avoid duplicate metrics on reload
from prometheus_client import REGISTRY, Counter, Histogram, Gauge

try:
    REGISTRY.clear()
except:
    pass
# Prometheus metrics
approval_requests_total = Counter('approval_requests_total', 'Total approval requests', ['operation', 'status'])
approval_request_duration = Histogram('approval_request_duration_seconds', 'Approval request duration', ['operation'])
active_approvals = Gauge('active_approvals_total', 'Total active approvals', ['tenant_id'])
# Prometheus Metrics
REQUEST_COUNT = Counter(
    'approvals_requests_total',
    'Total number of requests',
    ['method', 'endpoint', 'status_code']
)

REQUEST_DURATION = Histogram(
    'approvals_request_duration_seconds',
    'Request duration in seconds',
    ['method', 'endpoint']
)

ACTIVE_CONNECTIONS = Gauge(
    'approvals_active_connections',
    'Number of active connections'
)

APPROVAL_REQUESTS_CREATED_V2 = Counter(
    'approvals_v2_requests_created_total',
    'Total number of approval requests created',
    ['request_type', 'status']
)

APPROVAL_REQUESTS_RESOLVED_V2 = Counter(
    'approvals_v2_requests_resolved_total',
    'Total number of approval requests resolved',
    ['request_type', 'resolution']
)

EVENTS_PUBLISHED = Counter(
    'approvals_events_published_total',
    'Total number of events published',
    ['event_type', 'status']
)

CACHE_HITS = Counter(
    'approvals_cache_hits_total',
    'Total number of cache hits',
    ['cache_type']
)

CACHE_MISSES = Counter(
    'approvals_cache_misses_total',
    'Total number of cache misses',
    ['cache_type']
)