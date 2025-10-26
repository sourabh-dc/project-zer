import os
from datetime import datetime, timezone, timedelta
from typing import Dict, Any

import pika
import httpx
from sqlalchemy import text
from tenacity import retry, stop_after_attempt, wait_exponential

from ..core.celery_config import celery_app
from ..repositories.db_config import SessionLocal
from ..utils.orders_logger import logger
from core.config import get_settings
from ..utils.metrics import orders_operations_total

RABBITMQ_URL = get_settings().RABBITMQ_URL

# External service URLs
INVENTORY_BASE = os.getenv("INVENTORY_BASE", "http://localhost:8008")

# =============================================================================
# CELERY TASKS
# =============================================================================

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

@celery_app.task(bind=True, max_retries=3, name='orders.publish_outbox_events')
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
                        exchange='orders_events',
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
def process_order_fulfillment(self, order_id: str, fulfillment_data: Dict[str, Any]):
    """Process order fulfillment asynchronously"""
    try:
        with SessionLocal() as db:
            # Get order
            order = db.execute(text("""
                                    SELECT *
                                    FROM orders_v2
                                    WHERE order_id = :id
                                    """), {"id": order_id}).fetchone()

            if not order:
                raise ValueError(f"Order {order_id} not found")

            # Process fulfillment logic here
            logger.info(f"Processing order fulfillment for order {order_id}")

            # Update status
            db.execute(text("""
                            UPDATE orders_v2
                            SET fulfillment_status = 'fulfilled',
                                updated_at         = NOW()
                            WHERE order_id = :id
                            """), {"id": order_id})

            db.commit()

            # Update metrics
            orders_operations_total.labels(operation="fulfillment", status="success").inc()

    except Exception as e:
        logger.error(f"Failed to process order fulfillment for order {order_id}: {e}")
        orders_operations_total.labels(operation="fulfillment", status="failed").inc()
        raise self.retry(exc=e, countdown=60)


@celery_app.task(bind=True, max_retries=3)
def process_order_cancellation(self, order_id: str, cancellation_reason: str):
    """Process order cancellation asynchronously"""
    try:
        with SessionLocal() as db:
            # Get order
            order = db.execute(text("""
                                    SELECT *
                                    FROM orders_v2
                                    WHERE order_id = :id
                                    """), {"id": order_id}).fetchone()

            if not order:
                raise ValueError(f"Order {order_id} not found")

            # Process cancellation logic here
            logger.info(f"Processing order cancellation for order {order_id}, reason: {cancellation_reason}")

            # Update status
            db.execute(text("""
                            UPDATE orders_v2
                            SET order_status = 'cancelled',
                                updated_at   = NOW()
                            WHERE order_id = :id
                            """), {"id": order_id})

            db.commit()

            # Update metrics
            orders_operations_total.labels(operation="cancellation", status="success").inc()

    except Exception as e:
        logger.error(f"Failed to process order cancellation for order {order_id}: {e}")
        orders_operations_total.labels(operation="cancellation", status="failed").inc()
        raise self.retry(exc=e, countdown=60)


@celery_app.task(bind=True, max_retries=3)
def cleanup_old_orders(self):
    """Clean up old orders"""
    try:
        with SessionLocal() as db:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=365)

            # Clean up old completed orders
            order_result = db.execute(text("""
                                           DELETE
                                           FROM orders_v2
                                           WHERE created_at < :cutoff_date
                                             AND order_status IN ('completed', 'cancelled')
                                           """), {"cutoff_date": cutoff_date})

            db.commit()

            logger.info(f"Cleaned up {order_result.rowcount} old orders")

    except Exception as e:
        logger.error(f"Failed to cleanup old orders: {e}")
        raise self.retry(exc=e, countdown=300)