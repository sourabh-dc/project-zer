from datetime import datetime, timezone, timedelta

from sqlalchemy import text

from ..core.celery_config import celery_app
from ..services.outbox_services import process_pending_outbox_events
from ..utils.cataog_logger import logger

from ..repositories.db_handler import SessionLocal


@celery_app.task(bind=True, max_retries=3, name='catalog.publish_outbox_events')
def publish_outbox_events(self):
    """Publish outbox events to RabbitMQ"""
    try:
        process_pending_outbox_events()
    except Exception as e:
        logger.error("Outbox publishing failed", error=str(e))
        raise self.retry(exc=e, countdown=60)


@celery_app.task(bind=True, max_retries=3)
def process_search_indexing(self, product_id: str):
    """Process search indexing for a product"""
    try:
        with SessionLocal() as db:
            product = db.execute(
                text("SELECT * FROM products_v2 WHERE product_id = :id"),
                {"id": product_id}
            ).fetchone()

            if not product:
                raise ValueError("Product not found")

            # TODO: Index product in search engine (Elasticsearch, etc.)
            logger.info("Product indexed for search", product_id=product_id)

    except Exception as e:
        logger.error("Search indexing failed", product_id=product_id, error=str(e))
        raise self.retry(exc=e, countdown=60)


@celery_app.task(bind=True, max_retries=3)
def cleanup_old_products(self):
    """Cleanup old inactive products"""
    try:
        with SessionLocal() as db:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=365)
            result = db.execute(
                text("DELETE FROM products_v2 WHERE is_active = false AND updated_at < :cutoff"),
                {"cutoff": cutoff_date}
            )
            db.commit()
            logger.info("Cleaned up old products", count=result.rowcount)
    except Exception as e:
        logger.error("Product cleanup failed", error=str(e))
        raise self.retry(exc=e, countdown=60)