# services/observability/celeryconfig.py
import os

# Celery Configuration
broker_url = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672//")
result_backend = os.getenv("REDIS_URL", "redis://localhost:6379/0")
task_serializer = 'json'
result_serializer = 'json'
accept_content = ['json']
timezone = 'UTC'
enable_utc = True

# Task Routes
task_routes = {
    'observability.process_trace_collection': {'queue': 'observability_events'},
    'observability.process_span_analysis': {'queue': 'observability_events'},
    'observability.process_dependency_mapping': {'queue': 'observability_events'},
    'observability.process_performance_profiling': {'queue': 'observability_events'},
    'observability.process_error_tracking': {'queue': 'observability_events'},
    'observability.process_user_behavior': {'queue': 'observability_events'},
    'observability.process_system_health': {'queue': 'observability_events'},
    'observability.process_anomaly_detection': {'queue': 'observability_events'},
    'observability.cleanup_old_traces': {'queue': 'observability_maintenance'},
    'observability.cleanup_old_audit_logs': {'queue': 'observability_maintenance'},
    'observability.publish_outbox_events': {'queue': 'observability_outbox'},
}

# Beat Schedule
beat_schedule = {
    'publish-outbox': {
        'task': 'observability.publish_outbox_events',
        'schedule': 30.0,
    },
    'cleanup-traces': {
        'task': 'observability.cleanup_old_traces',
        'schedule': 86400.0,  # Daily
    },
    'cleanup-audit': {
        'task': 'observability.cleanup_old_audit_logs',
        'schedule': 86400.0,  # Daily
    },
    'process-trace-collection': {
        'task': 'observability.process_trace_collection',
        'schedule': 30.0,  # Every 30 seconds
    },
    'process-anomaly-detection': {
        'task': 'observability.process_anomaly_detection',
        'schedule': 300.0,  # Every 5 minutes
    },
}

# Worker Configuration
worker_prefetch_multiplier = 4
worker_max_tasks_per_child = 1000
task_acks_late = True
task_reject_on_worker_lost = True
task_time_limit = 300
task_soft_time_limit = 240
worker_concurrency = 4

# Task Execution
task_always_eager = False
task_eager_propagates = True
task_ignore_result = False
task_store_eager_result = True

# Result Backend
result_expires = 3600
result_persistent = True
result_compression = 'gzip'

# Security
worker_hijack_root_logger = False
worker_log_color = False

