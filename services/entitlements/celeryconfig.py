# services/entitlements/celeryconfig.py
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
    'entitlements.process_entitlement_granted': {'queue': 'entitlements_events'},
    'entitlements.process_entitlement_revoked': {'queue': 'entitlements_events'},
    'entitlements.process_entitlement_updated': {'queue': 'entitlements_events'},
    'entitlements.process_access_check': {'queue': 'entitlements_events'},
    'entitlements.process_permission_validation': {'queue': 'entitlements_events'},
    'entitlements.process_role_assignment': {'queue': 'entitlements_events'},
    'entitlements.process_policy_evaluation': {'queue': 'entitlements_events'},
    'entitlements.process_compliance_check': {'queue': 'entitlements_events'},
    'entitlements.cleanup_old_entitlements': {'queue': 'entitlements_maintenance'},
    'entitlements.cleanup_old_audit_logs': {'queue': 'entitlements_maintenance'},
    'entitlements.publish_outbox_events': {'queue': 'entitlements_outbox'},
}

# Beat Schedule
beat_schedule = {
    'publish-outbox': {
        'task': 'entitlements.publish_outbox_events',
        'schedule': 30.0,
    },
    'cleanup-entitlements': {
        'task': 'entitlements.cleanup_old_entitlements',
        'schedule': 86400.0,  # Daily
    },
    'cleanup-audit': {
        'task': 'entitlements.cleanup_old_audit_logs',
        'schedule': 86400.0,  # Daily
    },
    'process-access-check': {
        'task': 'entitlements.process_access_check',
        'schedule': 300.0,  # Every 5 minutes
    },
    'process-compliance-check': {
        'task': 'entitlements.process_compliance_check',
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

