# packages/zeroque_common/zeroque_common/events/celery_app.py
"""
Celery application configuration for ZeroQue event bus.
"""
import os
from celery import Celery

# Redis URL for Celery broker and result backend
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:4000/0")

# Create Celery app
celery_app = Celery(
    "zeroque",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=[
        "zeroque_common.events.tasks",
        "zeroque_common.events.webhook_tasks", 
        "zeroque_common.events.notification_tasks",
        "zeroque_common.events.pricing_tasks",
        "zeroque_common.events.catalog_tasks",
        "zeroque_common.events.provisioning_tasks",
        "zeroque_common.events.identity_tasks",
    ]
)

# Celery configuration
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=30 * 60,  # 30 minutes
    task_soft_time_limit=25 * 60,  # 25 minutes
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=1000,
    # Retry configuration
    task_acks_late=True,
    worker_disable_rate_limits=False,
    # Result backend configuration
    result_expires=3600,  # 1 hour
    # Task routing
    task_routes={
        "zeroque_common.events.webhook_tasks.*": {"queue": "webhooks"},
        "zeroque_common.events.notification_tasks.*": {"queue": "notifications"},
        "zeroque_common.events.pricing_tasks.*": {"queue": "pricing"},
        "zeroque_common.events.catalog_tasks.*": {"queue": "catalog"},
        "zeroque_common.events.provisioning_tasks.*": {"queue": "provisioning"},
        "zeroque_common.events.identity_tasks.*": {"queue": "identity"},
        "zeroque_common.events.tasks.*": {"queue": "default"},
    },
    # Queue configuration
    task_default_queue="default",
    task_queues={
        "default": {
            "exchange": "default",
            "exchange_type": "direct",
            "routing_key": "default",
        },
        "webhooks": {
            "exchange": "webhooks",
            "exchange_type": "direct",
            "routing_key": "webhooks",
        },
        "notifications": {
            "exchange": "notifications",
            "exchange_type": "direct",
            "routing_key": "notifications",
        },
        "pricing": {
            "exchange": "pricing",
            "exchange_type": "direct",
            "routing_key": "pricing",
        },
        "catalog": {
            "exchange": "catalog",
            "exchange_type": "direct",
            "routing_key": "catalog",
        },
        "provisioning": {
            "exchange": "provisioning",
            "exchange_type": "direct",
            "routing_key": "provisioning",
        },
        "identity": {
            "exchange": "identity",
            "exchange_type": "direct",
            "routing_key": "identity",
        },
        "orders": {
            "exchange": "orders",
            "exchange_type": "direct",
            "routing_key": "orders",
        },
        "inventory": {
            "exchange": "inventory",
            "exchange_type": "direct",
            "routing_key": "inventory",
        },
        "budget": {
            "exchange": "budget",
            "exchange_type": "direct",
            "routing_key": "budget",
        },
        "analytics": {
            "exchange": "analytics",
            "exchange_type": "direct",
            "routing_key": "analytics",
        },
        "security": {
            "exchange": "security",
            "exchange_type": "direct",
            "routing_key": "security",
        },
        "cache": {
            "exchange": "cache",
            "exchange_type": "direct",
            "routing_key": "cache",
        },
        "search": {
            "exchange": "search",
            "exchange_type": "direct",
            "routing_key": "search",
        },
        "user_management": {
            "exchange": "user_management",
            "exchange_type": "direct",
            "routing_key": "user_management",
        },
    },
)

# Periodic tasks (beat schedule)
celery_app.conf.beat_schedule = {
    "process-webhook-dlq": {
        "task": "zeroque_common.events.webhook_tasks.process_dlq_messages",
        "schedule": 300.0,  # Every 5 minutes
    },
    "cleanup-expired-tokens": {
        "task": "zeroque_common.events.tasks.cleanup_expired_tokens",
        "schedule": 3600.0,  # Every hour
    },
    "sync-usage-metrics": {
        "task": "zeroque_common.events.tasks.sync_usage_metrics",
        "schedule": 600.0,  # Every 10 minutes
    },
}

if __name__ == "__main__":
    celery_app.start()
