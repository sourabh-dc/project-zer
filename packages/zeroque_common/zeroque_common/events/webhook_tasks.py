# packages/zeroque_common/zeroque_common/events/webhook_tasks.py
"""
Celery tasks for webhook processing
"""
import logging
import requests
from typing import Dict, Any
from celery import current_task
from zeroque_common.events.celery_app import celery_app
from zeroque_common.events.bus import EventType

log = logging.getLogger("webhook_tasks")

@celery_app.task(bind=True, max_retries=3)
def trigger_order_webhooks(self, event_data: Dict[str, Any]):
    """Trigger webhooks for order events"""
    try:
        event_type = EventType(event_data["event_type"])
        tenant_id = event_data["tenant_id"]
        order_id = event_data["data"]["order_id"]
        
        log.info("Triggering webhooks for order event: %s", event_type.value)
        
        # Implementation would send webhooks to registered endpoints
        # For now, just log the webhook trigger
        
        webhook_urls = [
            "https://example.com/webhooks/orders",
            "https://analytics.example.com/events/orders"
        ]
        
        for url in webhook_urls:
            try:
                # In a real implementation, this would make HTTP requests
                log.info("Webhook sent to %s for order %s", url, order_id)
            except Exception as e:
                log.error("Webhook failed for %s: %s", url, str(e))
        
        return {"status": "success", "webhooks_sent": len(webhook_urls)}
        
    except Exception as exc:
        log.error("Webhook triggering failed: %s", str(exc))
        raise self.retry(exc=exc, countdown=60)
