from prometheus_client import Counter, Histogram

orders_operations_total = Counter('orders_operations_total', 'Total orders operations', ['operation', 'status'])
orders_requests_total = Counter('orders_requests_total', 'Total orders requests', ['endpoint', 'status'])
orders_request_duration = Histogram('orders_request_duration_seconds', 'Orders request duration', ['endpoint'])
orders_total = Counter('orders_total', 'Total orders', ['status'])
orders_duration = Histogram('orders_duration_seconds', 'Order processing duration', ['status'])
saga_total = Counter('saga_total', 'Total sagas', ['type', 'status'])
saga_duration = Histogram('saga_duration_seconds', 'Saga duration', ['type'])

# Prometheus metrics - Clear registry to avoid duplicates
from prometheus_client import REGISTRY
try:
    REGISTRY._collector_to_names.clear()
    REGISTRY._names_to_collectors.clear()

except:
    pass