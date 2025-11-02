# =============================================================================
# PROMETHEUS METRICS
# =============================================================================
from prometheus_client import Counter, Histogram

# Metrics for Ledger Service
ledger_requests_total = Counter(
    'ledger_requests_total_v2',
    'Total ledger requests',
    ['method', 'endpoint', 'status']
)

ledger_request_duration = Histogram(
    'ledger_request_duration_seconds_v2',
    'Ledger request duration',
    ['method', 'endpoint']
)

ledger_entries_created_total = Counter(
    'ledger_entries_created_total_v2',
    'Total ledger entries created',
    ['entry_type', 'account', 'currency']
)

ledger_saga_duration = Histogram(
    'ledger_saga_duration_seconds_v2',
    'Ledger saga execution duration',
    ['saga_type']
)

ledger_saga_failures = Counter(
    'ledger_saga_failures_total_v2',
    'Total ledger saga failures',
    ['saga_type', 'step']
)

# Idempotency metrics
ledger_idempotency_requests_total = Counter(
    'ledger_idempotency_requests_total_v2',
    'Total idempotency requests',
    ['operation', 'status']  # cached, new, conflict
)

ledger_idempotency_cache_hits = Counter(
    'ledger_idempotency_cache_hits_total_v2',
    'Total idempotency cache hits',
    ['operation']
)

ledger_idempotency_cleanup_total = Counter(
    'ledger_idempotency_cleanup_total_v2',
    'Total idempotency records cleaned up'
)

# Daily rollup metrics
ledger_daily_rollups_total = Counter(
    'ledger_daily_rollups_total_v2',
    'Total daily rollups generated',
    ['rollup_type', 'status']
)

ledger_financial_reports_total = Counter(
    'ledger_financial_reports_total_v2',
    'Total financial reports generated',
    ['report_type', 'status']
)

# Usage metering metrics
ledger_usage_events_total = Counter(
    'ledger_usage_events_total_v2',
    'Total usage events generated',
    ['meter_code', 'status']
)

ledger_usage_processing_total = Counter(
    'ledger_usage_processing_total_v2',
    'Total usage processing operations',
    ['status']
)
