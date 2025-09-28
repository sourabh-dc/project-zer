# packages/zeroque_common/zeroque_common/events/bus.py
"""
ZeroQue Event Bus - Async event processing system using Redis Streams and Celery
"""
import json
import logging
import asyncio
from typing import Dict, Any, Optional, List, Callable
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from enum import Enum
import redis
import os

log = logging.getLogger("event_bus")

class EventType(Enum):
    """Event types in the ZeroQue system"""
    # Order Events
    ORDER_CREATED = "order.created"
    ORDER_UPDATED = "order.updated"
    ORDER_COMPLETED = "order.completed"
    ORDER_CANCELLED = "order.cancelled"
    
    # Inventory Events
    INVENTORY_UPDATED = "inventory.updated"
    INVENTORY_LOW_STOCK = "inventory.low_stock"
    INVENTORY_OUT_OF_STOCK = "inventory.out_of_stock"
    INVENTORY_MOVEMENT = "inventory.movement"
    
    # Pricing Events
    PRICE_CALCULATED = "price.calculated"
    PRICE_RULE_APPLIED = "price.rule_applied"
    PROMOTION_ACTIVATED = "promotion.activated"
    PRICE_CHANGED = "price.changed"
    
    # User Events
    USER_LOGIN = "user.login"
    USER_LOGOUT = "user.logout"
    USER_ROLE_CHANGED = "user.role_changed"
    USER_CREATED = "user.created"
    USER_UPDATED = "user.updated"
    
    # Budget Events
    BUDGET_EXCEEDED = "budget.exceeded"
    BUDGET_WARNING = "budget.warning"
    BUDGET_UPDATED = "budget.updated"
    APPROVAL_REQUESTED = "approval.requested"
    APPROVAL_GRANTED = "approval.granted"
    APPROVAL_DENIED = "approval.denied"
    
    # Subscription Events
    SUBSCRIPTION_CREATED = "subscription.created"
    SUBSCRIPTION_UPDATED = "subscription.updated"
    SUBSCRIPTION_CANCELLED = "subscription.cancelled"
    USAGE_LIMIT_EXCEEDED = "usage.limit_exceeded"
    USAGE_RECORDED = "usage.recorded"
    
    # Webhook Events
    WEBHOOK_RECEIVED = "webhook.received"
    WEBHOOK_PROCESSED = "webhook.processed"
    WEBHOOK_FAILED = "webhook.failed"
    
    # Notification Events
    NOTIFICATION_SENT = "notification.sent"
    NOTIFICATION_DELIVERED = "notification.delivered"
    NOTIFICATION_FAILED = "notification.failed"
    
    # Catalog Events
    PRODUCT_CREATED = "product.created"
    PRODUCT_UPDATED = "product.updated"
    PRODUCT_DELETED = "product.deleted"
    CATEGORY_CREATED = "category.created"
    CATEGORY_UPDATED = "category.updated"
    
    # Provisioning Events
    SITE_PROVISIONED = "site.provisioned"
    SITE_UPDATED = "site.updated"
    STORE_PROVISIONED = "store.provisioned"
    STORE_UPDATED = "store.updated"
    TENANT_CREATED = "tenant.created"
    TENANT_UPDATED = "tenant.updated"
    
    # Entry Events
    ENTRY_CODE_GENERATED = "entry.code_generated"
    ENTRY_CODE_VALIDATED = "entry.code_validated"
    ENTRY_CODE_EXPIRED = "entry.code_expired"
    ENTRY_RATE_LIMITED = "entry.rate_limited"
    
    # Identity Events
    AUTHENTICATION_SUCCESS = "auth.success"
    AUTHENTICATION_FAILED = "auth.failed"
    PERMISSION_CHECKED = "permission.checked"
    ROLE_ASSIGNED = "role.assigned"
    ROLE_REVOKED = "role.revoked"
    
    # Billing Events
    INVOICE_CREATED = "invoice.created"
    INVOICE_PAID = "invoice.paid"
    PAYMENT_PROCESSED = "payment.processed"
    PAYMENT_FAILED = "payment.failed"
    LEDGER_ENTRY_CREATED = "ledger.entry_created"
    
    # System Events
    SERVICE_STARTED = "service.started"
    SERVICE_STOPPED = "service.stopped"
    HEALTH_CHECK_FAILED = "health.check_failed"
    CONFIGURATION_CHANGED = "config.changed"
    MAINTENANCE_MODE_ENABLED = "maintenance.enabled"
    MAINTENANCE_MODE_DISABLED = "maintenance.disabled"

@dataclass
class Event:
    """Event structure for the event bus"""
    event_type: EventType
    tenant_id: str
    site_id: Optional[str] = None
    store_id: Optional[str] = None
    user_id: Optional[str] = None
    data: Dict[str, Any] = None
    metadata: Dict[str, Any] = None
    timestamp: datetime = None
    event_id: Optional[str] = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc)
        if self.data is None:
            self.data = {}
        if self.metadata is None:
            self.metadata = {}
        if self.event_id is None:
            self.event_id = f"{self.event_type.value}_{self.timestamp.isoformat()}_{self.tenant_id}"

class EventBus:
    """Main event bus for ZeroQue system"""
    
    def __init__(self, redis_url: str = None):
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:4000/0")
        self.redis_client = redis.from_url(self.redis_url, decode_responses=True)
        self.stream_name = "zeroque:events"
        self.consumer_group = "zeroque_consumers"
        self.consumer_name = f"consumer_{os.getpid()}"
        self._handlers: Dict[EventType, List[Callable]] = {}
        self._running = False
        
    async def publish(self, event: Event) -> str:
        """Publish an event to the event bus"""
        try:
            # Convert event to dict for Redis storage
            event_data = {
                "event_type": event.event_type.value,
                "tenant_id": event.tenant_id,
                "site_id": event.site_id or "",
                "store_id": event.store_id or "",
                "user_id": event.user_id or "",
                "data": json.dumps(event.data),
                "metadata": json.dumps(event.metadata),
                "timestamp": event.timestamp.isoformat(),
                "event_id": event.event_id
            }
            
            # Add to Redis Stream
            message_id = self.redis_client.xadd(self.stream_name, event_data)
            
            log.info("Event published: %s (ID: %s)", event.event_type.value, message_id)
            return message_id
            
        except Exception as e:
            log.error("Failed to publish event %s: %s", event.event_type.value, str(e))
            raise
    
    def subscribe(self, event_type: EventType, handler: Callable[[Event], None]):
        """Subscribe to events of a specific type"""
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)
        log.info("Subscribed handler to event type: %s", event_type.value)
    
    async def start_consumer(self):
        """Start consuming events from the stream"""
        self._running = True
        
        # Create consumer group if it doesn't exist
        try:
            self.redis_client.xgroup_create(self.stream_name, self.consumer_group, id="0", mkstream=True)
        except redis.exceptions.ResponseError:
            # Group already exists
            pass
        
        log.info("Starting event consumer: %s", self.consumer_name)
        
        while self._running:
            try:
                # Read from stream
                messages = self.redis_client.xreadgroup(
                    self.consumer_group,
                    self.consumer_name,
                    {self.stream_name: ">"},
                    count=10,
                    block=1000
                )
                
                for stream, msgs in messages:
                    for msg_id, fields in msgs:
                        await self._process_message(msg_id, fields)
                        
            except Exception as e:
                log.error("Error consuming events: %s", str(e))
                await asyncio.sleep(1)
    
    async def _process_message(self, msg_id: str, fields: Dict[str, str]):
        """Process a single event message"""
        try:
            # Parse event from Redis fields
            event = Event(
                event_type=EventType(fields["event_type"]),
                tenant_id=fields["tenant_id"],
                site_id=fields.get("site_id") or None,
                store_id=fields.get("store_id") or None,
                user_id=fields.get("user_id") or None,
                data=json.loads(fields["data"]),
                metadata=json.loads(fields["metadata"]),
                timestamp=datetime.fromisoformat(fields["timestamp"]),
                event_id=fields["event_id"]
            )
            
            # Call registered handlers
            handlers = self._handlers.get(event.event_type, [])
            for handler in handlers:
                try:
                    if asyncio.iscoroutinefunction(handler):
                        await handler(event)
                    else:
                        handler(event)
                except Exception as e:
                    log.error("Handler error for event %s: %s", event.event_type.value, str(e))
            
            # Acknowledge message
            self.redis_client.xack(self.stream_name, self.consumer_group, msg_id)
            
        except Exception as e:
            log.error("Failed to process message %s: %s", msg_id, str(e))
    
    def stop_consumer(self):
        """Stop the event consumer"""
        self._running = False
        log.info("Event consumer stopped")

# Global event bus instance
event_bus = EventBus()

# Convenience functions
async def publish_event(event_type: EventType, tenant_id: str, **kwargs) -> str:
    """Publish an event to the event bus"""
    event = Event(event_type=event_type, tenant_id=tenant_id, **kwargs)
    return await event_bus.publish(event)

def subscribe_to_event(event_type: EventType, handler: Callable[[Event], None]):
    """Subscribe to events of a specific type"""
    event_bus.subscribe(event_type, handler)

async def start_event_consumer():
    """Start the event consumer"""
    await event_bus.start_consumer()

def stop_event_consumer():
    """Stop the event consumer"""
    event_bus.stop_consumer()

# Event factory functions for common events
def create_order_event(event_type: EventType, tenant_id: str, order_id: int, **kwargs) -> Event:
    """Create an order-related event"""
    return Event(
        event_type=event_type,
        tenant_id=tenant_id,
        data={"order_id": order_id, **kwargs}
    )

def create_inventory_event(event_type: EventType, tenant_id: str, store_id: str, sku: str, **kwargs) -> Event:
    """Create an inventory-related event"""
    return Event(
        event_type=event_type,
        tenant_id=tenant_id,
        store_id=store_id,
        data={"sku": sku, **kwargs}
    )

def create_user_event(event_type: EventType, tenant_id: str, user_id: str, **kwargs) -> Event:
    """Create a user-related event"""
    return Event(
        event_type=event_type,
        tenant_id=tenant_id,
        user_id=user_id,
        data=kwargs
    )

def create_budget_event(event_type: EventType, tenant_id: str, cost_centre_id: str, **kwargs) -> Event:
    """Create a budget-related event"""
    return Event(
        event_type=event_type,
        tenant_id=tenant_id,
        data={"cost_centre_id": cost_centre_id, **kwargs}
    )