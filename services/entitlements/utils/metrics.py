# Metrics
from prometheus_client import Counter, Histogram

ent_checks_total = Counter('ent_checks_total', 'Checks', ['tenant_id', 'feature', 'result'])
ent_check_duration = Histogram('ent_check_duration_seconds', 'Duration')
usage_records_total = Counter('usage_records_total', 'Usage records', ['tenant_id', 'feature'])
saga_total = Counter('ent_saga_total', 'Sagas', ['type', 'status'])
saga_duration = Histogram('ent_saga_duration_seconds', 'Saga duration')