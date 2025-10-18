# services/provisioning/celeryconfig.py
"""
Celery configuration for ZeroQue Provisioning Service
"""

import os

# Broker and Backend
broker_url = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672//")
result_backend = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Serialization
task_serializer = 'json'
result_serializer = 'json'
accept_content = ['json']

# Timezone
timezone = 'UTC'
enable_utc = True

# Task routing
task_routes = {
    'provisioning.process_entry_granted': {'queue': 'provisioning_events'},
    'provisioning.process_order_completed': {'queue': 'provisioning_events'},
    'provisioning.process_invoice_posted': {'queue': 'provisioning_events'},
    'provisioning.process_notification_sent': {'queue': 'provisioning_events'},
    'provisioning.process_usage_recorded': {'queue': 'provisioning_events'},
    'provisioning.cleanup_old_audit_logs': {'queue': 'provisioning_maintenance'},
    'provisioning.cleanup_old_outbox_events': {'queue': 'provisioning_maintenance'},
    'provisioning.publish_outbox_events': {'queue': 'provisioning_maintenance'},
}

# Beat schedule
beat_schedule = {
    'publish-outbox': {
        'task': 'provisioning.publish_outbox_events',
        'schedule': 30.0,  # Every 30 seconds
    },
    'cleanup-audit': {
        'task': 'provisioning.cleanup_old_audit_logs',
        'schedule': 86400.0,  # Daily
    },
    'cleanup-outbox': {
        'task': 'provisioning.cleanup_old_outbox_events',
        'schedule': 86400.0,  # Daily
    },
}

# Worker configuration
worker_prefetch_multiplier = 4
worker_max_tasks_per_child = 1000
task_acks_late = True
task_reject_on_worker_lost = True
task_time_limit = 300
task_soft_time_limit = 240
worker_concurrency = 4

# Result backend settings
result_expires = 3600  # 1 hour
result_cache_max = 10000

# Task execution settings
task_always_eager = False
task_eager_propagates = True

# Monitoring
worker_send_task_events = True
task_send_sent_event = True