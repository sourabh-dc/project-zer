# Prometheus metrics - Initialize only once to avoid duplication issues
from prometheus_client import Counter, Histogram, Gauge

_metrics_initialized = False

if not _metrics_initialized:
    _metrics_initialized = True
    entry_codes_issued = Counter('entry_codes_issued_total', 'Total entry codes issued', ['tenant_id', 'provider'])
    entry_codes_validated = Counter('entry_codes_validated_total', 'Total entry codes validated', ['tenant_id', 'status'])
    entry_code_duration = Histogram('entry_code_duration_seconds', 'Entry code operation duration', ['operation'])
    active_codes = Gauge('active_entry_codes_total', 'Total active entry codes', ['tenant_id'])
    entry_operations_total = Counter('entry_operations_total', 'Entry operations processed', ['operation', 'status'])
