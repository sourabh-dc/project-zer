import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, Any

from sqlalchemy import text

from ..core.celery_config import celery_app
from ..models import CategoryV2
from ..services.outbox_services import process_pending_outbox_events
from ..utils.cataog_logger import logger

from ..repositories.db_handler import SessionLocal, set_rls_context
from ..utils.metrics import catalog_operations_total


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

@celery_app.task(bind=True, max_retries=3, name='catalog.process_tenant_created')
def process_tenant_created(self, event_data: Dict[str, Any]):
    """Process TENANT_CREATED event from provisioning service"""
    try:
        tenant_id = event_data.get('tenant_id')
        tenant_name = event_data.get('name')

        if not tenant_id:
            logger.error('Missing tenant_id in TENANT_CREATED event')
            return {'status': 'error', 'message': 'Missing tenant_id'}

        with SessionLocal() as db:
            # Create default categories for new tenant
            default_categories = [
                {'name': 'Electronics', 'description': 'Electronic devices and accessories'},
                {'name': 'Clothing', 'description': 'Apparel and fashion items'},
                {'name': 'Home & Garden', 'description': 'Home improvement and garden supplies'},
                {'name': 'Sports & Outdoors', 'description': 'Sports equipment and outdoor gear'},
            ]

            created_count = 0
            for cat_data in default_categories:
                try:
                    category = CategoryV2(
                        category_id=uuid.uuid4(),
                        tenant_id=tenant_id,
                        name=cat_data['name'],
                        description=cat_data['description'],
                        is_active=True
                    )
                    db.add(category)
                    created_count += 1
                except Exception as e:
                    logger.error(f'Failed to create category {cat_data["name"]}: {e}')

            db.commit()
            logger.info(f'Created {created_count} default categories for tenant {tenant_id}')

        return {'status': 'ok', 'categories_created': created_count}

    except Exception as e:
        logger.error(f'Failed to process TENANT_CREATED event: {e}')
        raise self.retry(exc=e, countdown=300)

@celery_app.task(bind=True, max_retries=3, name='catalog.process_vendor_created')
def process_vendor_created(self, event_data: Dict[str, Any]):
    """Process VENDOR_CREATED event"""
    try:
        tenant_id = event_data.get('tenant_id')
        vendor_id = event_data.get('vendor_id')

        if not tenant_id or not vendor_id:
            logger.error('Missing tenant_id or vendor_id in VENDOR_CREATED event')
            return {'status': 'error', 'message': 'Missing required fields'}

        logger.info(f'Processing VENDOR_CREATED for tenant {tenant_id}, vendor {vendor_id}')
        # For now, just log the event - can be extended to create vendor-specific categories
        return {'status': 'ok', 'message': 'Vendor creation processed'}

    except Exception as e:
        logger.error(f'Failed to process VENDOR_CREATED event: {e}')
        raise self.retry(exc=e, countdown=300)

@celery_app.task(bind=True, max_retries=3, name='catalog.cleanup_old_outbox_events')
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
            logger.info(f'Cleaned up {result.rowcount} old outbox events')
            return {'deleted': result.rowcount}

    except Exception as e:
        logger.error(f'Failed to cleanup outbox events: {e}')
        raise self.retry(exc=e, countdown=300)

@celery_app.task(bind=True, max_retries=3, name='catalog.cleanup_old_audit_logs')
def cleanup_audit_logs(self):
    """Clean up old audit logs"""
    try:
        with SessionLocal() as db:
            cutoff = datetime.now(timezone.utc) - timedelta(days=90)
            result = db.execute(
                text("DELETE FROM audit_logs WHERE created_at < :cutoff"),
                {'cutoff': cutoff}
            )
            db.commit()
            logger.info(f'Cleaned up {result.rowcount} old audit logs')
            return {'deleted': result.rowcount}

    except Exception as e:
        logger.error(f'Failed to cleanup audit logs: {e}')
        raise self.retry(exc=e, countdown=300)


@celery_app.task(bind=True, max_retries=3)
def process_product_import(self, tenant_id: str, import_data: Dict[str, Any]):
    """Process product import asynchronously"""
    try:
        with SessionLocal() as db:
            # Set RLS context
            set_rls_context(db, tenant_id)

            # Process import logic here
            logger.info(f"Processing product import for tenant {tenant_id}")

            # Update metrics
            catalog_operations_total.labels(operation="import", status="success").inc()

    except Exception as e:
        logger.error(f"Failed to process product import for tenant {tenant_id}: {e}")
        catalog_operations_total.labels(operation="import", status="failed").inc()
        raise self.retry(exc=e, countdown=60)


@celery_app.task(bind=True, max_retries=3)
def rebuild_search_index(self, tenant_id: str):
    """Rebuild search index for products"""
    try:
        with SessionLocal() as db:
            # Set RLS context
            set_rls_context(db, tenant_id)

            # Rebuild index logic here
            logger.info(f"Rebuilding search index for tenant {tenant_id}")

            # Update metrics
            catalog_operations_total.labels(operation="index_rebuild", status="success").inc()

    except Exception as e:
        logger.error(f"Failed to rebuild search index for tenant {tenant_id}: {e}")
        catalog_operations_total.labels(operation="index_rebuild", status="failed").inc()
        raise self.retry(exc=e, countdown=60)


@celery_app.task(bind=True, max_retries=3)
def cleanup_old_catalog_data(self):
    """Clean up old catalog data"""
    try:
        with SessionLocal() as db:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=365)

            # Clean up old products
            product_result = db.execute(text("""
                                             DELETE
                                             FROM products_v2
                                             WHERE created_at < :cutoff_date
                                               AND is_active = false
                                             """), {"cutoff_date": cutoff_date})

            # Clean up old categories
            category_result = db.execute(text("""
                                              DELETE
                                              FROM categories_v2
                                              WHERE created_at < :cutoff_date
                                                AND is_active = false
                                              """), {"cutoff_date": cutoff_date})

            db.commit()

            logger.info(
                f"Cleaned up {product_result.rowcount} old products and {category_result.rowcount} old categories")

    except Exception as e:
        logger.error(f"Failed to cleanup old catalog data: {e}")
        raise self.retry(exc=e, countdown=300)