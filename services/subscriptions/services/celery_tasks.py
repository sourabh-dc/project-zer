import time
from datetime import datetime, timedelta
from typing import Dict

from sqlalchemy import text

from services.subscriptions.core.celery_config import celery_app
from services.subscriptions.models import OutboxEvent, TenantSubscription
from services.subscriptions.repositories.database_ops import store_outbox_event
from services.subscriptions.repositories.db_config import SessionLocal
from services.subscriptions.utils.rabbitmq import publish_to_rabbitmq
from services.subscriptions.utils.subsciptions_logger import logger

SUBSCRIPTION_CLEANUP_DAYS = 365

@celery_app.task(bind=True, max_retries=3)
def publish_outbox_events(self):
    try:
        with SessionLocal() as db:
            events = db.query(OutboxEvent).filter(OutboxEvent.status == "pending", OutboxEvent.retry_count < 3).limit(100).all()
            for event in events:
                success = publish_to_rabbitmq(event.event_type, event.event_data, event.tenant_id)
                if success:
                    event.status = "published"
                    event.published_at = datetime.now()
                else:
                    event.retry_count += 1
                    if event.retry_count >= 3:
                        event.status = "failed"
                db.commit()
    except Exception as e:
        logger.error(f"Outbox publishing failed: {e}")
        raise self.retry(exc=e, countdown=60)

@celery_app.task(name='subscriptions.process_tenant_created')
def process_tenant_created(event_data: Dict):
    try:
        tenant_id = event_data['tenant_id']
        with SessionLocal() as db:
            # Auto-create default subscription (e.g., Core plan)
            subscription = TenantSubscription(
                tenant_id=tenant_id,
                plan_code="core",
                payment_method="trade",
                status="active",
                external_id=f"sub_{tenant_id}_{int(time.time())}",
                current_period_start=datetime.now(),
                current_period_end=datetime.now() + timedelta(days=365)
            )
            db.add(subscription)
            db.commit()
            logger.info(f"Auto-created Core subscription for tenant {tenant_id}")
            # Publish PLAN_CREATED
            store_outbox_event(db, "PLAN_CREATED", tenant_id, tenant_id, {"tenant_id": tenant_id, "plan_code": "core"})
            publish_outbox_events.delay()
        return {"status": "processed"}
    except Exception as e:
        logger.error(f"Failed to process TENANT_CREATED: {e}")
        raise

@celery_app.task(name='subscriptions.cleanup_old_subscriptions')
def cleanup_old_subscriptions():
    try:
        with SessionLocal() as db:
            cutoff = datetime.now() - timedelta(days=SUBSCRIPTION_CLEANUP_DAYS)
            deleted = db.execute(text("DELETE FROM tenant_subscriptions WHERE canceled_at < :cutoff AND status = 'canceled'"), {"cutoff": cutoff})
            db.commit()
            logger.info(f"Cleaned {deleted.rowcount} old subscriptions")
    except Exception as e:
        logger.error(f"Cleanup failed: {e}")