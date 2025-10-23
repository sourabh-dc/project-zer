# services/notifications/celeryconfig.py
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
    'notifications.process_email': {'queue': 'notifications_events'},
    'notifications.process_sms': {'queue': 'notifications_events'},
    'notifications.process_push': {'queue': 'notifications_events'},
    'notifications.process_in_app': {'queue': 'notifications_events'},
    'notifications.process_webhook': {'queue': 'notifications_events'},
    'notifications.process_template': {'queue': 'notifications_events'},
    'notifications.process_delivery_status': {'queue': 'notifications_events'},
    'notifications.process_bounce_handling': {'queue': 'notifications_events'},
    'notifications.cleanup_old_notifications': {'queue': 'notifications_maintenance'},
    'notifications.cleanup_old_audit_logs': {'queue': 'notifications_maintenance'},
    'notifications.publish_outbox_events': {'queue': 'notifications_outbox'},
}

# Beat Schedule
beat_schedule = {
    'publish-outbox': {
        'task': 'notifications.publish_outbox_events',
        'schedule': 30.0,
    },
    'cleanup-notifications': {
        'task': 'notifications.cleanup_old_notifications',
        'schedule': 86400.0,  # Daily
    },
    'cleanup-audit': {
        'task': 'notifications.cleanup_old_audit_logs',
        'schedule': 86400.0,  # Daily
    },
    'process-delivery-status': {
        'task': 'notifications.process_delivery_status',
        'schedule': 300.0,  # Every 5 minutes
    },
    'process-bounce-handling': {
        'task': 'notifications.process_bounce_handling',
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




