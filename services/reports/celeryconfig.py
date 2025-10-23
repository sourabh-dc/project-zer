# services/reports/celeryconfig.py
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
    'reports.process_report_generation': {'queue': 'reports_events'},
    'reports.process_report_scheduling': {'queue': 'reports_events'},
    'reports.process_report_export': {'queue': 'reports_events'},
    'reports.process_report_analytics': {'queue': 'reports_events'},
    'reports.process_report_dashboard': {'queue': 'reports_events'},
    'reports.process_report_notification': {'queue': 'reports_events'},
    'reports.process_report_compliance': {'queue': 'reports_events'},
    'reports.process_report_archiving': {'queue': 'reports_events'},
    'reports.cleanup_old_reports': {'queue': 'reports_maintenance'},
    'reports.cleanup_old_audit_logs': {'queue': 'reports_maintenance'},
    'reports.publish_outbox_events': {'queue': 'reports_outbox'},
}

# Beat Schedule
beat_schedule = {
    'publish-outbox': {
        'task': 'reports.publish_outbox_events',
        'schedule': 30.0,
    },
    'cleanup-reports': {
        'task': 'reports.cleanup_old_reports',
        'schedule': 86400.0,  # Daily
    },
    'cleanup-audit': {
        'task': 'reports.cleanup_old_audit_logs',
        'schedule': 86400.0,  # Daily
    },
    'process-report-scheduling': {
        'task': 'reports.process_report_scheduling',
        'schedule': 300.0,  # Every 5 minutes
    },
    'process-report-archiving': {
        'task': 'reports.process_report_archiving',
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




