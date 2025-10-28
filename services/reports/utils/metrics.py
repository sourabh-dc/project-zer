# Prometheus metrics
from prometheus_client import Counter, Histogram

report_requests_total = Counter('report_requests_total', 'Total report requests', ['report_type', 'status'])
report_request_duration = Histogram('report_request_duration_seconds', 'Report request duration', ['report_type'])
report_generation_duration = Histogram('report_generation_duration_seconds', 'Report generation duration', ['report_type'])
report_cache_hits = None
active_report_sessions = None