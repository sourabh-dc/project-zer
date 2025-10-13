# services/entry/celeryconfig.py
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
    'entry.process_entry_created': {'queue': 'entry_events'},
    'entry.process_entry_updated': {'queue': 'entry_events'},
    'entry.process_entry_deleted': {'queue': 'entry_events'},
    'entry.process_entry_validation': {'queue': 'entry_events'},
    'entry.process_entry_approval': {'queue': 'entry_events'},
    'entry.process_entry_workflow': {'queue': 'entry_events'},
    'entry.process_entry_notification': {'queue': 'entry_events'},
    'entry.process_entry_audit': {'queue': 'entry_events'},
    'entry.cleanup_old_entries': {'queue': 'entry_maintenance'},
    'entry.cleanup_old_audit_logs': {'queue': 'entry_maintenance'},
    'entry.publish_outbox_events': {'queue': 'entry_outbox'},
}

# Beat Schedule
beat_schedule = {
    'publish-outbox': {
        'task': 'entry.publish_outbox_events',
        'schedule': 30.0,
    },
    'cleanup-entries': {
        'task': 'entry.cleanup_old_entries',
        'schedule': 86400.0,  # Daily
    },
    'cleanup-audit': {
        'task': 'entry.cleanup_old_audit_logs',
        'schedule': 86400.0,  # Daily
    },
    'process-entry-validation': {
        'task': 'entry.process_entry_validation',
        'schedule': 300.0,  # Every 5 minutes
    },
    'process-entry-workflow': {
        'task': 'entry.process_entry_workflow',
        'schedule': 600.0,  # Every 10 minutes
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

