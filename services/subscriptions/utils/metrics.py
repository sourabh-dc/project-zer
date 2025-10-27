# Metrics
from prometheus_client import Counter, Histogram

sub_requests_total = Counter('sub_requests_total', 'Requests', ['endpoint', 'status'])
sub_request_duration = Histogram('sub_request_duration_seconds', 'Duration', ['endpoint'])
saga_total = Counter('sub_saga_total', 'Sagas', ['type', 'status'])
saga_duration = Histogram('sub_saga_duration_seconds', 'Saga duration', ['type'])
