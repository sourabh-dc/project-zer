import os
import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, Any

import httpx
import pika
from sqlalchemy import text
from tenacity import retry, stop_after_attempt, wait_exponential

from ..core.celery_config import celery_app
from ..models import PricebookV2
from ..repositories.db_config import SessionLocal, set_rls_context
from core.config import get_settings
from ..utils.metrics import pricing_operations_total
from ..utils.pricing_logger import logger


RABBITMQ_URL= get_settings().RABBITMQ_URL

CATALOG_BASE = os.getenv("CATALOG_BASE", "http://localhost:8008")

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def call_external_service(url: str, method: str = "GET", data: Dict = None):
    """Call external service with retry"""
    with httpx.Client() as client:
        if method == "GET":
            response = client.get(url)
        elif method == "POST":
            response = client.post(url, json=data)
        elif method == "PUT":
            response = client.put(url, json=data)
        else:
            raise ValueError(f"Unsupported method: {method}")

        response.raise_for_status()
        return response.json()


# =============================================================================
# CELERY TASKS
# =============================================================================

@celery_app.task(bind=True, max_retries=3)
def publish_outbox_events(self):
    """Publish outbox events to RabbitMQ"""
    try:
        with SessionLocal() as db:
            events = db.execute(text("SELECT * FROM outbox_events WHERE status = 'pending' LIMIT 100")).fetchall()

            for event in events:
                try:
                    # Publish to RabbitMQ
                    connection = pika.BlockingConnection(pika.URLParameters(RABBITMQ_URL))
                    channel = connection.channel()

                    channel.basic_publish(
                        exchange='pricing_events',
                        routing_key=event.event_type.lower(),
                        body=event.event_data
                    )

                    # Update status
                    db.execute(
                        text(
                            "UPDATE outbox_events SET status = 'published', published_at = NOW() WHERE event_id = :id"),
                        {"id": event.event_id}
                    )
                    db.commit()

                    connection.close()

                except Exception as e:
                    logger.error("Failed to publish event", event_id=event.event_id, error=str(e))
                    # Increment retry count
                    db.execute(
                        text("UPDATE outbox_events SET retry_count = retry_count + 1 WHERE event_id = :id"),
                        {"id": event.event_id}
                    )
                    db.commit()

    except Exception as e:
        logger.error("Outbox publishing failed", error=str(e))
        raise self.retry(exc=e, countdown=60)


@celery_app.task(bind=True, max_retries=3)
def process_price_calculation(self, tenant_id: str, calculation_data: Dict[str, Any]):
    """Process price calculation asynchronously"""
    try:
        with SessionLocal() as db:
            # Set RLS context
            set_rls_context(db, tenant_id)

            # Process price calculation logic here
            logger.info(f"Processing price calculation for tenant {tenant_id}")

            # Update metrics
            pricing_operations_total.labels(operation="calculation", status="success").inc()

    except Exception as e:
        logger.error(f"Failed to process price calculation for tenant {tenant_id}: {e}")
        pricing_operations_total.labels(operation="calculation", status="failed").inc()
        raise self.retry(exc=e, countdown=60)


@celery_app.task(bind=True, max_retries=3)
def process_pricebook_update(self, tenant_id: str, pricebook_id: str, update_data: Dict[str, Any]):
    """Process pricebook update asynchronously"""
    try:
        with SessionLocal() as db:
            # Set RLS context
            set_rls_context(db, tenant_id)

            # Process pricebook update logic here
            logger.info(f"Processing pricebook update for tenant {tenant_id}, pricebook {pricebook_id}")

            # Update metrics
            pricing_operations_total.labels(operation="pricebook_update", status="success").inc()

    except Exception as e:
        logger.error(f"Failed to process pricebook update: {e}")
        pricing_operations_total.labels(operation="pricebook_update", status="failed").inc()
        raise self.retry(exc=e, countdown=60)


@celery_app.task(bind=True, max_retries=3)
def cleanup_old_pricing_data(self):
    """Clean up old pricing data"""
    try:
        with SessionLocal() as db:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=90)

            # Clean up old calculated prices
            price_result = db.execute(text("""
                                           DELETE
                                           FROM calculated_prices_v2
                                           WHERE calculated_at < :cutoff_date
                                           """), {"cutoff_date": cutoff_date})

            # Clean up old price rules
            rule_result = db.execute(text("""
                                          DELETE
                                          FROM price_rules_v2
                                          WHERE created_at < :cutoff_date
                                            AND is_active = false
                                          """), {"cutoff_date": cutoff_date})

            db.commit()

            logger.info(
                f"Cleaned up {price_result.rowcount} old calculated prices and {rule_result.rowcount} old price rules")

    except Exception as e:
        logger.error(f"Failed to cleanup old pricing data: {e}")
        raise self.retry(exc=e, countdown=300)


# =============================================================================
# CELERY WORKERS - Event Consumption
# =============================================================================

@celery_app.task(bind=True, max_retries=3, name='pricing.process_product_created')
def process_product_created(self, event_data: Dict[str, Any]):
    """Process PRODUCT_CREATED event from catalog service"""
    try:
        tenant_id = event_data.get('tenant_id')
        product_id = event_data.get('product_id')
        product_name = event_data.get('name')

        if not all([tenant_id, product_id]):
            logger.error('Missing required fields in PRODUCT_CREATED event')
            return {'status': 'error', 'message': 'Missing required fields'}

        with SessionLocal() as db:
            # Create default pricebook for new product if none exists
            existing_pricebook = db.query(PricebookV2).filter(
                PricebookV2.tenant_id == tenant_id,
                PricebookV2.name == 'Default Pricebook'
            ).first()

            if not existing_pricebook:
                # Create default pricebook
                pricebook_id = f"pb_{uuid.uuid4().hex[:12]}"
                pricebook = PricebookV2(
                    pricebook_id=pricebook_id,
                    tenant_id=tenant_id,
                    name='Default Pricebook',
                    currency='GBP'
                )
                db.add(pricebook)
                db.commit()

                logger.info(f"Created default pricebook {pricebook_id} for tenant {tenant_id}")

        return {'status': 'ok', 'pricebook_created': existing_pricebook is None}

    except Exception as e:
        logger.error(f"Failed to process PRODUCT_CREATED event: {e}")
        raise self.retry(exc=e, countdown=300)


@celery_app.task(bind=True, max_retries=3, name='pricing.cleanup_old_outbox_events')
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
        logger.error(f"Failed to cleanup outbox events: {e}")
        raise self.retry(exc=e, countdown=300)


@celery_app.task(bind=True, max_retries=3, name='pricing.cleanup_old_pricing_data')
def cleanup_old_pricing_data(self):
    """Clean up old pricing data"""
    try:
        with SessionLocal() as db:
            cutoff = datetime.now(timezone.utc) - timedelta(days=90)

            # Clean old price calculations
            calc_result = db.execute(
                text("DELETE FROM calculated_prices_v2 WHERE calculated_at < :cutoff"),
                {'cutoff': cutoff}
            )

            # Clean old price rules (if not referenced)
            rules_result = db.execute(
                text(
                    "DELETE FROM price_rules_v2 WHERE created_at < :cutoff AND id NOT IN (SELECT DISTINCT rule_id FROM plan_rules WHERE rule_id IS NOT NULL)"),
                {'cutoff': cutoff}
            )

            db.commit()
            logger.info(f"Cleaned {calc_result.rowcount} old calculations and {rules_result.rowcount} old rules")
            return {'calculations_deleted': calc_result.rowcount, 'rules_deleted': rules_result.rowcount}

    except Exception as e:
        logger.error(f"Failed to cleanup old pricing data: {e}")
        raise self.retry(exc=e, countdown=300)