from prometheus_client import Counter, Histogram, Gauge

usage_events_recorded = Counter('usage_events_recorded_total', 'Total usage events recorded', ['tenant_id', 'meter_code'])
usage_event_duration = Histogram('usage_event_duration_seconds', 'Usage event processing duration', ['operation'])
active_meters = Gauge('active_meters_total', 'Total active meters', ['tenant_id'])
saga_total = Counter('sub_saga_total', 'Sagas', ['type', 'status'])
saga_duration = Histogram('sub_saga_duration_seconds', 'Saga duration', ['type'])