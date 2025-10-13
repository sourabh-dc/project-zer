# services/billing/celeryconfig.py
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
    'billing.process_invoice': {'queue': 'billing_events'},
    'billing.process_payment': {'queue': 'billing_events'},
    'billing.process_settlement': {'queue': 'billing_events'},
    'billing.process_refund': {'queue': 'billing_events'},
    'billing.process_chargeback': {'queue': 'billing_events'},
    'billing.process_tax_calculation': {'queue': 'billing_events'},
    'billing.process_commission': {'queue': 'billing_events'},
    'billing.cleanup_old_invoices': {'queue': 'billing_maintenance'},
    'billing.cleanup_old_audit_logs': {'queue': 'billing_maintenance'},
    'billing.publish_outbox_events': {'queue': 'billing_outbox'},
}

# Beat Schedule
beat_schedule = {
    'publish-outbox': {
        'task': 'billing.publish_outbox_events',
        'schedule': 30.0,
    },
    'cleanup-invoices': {
        'task': 'billing.cleanup_old_invoices',
        'schedule': 86400.0,  # Daily
    },
    'cleanup-audit': {
        'task': 'billing.cleanup_old_audit_logs',
        'schedule': 86400.0,  # Daily
    },
    'process-settlements': {
        'task': 'billing.process_settlement',
        'schedule': 3600.0,  # Hourly
    },
    'process-commissions': {
        'task': 'billing.process_commission',
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

