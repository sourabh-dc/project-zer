from prometheus_client import Counter, Histogram

req_total = Counter('prov_requests_total', 'Requests', ['op', 'status'])
req_duration = Histogram('prov_duration_seconds', 'Duration', ['op'])
saga_total = Counter('prov_saga_total', 'Sagas', ['type', 'status'])
saga_duration = Histogram('prov_saga_duration_seconds', 'Saga duration', ['type'])