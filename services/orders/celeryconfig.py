# services/orders/celeryconfig.py
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
    'orders.process_order_created': {'queue': 'orders_events'},
    'orders.process_order_updated': {'queue': 'orders_events'},
    'orders.process_order_cancelled': {'queue': 'orders_events'},
    'orders.process_order_completed': {'queue': 'orders_events'},
    'orders.process_order_fulfillment': {'queue': 'orders_events'},
    'orders.process_order_payment': {'queue': 'orders_events'},
    'orders.process_order_shipping': {'queue': 'orders_events'},
    'orders.process_order_refund': {'queue': 'orders_events'},
    'orders.cleanup_old_orders': {'queue': 'orders_maintenance'},
    'orders.cleanup_old_audit_logs': {'queue': 'orders_maintenance'},
    'orders.publish_outbox_events': {'queue': 'orders_outbox'},
}

# Beat Schedule
beat_schedule = {
    'publish-outbox': {
        'task': 'orders.publish_outbox_events',
        'schedule': 30.0,
    },
    'cleanup-orders': {
        'task': 'orders.cleanup_old_orders',
        'schedule': 86400.0,  # Daily
    },
    'cleanup-audit': {
        'task': 'orders.cleanup_old_audit_logs',
        'schedule': 86400.0,  # Daily
    },
    'process-fulfillment': {
        'task': 'orders.process_order_fulfillment',
        'schedule': 300.0,  # Every 5 minutes
    },
    'process-shipping': {
        'task': 'orders.process_order_shipping',
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




