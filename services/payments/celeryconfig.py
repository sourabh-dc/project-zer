# services/payments/celeryconfig.py
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
    'payments.process_payment': {'queue': 'payments_events'},
    'payments.process_refund': {'queue': 'payments_events'},
    'payments.process_chargeback': {'queue': 'payments_events'},
    'payments.process_settlement': {'queue': 'payments_events'},
    'payments.process_dispute': {'queue': 'payments_events'},
    'payments.process_fraud_check': {'queue': 'payments_events'},
    'payments.process_3ds_verification': {'queue': 'payments_events'},
    'payments.process_wallet_transaction': {'queue': 'payments_events'},
    'payments.cleanup_old_payments': {'queue': 'payments_maintenance'},
    'payments.cleanup_old_audit_logs': {'queue': 'payments_maintenance'},
    'payments.publish_outbox_events': {'queue': 'payments_outbox'},
}

# Beat Schedule
beat_schedule = {
    'publish-outbox': {
        'task': 'payments.publish_outbox_events',
        'schedule': 30.0,
    },
    'cleanup-payments': {
        'task': 'payments.cleanup_old_payments',
        'schedule': 86400.0,  # Daily
    },
    'cleanup-audit': {
        'task': 'payments.cleanup_old_audit_logs',
        'schedule': 86400.0,  # Daily
    },
    'process-settlements': {
        'task': 'payments.process_settlement',
        'schedule': 3600.0,  # Hourly
    },
    'process-fraud-checks': {
        'task': 'payments.process_fraud_check',
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




