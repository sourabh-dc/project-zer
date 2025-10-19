# services/catalog/celeryconfig.py
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
    'catalog.process_product_created': {'queue': 'catalog_events'},
    'catalog.process_product_updated': {'queue': 'catalog_events'},
    'catalog.process_product_deleted': {'queue': 'catalog_events'},
    'catalog.process_category_management': {'queue': 'catalog_events'},
    'catalog.process_inventory_update': {'queue': 'catalog_events'},
    'catalog.process_search_indexing': {'queue': 'catalog_events'},
    'catalog.process_recommendation': {'queue': 'catalog_events'},
    'catalog.process_content_management': {'queue': 'catalog_events'},
    'catalog.cleanup_old_products': {'queue': 'catalog_maintenance'},
    'catalog.cleanup_old_audit_logs': {'queue': 'catalog_maintenance'},
    'catalog.publish_outbox_events': {'queue': 'catalog_outbox'},
}

# Beat Schedule
beat_schedule = {
    'publish-outbox': {
        'task': 'catalog.publish_outbox_events',
        'schedule': 30.0,
    },
    'cleanup-products': {
        'task': 'catalog.cleanup_old_products',
        'schedule': 86400.0,  # Daily
    },
    'cleanup-audit': {
        'task': 'catalog.cleanup_old_audit_logs',
        'schedule': 86400.0,  # Daily
    },
    'process-search-indexing': {
        'task': 'catalog.process_search_indexing',
        'schedule': 1800.0,  # Every 30 minutes
    },
    'process-recommendations': {
        'task': 'catalog.process_recommendation',
        'schedule': 3600.0,  # Hourly
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

