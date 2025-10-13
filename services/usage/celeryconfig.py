# services/usage/celeryconfig.py
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
    'usage.process_usage_recorded': {'queue': 'usage_events'},
    'usage.process_usage_aggregation': {'queue': 'usage_events'},
    'usage.process_usage_billing': {'queue': 'usage_events'},
    'usage.process_usage_analytics': {'queue': 'usage_events'},
    'usage.process_usage_reporting': {'queue': 'usage_events'},
    'usage.process_usage_optimization': {'queue': 'usage_events'},
    'usage.process_usage_alerts': {'queue': 'usage_events'},
    'usage.process_usage_compliance': {'queue': 'usage_events'},
    'usage.cleanup_old_usage': {'queue': 'usage_maintenance'},
    'usage.cleanup_old_audit_logs': {'queue': 'usage_maintenance'},
    'usage.publish_outbox_events': {'queue': 'usage_outbox'},
}

# Beat Schedule
beat_schedule = {
    'publish-outbox': {
        'task': 'usage.publish_outbox_events',
        'schedule': 30.0,
    },
    'cleanup-usage': {
        'task': 'usage.cleanup_old_usage',
        'schedule': 86400.0,  # Daily
    },
    'cleanup-audit': {
        'task': 'usage.cleanup_old_audit_logs',
        'schedule': 86400.0,  # Daily
    },
    'process-usage-aggregation': {
        'task': 'usage.process_usage_aggregation',
        'schedule': 300.0,  # Every 5 minutes
    },
    'process-usage-analytics': {
        'task': 'usage.process_usage_analytics',
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

