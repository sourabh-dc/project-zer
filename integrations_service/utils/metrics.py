# Metrics
from prometheus_client import Counter, Histogram

req_total = Counter('prov_requests_total', 'Total requests', ['operation', 'status'])
req_duration = Histogram('prov_duration_seconds', 'Request duration', ['operation'])