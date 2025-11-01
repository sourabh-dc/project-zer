from sqlalchemy import text
from typing import Any, Dict
from datetime import datetime, timezone, timedelta

from ..core.celery_config import celery_app
from ..repositories.db_config import SessionLocal
from ..utils.notifications_logger import logger
from ..repositories.db_config import set_rls_context
from ..utils.metrics import notification_operations_total


# =============================================================================
# CELERY TASKS
# =============================================================================

@celery_app.task(bind=True, max_retries=3)
def process_notification_delivery(self, notification_id: str, delivery_data: Dict[str, Any]):
    """Process notification delivery asynchronously"""
    try:
        with SessionLocal() as db:
            # Get notification
            notification = db.execute(text("""
                                           SELECT *
                                           FROM notifications_new
                                           WHERE id = :id
                                           """), {"id": notification_id}).fetchone()

            if not notification:
                raise ValueError(f"Notification {notification_id} not found")

            # Process delivery logic here
            logger.info(f"Processing notification delivery for notification {notification_id}")

            # Update status
            db.execute(text("""
                            UPDATE notifications_new
                            SET status       = 'delivered',
                                delivered_at = NOW()
                            WHERE id = :id
                            """), {"id": notification_id})

            db.commit()

            # Update metrics
            notification_operations_total.labels(operation="delivery", status="success").inc()

    except Exception as e:
        logger.error(f"Failed to process notification delivery for notification {notification_id}: {e}")
        notification_operations_total.labels(operation="delivery", status="failed").inc()
        raise self.retry(exc=e, countdown=60)


@celery_app.task(bind=True, max_retries=3)
def process_email_notification(self, tenant_id: str, email_data: Dict[str, Any]):
    """Process email notification asynchronously"""
    try:
        with SessionLocal() as db:
            # Set RLS context
            set_rls_context(db, tenant_id)

            # Process email logic here
            logger.info(f"Processing email notification for tenant {tenant_id}")

            # Update metrics
            notification_operations_total.labels(operation="email", status="success").inc()

    except Exception as e:
        logger.error(f"Failed to process email notification for tenant {tenant_id}: {e}")
        notification_operations_total.labels(operation="email", status="failed").inc()
        raise self.retry(exc=e, countdown=60)


@celery_app.task(bind=True, max_retries=3)
def cleanup_old_notifications(self):
    """Clean up old notifications"""
    try:
        with SessionLocal() as db:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=90)

            # Clean up old notifications
            notification_result = db.execute(text("""
                                                  DELETE
                                                  FROM notifications_new
                                                  WHERE created_at < :cutoff_date
                                                    AND status IN ('delivered', 'failed')
                                                  """), {"cutoff_date": cutoff_date})

            # Clean up old delivery attempts
            delivery_result = db.execute(text("""
                                              DELETE
                                              FROM delivery_attempts_new
                                              WHERE created_at < :cutoff_date
                                                AND status IN ('delivered', 'failed')
                                              """), {"cutoff_date": cutoff_date})

            db.commit()

            logger.info(
                f"Cleaned up {notification_result.rowcount} old notifications and {delivery_result.rowcount} old delivery attempts")

    except Exception as e:
        logger.error(f"Failed to cleanup old notifications: {e}")
        raise self.retry(exc=e, countdown=300)