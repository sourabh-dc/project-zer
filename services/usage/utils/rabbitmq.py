import json
from datetime import datetime, timezone
from typing import Dict
import pika

from core.config import get_settings
from ..utils.usage_logger import logger

RABBITMQ_URL = get_settings().RABBITMQ_URL

def publish_to_rabbitmq(event_type: str, event_data: Dict, tenant_id: str):
    """Publish event to RabbitMQ"""
    try:
        conn = pika.BlockingConnection(pika.URLParameters(RABBITMQ_URL))
        ch = conn.channel()
        ch.exchange_declare(exchange='zeroque_events', exchange_type='topic', durable=True)
        msg = json.dumps({
            "event_type": event_type,
            "tenant_id": tenant_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": event_data
        })
        ch.basic_publish(
            exchange='zeroque_events',
            routing_key=event_type,
            body=msg,
            properties=pika.BasicProperties(delivery_mode=2)
        )
        conn.close()
        return True
    except Exception as e:
        logger.error(f"RabbitMQ publish failed: {e}")
        return False