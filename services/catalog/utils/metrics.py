from prometheus_client import Counter, Histogram


catalog_requests_total = Counter('catalog_requests_total', 'Total catalog requests', ['endpoint', 'status'])
catalog_request_duration = Histogram('catalog_request_duration_seconds', 'Catalog request duration', ['endpoint'])
catalog_operations_total = Counter('catalog_operations_total', 'Total catalog operations', ['operation', 'status'])
catalog_duration = Histogram('catalog_duration_seconds', 'Catalog operation duration', ['operation'])
saga_total = Counter('saga_total', 'Total sagas', ['type', 'status'])
saga_duration = Histogram('saga_duration_seconds', 'Saga duration', ['type'])