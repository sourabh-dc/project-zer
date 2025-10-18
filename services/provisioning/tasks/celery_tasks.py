from ..utils.provisioning_logger import logger
from ..core.celery_main import celery_app
from ..services.outbox_services import process_pending_outbox_events

@celery_app.task(name='provisioning.publish_outbox_events')
def publish_outbox_events():
    try:
        process_pending_outbox_events()
    except Exception as e:
        logger.error(f"Failed to publish outbox events: {e}")