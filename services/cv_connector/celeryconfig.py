# services/cv_connector/celeryconfig.py
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
    'cv_connector.process_cv_data': {'queue': 'cv_connector_events'},
    'cv_connector.process_cv_analysis': {'queue': 'cv_connector_events'},
    'cv_connector.process_cv_validation': {'queue': 'cv_connector_events'},
    'cv_connector.process_cv_extraction': {'queue': 'cv_connector_events'},
    'cv_connector.process_cv_matching': {'queue': 'cv_connector_events'},
    'cv_connector.process_cv_scoring': {'queue': 'cv_connector_events'},
    'cv_connector.process_cv_reporting': {'queue': 'cv_connector_events'},
    'cv_connector.process_cv_notification': {'queue': 'cv_connector_events'},
    'cv_connector.cleanup_old_cv_data': {'queue': 'cv_connector_maintenance'},
    'cv_connector.cleanup_old_audit_logs': {'queue': 'cv_connector_maintenance'},
    'cv_connector.publish_outbox_events': {'queue': 'cv_connector_outbox'},
}

# Beat Schedule
beat_schedule = {
    'publish-outbox': {
        'task': 'cv_connector.publish_outbox_events',
        'schedule': 30.0,
    },
    'cleanup-cv-data': {
        'task': 'cv_connector.cleanup_old_cv_data',
        'schedule': 86400.0,  # Daily
    },
    'cleanup-audit': {
        'task': 'cv_connector.cleanup_old_audit_logs',
        'schedule': 86400.0,  # Daily
    },
    'process-cv-analysis': {
        'task': 'cv_connector.process_cv_analysis',
        'schedule': 300.0,  # Every 5 minutes
    },
    'process-cv-matching': {
        'task': 'cv_connector.process_cv_matching',
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

