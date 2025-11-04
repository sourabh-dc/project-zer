from services.provisioning.utils.provisioning_logger import logger
from services.provisioning.core.celery_main import celery_app
from services.provisioning.services.outbox_services import process_pending_outbox_events
from datetime import datetime, timedelta
from services.provisioning.models import *
from services.provisioning.repositories.db_handler import SessionLocal

@celery_app.task(name='provisioning.publish_outbox_events')
def publish_outbox_events():
    try:
        process_pending_outbox_events()
    except Exception as e:
        logger.error(f"Failed to publish outbox events: {e}")

@celery_app.task(name='provisioning.process_entry_granted')
def process_entry_granted(data):
    logger.info(f"Processed ENTRY_GRANTED: {data}")
    return {"status": "ok"}

@celery_app.task(name='provisioning.process_order_completed')
def process_order_completed(data):
    logger.info(f"Processed ORDER_COMPLETED: {data}")
    return {"status": "ok"}

@celery_app.task(name='provisioning.process_notification_sent')
def process_notification_sent(data):
    logger.info(f"Processed NOTIFICATION_SENT")
    return {"status": "ok"}

@celery_app.task(name='provisioning.process_usage_recorded')
def process_usage_recorded(data):
    logger.info(f"Processed USAGE_RECORDED")
    return {"status": "ok"}

@celery_app.task(name='provisioning.process_invoice_posted')
def process_invoice_posted(data):
    try:
        tid = data.get("tenant_id")
        if tid:
            with SessionLocal() as db:
                t = db.query(TenantV2).filter(TenantV2.tenant_id == uuid.UUID(tid)).first()
                if t:
                    m = t.tenant_metadata or {}
                    m["last_billed"] = datetime.now().isoformat()
                    t.tenant_metadata = m
                    db.commit()
        logger.info(f"Processed INVOICE_POSTED")
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Invoice handler failed: {e}")
        return {"status": "error"}

@celery_app.task(bind=True, max_retries=3, name='provisioning.cleanup_old_audit_logs')
def cleanup_audit(self):
    try:
        with SessionLocal() as db:
            cutoff = datetime.now() - timedelta(days=90)
            result = db.execute(text("DELETE FROM audit_logs WHERE created_at < :c"), {"c": cutoff})
            db.commit()
            logger.info(f"Cleaned {result.rowcount} audit logs")
            return {"deleted": result.rowcount}
    except Exception as e:
        logger.error(f"Audit cleanup failed: {e}")
        raise self.retry(exc=e, countdown=300)

@celery_app.task(bind=True, max_retries=3, name='provisioning.cleanup_old_outbox_events')
def cleanup_outbox(self):
    try:
        with SessionLocal() as db:
            cutoff = datetime.now() - timedelta(days=30)
            result = db.execute(text("DELETE FROM outbox_events WHERE created_at < :c AND status IN ('published', 'failed')"), {"c": cutoff})
            db.commit()
            logger.info(f"Cleaned {result.rowcount} outbox events")
            return {"deleted": result.rowcount}
    except Exception as e:
        logger.error(f"Outbox cleanup failed: {e}")
        raise self.retry(exc=e, countdown=300)