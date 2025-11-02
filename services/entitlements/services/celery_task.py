from datetime import datetime, timedelta
from typing import Dict

from sqlalchemy import text

from services.entitlements.core.celery_config import celery_app
from services.entitlements.models import OutboxEvent, SubscriptionUsage
from services.entitlements.repositories.db_config import SessionLocal
from services.entitlements.utils.entitlements_logger import logger
from services.entitlements.utils.rabbitmq import publish_to_rabbitmq


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

# Celery Worker for TENANT_CREATED
@celery_app.task(name='entitlements.process_tenant_created')
def process_tenant_created(event_data: Dict):
    try:
        tenant_id = event_data['tenant_id']
        with SessionLocal() as db:
            # Initialize usage records for default features (e.g., from Subscriptions)
            default_features = ["api_calls", "analytics"]  # Fetch from Subscriptions if needed
            month_start = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            month_end = (month_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
            for feature in default_features:
                usage = SubscriptionUsage(
                    tenant_id=tenant_id,
                    feature_code=feature,
                    usage_type="default",
                    usage_count=0,
                    period_start=month_start,
                    period_end=month_end
                )
                db.add(usage)
            db.commit()
            logger.info(f"Initialized usage for tenant {tenant_id}")
        return {"status": "processed"}
    except Exception as e:
        logger.error(f"Failed to process TENANT_CREATED: {e}")
        raise

@celery_app.task(name='entitlements.cleanup_old_usage')
def cleanup_old_usage():
    try:
        with SessionLocal() as db:
            cutoff = datetime.now() - timedelta(days=365)
            deleted = db.execute(text("DELETE FROM subscription_usage WHERE created_at < :cutoff"), {"cutoff": cutoff})
            db.commit()
            logger.info(f"Cleaned {deleted.rowcount} old usage records")
    except Exception as e:
        logger.error(f"Cleanup failed: {e}")