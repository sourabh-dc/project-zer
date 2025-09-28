# packages/zeroque_common/zeroque_common/events/catalog_tasks.py
"""
Celery tasks for catalog event processing
"""
import logging
from typing import Dict, Any
from celery import current_task
from zeroque_common.events.celery_app import celery_app
from zeroque_common.events.bus import EventType

log = logging.getLogger("catalog_tasks")

@celery_app.task(bind=True, max_retries=3)
def process_product_event(self, event_data: Dict[str, Any]):
    """Process product-related events"""
    try:
        event_type = EventType(event_data["event_type"])
        tenant_id = event_data["tenant_id"]
        sku = event_data["data"]["sku"]
        
        log.info("Processing product event: %s for SKU %s", event_type.value, sku)
        
        if event_type == EventType.PRODUCT_CREATED:
            # Update search index
            celery_app.send_task(
                "zeroque_common.events.catalog_tasks.update_search_index",
                args=[event_data],
                queue="search"
            )
            
            # Send notifications to catalog managers
            celery_app.send_task(
                "zeroque_common.events.notification_tasks.send_product_notification",
                args=[event_data],
                queue="notifications"
            )
            
        elif event_type == EventType.PRODUCT_UPDATED:
            # Update search index
            celery_app.send_task(
                "zeroque_common.events.catalog_tasks.update_search_index",
                args=[event_data],
                queue="search"
            )
            
            # Invalidate cache
            celery_app.send_task(
                "zeroque_common.events.catalog_tasks.invalidate_product_cache",
                args=[event_data],
                queue="cache"
            )
        
        return {"status": "success", "event_type": event_type.value}
        
    except Exception as exc:
        log.error("Product event processing failed: %s", str(exc))
        raise self.retry(exc=exc, countdown=60)

@celery_app.task(bind=True, max_retries=3)
def update_search_index(self, event_data: Dict[str, Any]):
    """Update search index for product"""
    try:
        sku = event_data["data"]["sku"]
        tenant_id = event_data["tenant_id"]
        
        log.info("Updating search index for SKU %s", sku)
        
        # Implementation would update search index (Elasticsearch, etc.)
        # For now, just log the action
        
        return {"status": "success", "sku": sku}
        
    except Exception as exc:
        log.error("Search index update failed: %s", str(exc))
        raise self.retry(exc=exc, countdown=60)

@celery_app.task(bind=True, max_retries=3)
def invalidate_product_cache(self, event_data: Dict[str, Any]):
    """Invalidate product cache"""
    try:
        sku = event_data["data"]["sku"]
        tenant_id = event_data["tenant_id"]
        
        log.info("Invalidating cache for SKU %s", sku)
        
        # Implementation would invalidate Redis cache
        # For now, just log the action
        
        return {"status": "success", "sku": sku}
        
    except Exception as exc:
        log.error("Cache invalidation failed: %s", str(exc))
        raise self.retry(exc=exc, countdown=60)
