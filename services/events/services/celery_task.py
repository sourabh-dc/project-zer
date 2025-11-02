import os
from typing import Dict, Any, List
import time
import json
from datetime import datetime, timedelta
from core.config import get_settings
from ..core.celery_config import celery_app
from ..utils.events_logger import logger

DATABASE_URL = get_settings().DATABASE_URL
EVENT_RETENTION_DAYS = int(os.getenv("EVENT_RETENTION_DAYS", "30"))
# RabbitMQ configuration
try:
    import pika
    RABBITMQ_AVAILABLE = True
except ImportError:
    RABBITMQ_AVAILABLE = False
    logger.warning("pika not available, RabbitMQ integration disabled")

RABBITMQ_URL = get_settings().RABBITMQ_URL

@celery_app.task(bind=True, max_retries=3)
def publish_to_rabbitmq(self, event_type: str, event_data: Dict[str, Any], tenant_id: str, event_id: str = None,
                        subscriptions: List[Dict[str, str]] = None):
    """Celery task to publish events to RabbitMQ"""
    try:
        if not RABBITMQ_AVAILABLE:
            logger.warning("RabbitMQ not available, simulating event publishing")
            time.sleep(0.1)  # Simulate network delay
            return True

        # Connect to RabbitMQ
        connection = None
        try:
            # Parse RabbitMQ URL
            import urllib.parse as urlparse
            parsed_url = urlparse.urlparse(RABBITMQ_URL)

            # Create connection parameters
            credentials = pika.PlainCredentials(parsed_url.username or 'guest', parsed_url.password or 'guest')
            parameters = pika.ConnectionParameters(
                host=parsed_url.hostname or 'localhost',
                port=parsed_url.port or 5672,
                virtual_host=parsed_url.path.lstrip('/') or '/',
                credentials=credentials
            )

            connection = pika.BlockingConnection(parameters)
            channel = connection.channel()

            # Declare exchange
            exchange_name = 'zeroque_events'
            channel.exchange_declare(exchange=exchange_name, exchange_type='topic', durable=True)

            # Create message
            message = {
                'event_type': event_type,
                'event_data': event_data,
                'tenant_id': tenant_id,
                'timestamp': datetime.utcnow().isoformat(),
                'event_id': event_id
            }

            # Publish to subscriptions if available, otherwise use default routing
            if subscriptions:
                for subscription in subscriptions:
                    queue_name = subscription.get('queue_name', f"{event_type}_queue")
                    service_name = subscription.get('service_name', 'default')

                    # Declare queue for this service
                    channel.queue_declare(queue=queue_name, durable=True)

                    # Bind queue to exchange with service-specific routing key
                    routing_key = f"{event_type}.{service_name}.{tenant_id}"
                    channel.queue_bind(
                        exchange=exchange_name,
                        queue=queue_name,
                        routing_key=routing_key
                    )

                    # Publish message to this queue
                    channel.basic_publish(
                        exchange=exchange_name,
                        routing_key=routing_key,
                        body=json.dumps(message),
                        properties=pika.BasicProperties(
                            delivery_mode=2,  # Make message persistent
                            content_type='application/json',
                            headers={
                                'tenant_id': tenant_id,
                                'service_name': service_name,
                                'queue_name': queue_name
                            }
                        )
                    )

                    logger.info(f"Published event {event_type} to queue {queue_name} for service {service_name}")
            else:
                # Default routing - publish to general exchange
                routing_key = f"{event_type}.{tenant_id}"
                channel.basic_publish(
                    exchange=exchange_name,
                    routing_key=routing_key,
                    body=json.dumps(message),
                    properties=pika.BasicProperties(
                        delivery_mode=2,  # Make message persistent
                        content_type='application/json',
                        headers={'tenant_id': tenant_id}
                    )
                )
                logger.info(f"Published event {event_type} to RabbitMQ with routing key {routing_key}")

            return True

        finally:
            if connection and not connection.is_closed:
                connection.close()

    except Exception as exc:
        logger.error(f"RabbitMQ publishing failed: {str(exc)}")
        raise self.retry(exc=exc, countdown=60)


@celery_app.task(bind=True)
def cleanup_old_events(self):
    """Cleanup old events and metrics based on retention policy"""
    try:
        from sqlalchemy import create_engine, text
        from sqlalchemy.orm import sessionmaker

        # Create sync engine for cleanup
        sync_engine = create_engine(DATABASE_URL)
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=sync_engine)

        cutoff_date = datetime.utcnow() - timedelta(days=EVENT_RETENTION_DAYS)

        with SessionLocal() as db:
            # Cleanup old events
            events_deleted = db.execute(text("""
                                             DELETE
                                             FROM events_new
                                             WHERE created_at < :cutoff_date
                                               AND status IN ('published', 'failed')
                                             """), {"cutoff_date": cutoff_date}).rowcount

            # Cleanup old metrics
            metrics_deleted = db.execute(text("""
                                              DELETE
                                              FROM event_metrics
                                              WHERE timestamp < :cutoff_date
                                              """), {"cutoff_date": cutoff_date}).rowcount

            db.commit()

            logger.info(f"Cleanup completed: {events_deleted} events, {metrics_deleted} metrics deleted")
            return {"events_deleted": events_deleted, "metrics_deleted": metrics_deleted}

    except Exception as exc:
        logger.error(f"Event cleanup failed: {str(exc)}")
        raise self.retry(exc=exc, countdown=3600)  # Retry in 1 hour