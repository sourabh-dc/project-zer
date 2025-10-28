import json
import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict

from sqlalchemy import text

from ..core.celery_config import celery_app
from ..models import OutboxEvent, UsageEvent
from ..repositories.db_config import SessionLocal
from ..utils.usage_logger import logger
from ..utils.rabbitmq import publish_to_rabbitmq

# =============================================================================
# CELERY TASKS
# =============================================================================

@celery_app.task(name='usage.publish_outbox_events')
def publish_outbox_events():
    """Publish outbox events to RabbitMQ"""
    try:
        with SessionLocal() as db:
            evts = db.query(OutboxEvent).filter(
                OutboxEvent.status == "pending",
                OutboxEvent.retry_count < 5
            ).limit(100).all()

            for e in evts:
                event_data = json.loads(e.event_data) if isinstance(e.event_data, str) else e.event_data
                if publish_to_rabbitmq(e.event_type, event_data, e.aggregate_id):
                    e.status = "published"
                    e.published_at = datetime.now(timezone.utc)
                else:
                    e.retry_count += 1
                    if e.retry_count >= 5:
                        e.status = "failed"
                db.commit()

            if evts:
                logger.info(f"Published {len(evts)} events")
    except Exception as ex:
        logger.error(f"Outbox publish failed: {ex}")


@celery_app.task(bind=True, max_retries=3, name='usage.cleanup_old_usage_events')
def cleanup_old_usage_events(self):
    """Clean up old usage events"""
    try:
        with SessionLocal() as db:
            cutoff = datetime.now(timezone.utc) - timedelta(days=90)
            result = db.execute(
                text("DELETE FROM usage_events_new WHERE recorded_at < :cutoff"),
                {'cutoff': cutoff}
            )
            db.commit()
            logger.info(f"Cleaned {result.rowcount} old usage events")
            return {'deleted': result.rowcount}
    except Exception as e:
        logger.error(f"Failed to cleanup usage events: {e}")
        raise self.retry(exc=e, countdown=300)


@celery_app.task(bind=True, max_retries=3, name='usage.cleanup_old_outbox_events')
def cleanup_outbox_events(self):
    """Clean up old outbox events"""
    try:
        with SessionLocal() as db:
            cutoff = datetime.now(timezone.utc) - timedelta(days=30)
            result = db.execute(
                text("DELETE FROM outbox_events WHERE created_at < :cutoff AND status IN ('published', 'failed')"),
                {'cutoff': cutoff}
            )
            db.commit()
            logger.info(f"Cleaned {result.rowcount} old outbox events")
            return {'deleted': result.rowcount}
    except Exception as e:
        logger.error(f"Failed to cleanup outbox events: {e}")
        raise self.retry(exc=e, countdown=300)


@celery_app.task(name='usage.process_entry_granted')
def process_entry_granted(event_data: Dict):
    """Process ENTRY_GRANTED event"""
    try:
        tenant_id = event_data.get('tenant_id')
        user_id = event_data.get('user_id')

        if tenant_id:
            with SessionLocal() as db:
                # Record entry as usage event
                event_id = f"usage_{uuid.uuid4().hex[:12]}"
                event = UsageEvent(
                    event_id=event_id,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    meter_code='entry_count',
                    quantity=1,
                    metadata_json={"source": "entry_service"}
                )
                db.add(event)
                db.commit()
                logger.info(f"Recorded entry usage for tenant {tenant_id}")

        return {'status': 'ok'}
    except Exception as e:
        logger.error(f"Failed to process ENTRY_GRANTED: {e}")
        return {'status': 'error'}