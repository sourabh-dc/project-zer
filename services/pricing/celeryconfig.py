# services/pricing/celeryconfig.py
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
    'pricing.process_price_calculation': {'queue': 'pricing_events'},
    'pricing.process_discount_application': {'queue': 'pricing_events'},
    'pricing.process_tax_calculation': {'queue': 'pricing_events'},
    'pricing.process_promotion': {'queue': 'pricing_events'},
    'pricing.process_price_update': {'queue': 'pricing_events'},
    'pricing.process_market_analysis': {'queue': 'pricing_events'},
    'pricing.process_competitor_pricing': {'queue': 'pricing_events'},
    'pricing.process_dynamic_pricing': {'queue': 'pricing_events'},
    'pricing.cleanup_old_prices': {'queue': 'pricing_maintenance'},
    'pricing.cleanup_old_audit_logs': {'queue': 'pricing_maintenance'},
    'pricing.publish_outbox_events': {'queue': 'pricing_outbox'},
}

# Beat Schedule
beat_schedule = {
    'publish-outbox': {
        'task': 'pricing.publish_outbox_events',
        'schedule': 30.0,
    },
    'cleanup-prices': {
        'task': 'pricing.cleanup_old_prices',
        'schedule': 86400.0,  # Daily
    },
    'cleanup-audit': {
        'task': 'pricing.cleanup_old_audit_logs',
        'schedule': 86400.0,  # Daily
    },
    'process-market-analysis': {
        'task': 'pricing.process_market_analysis',
        'schedule': 3600.0,  # Hourly
    },
    'process-dynamic-pricing': {
        'task': 'pricing.process_dynamic_pricing',
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

