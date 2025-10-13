# services/service_registry/celeryconfig.py
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
    'service_registry.process_service_registration': {'queue': 'service_registry_events'},
    'service_registry.process_service_discovery': {'queue': 'service_registry_events'},
    'service_registry.process_service_health_check': {'queue': 'service_registry_events'},
    'service_registry.process_service_load_balancing': {'queue': 'service_registry_events'},
    'service_registry.process_service_routing': {'queue': 'service_registry_events'},
    'service_registry.process_service_monitoring': {'queue': 'service_registry_events'},
    'service_registry.process_service_security': {'queue': 'service_registry_events'},
    'service_registry.process_service_analytics': {'queue': 'service_registry_events'},
    'service_registry.cleanup_old_services': {'queue': 'service_registry_maintenance'},
    'service_registry.cleanup_old_audit_logs': {'queue': 'service_registry_maintenance'},
    'service_registry.publish_outbox_events': {'queue': 'service_registry_outbox'},
}

# Beat Schedule
beat_schedule = {
    'publish-outbox': {
        'task': 'service_registry.publish_outbox_events',
        'schedule': 30.0,
    },
    'cleanup-services': {
        'task': 'service_registry.cleanup_old_services',
        'schedule': 86400.0,  # Daily
    },
    'cleanup-audit': {
        'task': 'service_registry.cleanup_old_audit_logs',
        'schedule': 86400.0,  # Daily
    },
    'process-health-check': {
        'task': 'service_registry.process_service_health_check',
        'schedule': 60.0,  # Every minute
    },
    'process-service-monitoring': {
        'task': 'service_registry.process_service_monitoring',
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

