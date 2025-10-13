# services/monitoring/celeryconfig.py
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
    'monitoring.process_metrics_collection': {'queue': 'monitoring_events'},
    'monitoring.process_health_check': {'queue': 'monitoring_events'},
    'monitoring.process_alert_generation': {'queue': 'monitoring_events'},
    'monitoring.process_performance_analysis': {'queue': 'monitoring_events'},
    'monitoring.process_log_aggregation': {'queue': 'monitoring_events'},
    'monitoring.process_trace_analysis': {'queue': 'monitoring_events'},
    'monitoring.process_dashboard_update': {'queue': 'monitoring_events'},
    'monitoring.process_incident_management': {'queue': 'monitoring_events'},
    'monitoring.cleanup_old_metrics': {'queue': 'monitoring_maintenance'},
    'monitoring.cleanup_old_audit_logs': {'queue': 'monitoring_maintenance'},
    'monitoring.publish_outbox_events': {'queue': 'monitoring_outbox'},
}

# Beat Schedule
beat_schedule = {
    'publish-outbox': {
        'task': 'monitoring.publish_outbox_events',
        'schedule': 30.0,
    },
    'cleanup-metrics': {
        'task': 'monitoring.cleanup_old_metrics',
        'schedule': 86400.0,  # Daily
    },
    'cleanup-audit': {
        'task': 'monitoring.cleanup_old_audit_logs',
        'schedule': 86400.0,  # Daily
    },
    'process-health-check': {
        'task': 'monitoring.process_health_check',
        'schedule': 60.0,  # Every minute
    },
    'process-metrics-collection': {
        'task': 'monitoring.process_metrics_collection',
        'schedule': 30.0,  # Every 30 seconds
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

