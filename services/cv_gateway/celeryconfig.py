# services/cv_gateway/celeryconfig.py
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
    'cv_gateway.process_cv_request': {'queue': 'cv_gateway_events'},
    'cv_gateway.process_cv_response': {'queue': 'cv_gateway_events'},
    'cv_gateway.process_cv_routing': {'queue': 'cv_gateway_events'},
    'cv_gateway.process_cv_load_balancing': {'queue': 'cv_gateway_events'},
    'cv_gateway.process_cv_caching': {'queue': 'cv_gateway_events'},
    'cv_gateway.process_cv_monitoring': {'queue': 'cv_gateway_events'},
    'cv_gateway.process_cv_security': {'queue': 'cv_gateway_events'},
    'cv_gateway.process_cv_analytics': {'queue': 'cv_gateway_events'},
    'cv_gateway.cleanup_old_cv_logs': {'queue': 'cv_gateway_maintenance'},
    'cv_gateway.cleanup_old_audit_logs': {'queue': 'cv_gateway_maintenance'},
    'cv_gateway.publish_outbox_events': {'queue': 'cv_gateway_outbox'},
}

# Beat Schedule
beat_schedule = {
    'publish-outbox': {
        'task': 'cv_gateway.publish_outbox_events',
        'schedule': 30.0,
    },
    'cleanup-cv-logs': {
        'task': 'cv_gateway.cleanup_old_cv_logs',
        'schedule': 86400.0,  # Daily
    },
    'cleanup-audit': {
        'task': 'cv_gateway.cleanup_old_audit_logs',
        'schedule': 86400.0,  # Daily
    },
    'process-cv-monitoring': {
        'task': 'cv_gateway.process_cv_monitoring',
        'schedule': 300.0,  # Every 5 minutes
    },
    'process-cv-analytics': {
        'task': 'cv_gateway.process_cv_analytics',
        'schedule': 1800.0,  # Every 30 minutes
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




