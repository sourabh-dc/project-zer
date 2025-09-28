# packages/zeroque_common/zeroque_common/events/integration.py
"""
Event integration helpers for ZeroQue services
"""
import logging
import httpx
from typing import Dict, Any, Optional
from .bus import EventType

log = logging.getLogger("event_integration")

class EventPublisher:
    """Helper class for services to publish events"""
    
    def __init__(self, events_service_url: str = None):
        self.events_service_url = events_service_url or "http://localhost:8213"
        self.client = httpx.AsyncClient(timeout=30.0)
    
    async def publish_order_event(
        self, 
        event_type: EventType, 
        tenant_id: str, 
        order_id: int,
        site_id: Optional[str] = None,
        store_id: Optional[str] = None,
        user_id: Optional[str] = None,
        **data
    ):
        """Publish an order-related event"""
        try:
            response = await self.client.post(
                f"{self.events_service_url}/events/orders/{order_id}",
                params={
                    "event_type": event_type.value,
                    "tenant_id": tenant_id,
                    "site_id": site_id,
                    "store_id": store_id,
                    "user_id": user_id
                },
                json=data
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            log.error("Failed to publish order event: %s", str(e))
            raise
    
    async def publish_inventory_event(
        self,
        event_type: EventType,
        tenant_id: str,
        store_id: str,
        sku: str,
        **data
    ):
        """Publish an inventory-related event"""
        try:
            response = await self.client.post(
                f"{self.events_service_url}/events/inventory/{sku}",
                params={
                    "event_type": event_type.value,
                    "tenant_id": tenant_id,
                    "store_id": store_id
                },
                json=data
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            log.error("Failed to publish inventory event: %s", str(e))
            raise
    
    async def publish_event(
        self,
        event_type: EventType,
        tenant_id: str,
        site_id: Optional[str] = None,
        store_id: Optional[str] = None,
        user_id: Optional[str] = None,
        data: Dict[str, Any] = None,
        metadata: Dict[str, Any] = None
    ):
        """Publish a generic event"""
        try:
            payload = {
                "event_type": event_type.value,
                "tenant_id": tenant_id,
                "site_id": site_id,
                "store_id": store_id,
                "user_id": user_id,
                "data": data or {},
                "metadata": metadata or {}
            }
            
            response = await self.client.post(
                f"{self.events_service_url}/events/publish",
                json=payload
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            log.error("Failed to publish event: %s", str(e))
            raise
    
    async def close(self):
        """Close the HTTP client"""
        await self.client.aclose()

# Global event publisher instance
event_publisher = EventPublisher()

# Convenience functions for services
async def publish_order_created(tenant_id: str, order_id: int, **kwargs):
    """Publish order created event"""
    return await event_publisher.publish_order_event(
        EventType.ORDER_CREATED, tenant_id, order_id, **kwargs
    )

async def publish_order_completed(tenant_id: str, order_id: int, **kwargs):
    """Publish order completed event"""
    return await event_publisher.publish_order_event(
        EventType.ORDER_COMPLETED, tenant_id, order_id, **kwargs
    )

async def publish_inventory_updated(tenant_id: str, store_id: str, sku: str, **kwargs):
    """Publish inventory updated event"""
    return await event_publisher.publish_inventory_event(
        EventType.INVENTORY_UPDATED, tenant_id, store_id, sku, **kwargs
    )

async def publish_low_stock_alert(tenant_id: str, store_id: str, sku: str, **kwargs):
    """Publish low stock alert event"""
    return await event_publisher.publish_inventory_event(
        EventType.INVENTORY_LOW_STOCK, tenant_id, store_id, sku, **kwargs
    )

async def publish_budget_exceeded(tenant_id: str, cost_centre_id: str, **kwargs):
    """Publish budget exceeded event"""
    return await event_publisher.publish_event(
        EventType.BUDGET_EXCEEDED, tenant_id, data={"cost_centre_id": cost_centre_id, **kwargs}
    )

async def publish_approval_requested(tenant_id: str, cost_centre_id: str, **kwargs):
    """Publish approval requested event"""
    return await event_publisher.publish_event(
        EventType.APPROVAL_REQUESTED, tenant_id, data={"cost_centre_id": cost_centre_id, **kwargs}
    )

async def publish_user_login(tenant_id: str, user_id: str, **kwargs):
    """Publish user login event"""
    return await event_publisher.publish_event(
        EventType.USER_LOGIN, tenant_id, user_id=user_id, data=kwargs
    )

async def publish_product_created(tenant_id: str, sku: str, **kwargs):
    """Publish product created event"""
    return await event_publisher.publish_event(
        EventType.PRODUCT_CREATED, tenant_id, data={"sku": sku, **kwargs}
    )

async def publish_site_provisioned(tenant_id: str, site_id: str, **kwargs):
    """Publish site provisioned event"""
    return await event_publisher.publish_event(
        EventType.SITE_PROVISIONED, tenant_id, site_id=site_id, data=kwargs
    )

async def publish_entry_code_generated(tenant_id: str, site_id: str, store_id: str, user_id: str, **kwargs):
    """Publish entry code generated event"""
    return await event_publisher.publish_event(
        EventType.ENTRY_CODE_GENERATED, tenant_id, site_id=site_id, store_id=store_id, user_id=user_id, data=kwargs
    )

async def publish_auth_success(tenant_id: str, user_id: str, **kwargs):
    """Publish authentication success event"""
    return await event_publisher.publish_event(
        EventType.AUTHENTICATION_SUCCESS, tenant_id, user_id=user_id, data=kwargs
    )

async def publish_invoice_created(tenant_id: str, invoice_id: str, **kwargs):
    """Publish invoice created event"""
    return await event_publisher.publish_event(
        EventType.INVOICE_CREATED, tenant_id, data={"invoice_id": invoice_id, **kwargs}
    )

async def publish_price_calculated(tenant_id: str, store_id: str, sku: str, **kwargs):
    """Publish price calculated event"""
    return await event_publisher.publish_event(
        EventType.PRICE_CALCULATED, tenant_id, store_id=store_id, data={"sku": sku, **kwargs}
    )
