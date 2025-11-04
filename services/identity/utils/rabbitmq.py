# RabbitMQ Publishing
import json
from datetime import datetime, timezone
from typing import Dict, Any
import pika

from core.config import get_settings
from ..utils.identity_logger import logger

RABBITMQ_URL = get_settings().RABBITMQ_URL


def publish_to_rabbitmq(event_type: str, event_data: Dict[str, Any], tenant_id: str) -> bool:
    """Publish event directly to RabbitMQ"""
    try:
        connection = pika.BlockingConnection(pika.URLParameters(RABBITMQ_URL))
        channel = connection.channel()
        channel.exchange_declare(exchange='zeroque_events', exchange_type='topic', durable=True)
        message = json.dumps({
            "event_type": event_type,
            "tenant_id": tenant_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": event_data
        })
        channel.basic_publish(
            exchange='zeroque_events',
            routing_key=event_type,
            body=message,
            properties=pika.BasicProperties(delivery_mode=2)
        )
        connection.close()
        logger.info(f"Published {event_type} to RabbitMQ")
        return True
    except Exception as e:
        logger.error(f"RabbitMQ publish failed: {e}")
        return False