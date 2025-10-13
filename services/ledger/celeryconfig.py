# services/ledger/celeryconfig.py
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
    'ledger.process_transaction': {'queue': 'ledger_events'},
    'ledger.process_journal_entry': {'queue': 'ledger_events'},
    'ledger.process_account_balance': {'queue': 'ledger_events'},
    'ledger.process_reconciliation': {'queue': 'ledger_events'},
    'ledger.process_tax_calculation': {'queue': 'ledger_events'},
    'ledger.process_financial_report': {'queue': 'ledger_events'},
    'ledger.process_audit_trail': {'queue': 'ledger_events'},
    'ledger.process_compliance_check': {'queue': 'ledger_events'},
    'ledger.cleanup_old_transactions': {'queue': 'ledger_maintenance'},
    'ledger.cleanup_old_audit_logs': {'queue': 'ledger_maintenance'},
    'ledger.publish_outbox_events': {'queue': 'ledger_outbox'},
}

# Beat Schedule
beat_schedule = {
    'publish-outbox': {
        'task': 'ledger.publish_outbox_events',
        'schedule': 30.0,
    },
    'cleanup-transactions': {
        'task': 'ledger.cleanup_old_transactions',
        'schedule': 86400.0,  # Daily
    },
    'cleanup-audit': {
        'task': 'ledger.cleanup_old_audit_logs',
        'schedule': 86400.0,  # Daily
    },
    'process-reconciliation': {
        'task': 'ledger.process_reconciliation',
        'schedule': 3600.0,  # Hourly
    },
    'process-compliance': {
        'task': 'ledger.process_compliance_check',
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

