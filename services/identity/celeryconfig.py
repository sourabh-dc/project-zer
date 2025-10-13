# services/identity/celeryconfig.py
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
    'identity.process_user_created': {'queue': 'identity_events'},
    'identity.process_user_updated': {'queue': 'identity_events'},
    'identity.process_user_deleted': {'queue': 'identity_events'},
    'identity.process_token_generated': {'queue': 'identity_events'},
    'identity.process_token_revoked': {'queue': 'identity_events'},
    'identity.process_password_reset': {'queue': 'identity_events'},
    'identity.process_mfa_setup': {'queue': 'identity_events'},
    'identity.process_session_management': {'queue': 'identity_events'},
    'identity.cleanup_old_tokens': {'queue': 'identity_maintenance'},
    'identity.cleanup_old_sessions': {'queue': 'identity_maintenance'},
    'identity.cleanup_old_audit_logs': {'queue': 'identity_maintenance'},
    'identity.publish_outbox_events': {'queue': 'identity_outbox'},
}

# Beat Schedule
beat_schedule = {
    'publish-outbox': {
        'task': 'identity.publish_outbox_events',
        'schedule': 30.0,
    },
    'cleanup-tokens': {
        'task': 'identity.cleanup_old_tokens',
        'schedule': 3600.0,  # Hourly
    },
    'cleanup-sessions': {
        'task': 'identity.cleanup_old_sessions',
        'schedule': 1800.0,  # Every 30 minutes
    },
    'cleanup-audit': {
        'task': 'identity.cleanup_old_audit_logs',
        'schedule': 86400.0,  # Daily
    },
    'check-expired-tokens': {
        'task': 'identity.process_token_revoked',
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

