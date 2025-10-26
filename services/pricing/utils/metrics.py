# Prometheus metrics - clear registry to avoid duplicates
from prometheus_client import REGISTRY, Counter, Histogram

try:
    REGISTRY._collector_to_names.clear()
    REGISTRY._names_to_collectors.clear()
except:
    pass

pricing_operations_total = Counter('pricing_operations_total', 'Total pricing operations', ['operation', 'status'])
pricing_operation_duration = Histogram('pricing_operation_duration_seconds', 'Pricing operation duration', ['operation'])
saga_total = Counter('saga_total', 'Total sagas', ['type', 'status'])
saga_duration = Histogram('saga_duration_seconds', 'Saga duration', ['type'])