# services/subscriptions/celeryconfig.py
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
    'subscriptions.process_subscription_created': {'queue': 'subscriptions_events'},
    'subscriptions.process_subscription_updated': {'queue': 'subscriptions_events'},
    'subscriptions.process_subscription_cancelled': {'queue': 'subscriptions_events'},
    'subscriptions.process_subscription_renewed': {'queue': 'subscriptions_events'},
    'subscriptions.process_billing_cycle': {'queue': 'subscriptions_events'},
    'subscriptions.process_usage_tracking': {'queue': 'subscriptions_events'},
    'subscriptions.process_plan_change': {'queue': 'subscriptions_events'},
    'subscriptions.process_entitlement_check': {'queue': 'subscriptions_events'},
    'subscriptions.cleanup_old_subscriptions': {'queue': 'subscriptions_maintenance'},
    'subscriptions.cleanup_old_audit_logs': {'queue': 'subscriptions_maintenance'},
    'subscriptions.publish_outbox_events': {'queue': 'subscriptions_outbox'},
}

# Beat Schedule
beat_schedule = {
    'publish-outbox': {
        'task': 'subscriptions.publish_outbox_events',
        'schedule': 30.0,
    },
    'cleanup-subscriptions': {
        'task': 'subscriptions.cleanup_old_subscriptions',
        'schedule': 86400.0,  # Daily
    },
    'cleanup-audit': {
        'task': 'subscriptions.cleanup_old_audit_logs',
        'schedule': 86400.0,  # Daily
    },
    'process-billing-cycle': {
        'task': 'subscriptions.process_billing_cycle',
        'schedule': 3600.0,  # Hourly
    },
    'process-usage-tracking': {
        'task': 'subscriptions.process_usage_tracking',
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




