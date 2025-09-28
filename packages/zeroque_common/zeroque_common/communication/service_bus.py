# packages/zeroque_common/zeroque_common/communication/service_bus.py
"""
Enhanced Service Bus for ZeroQue Microservices

This module provides service-to-service communication patterns
building on top of Redis Streams and Celery.
"""

import os
import json
import redis
import asyncio
import logging
from datetime import datetime
from typing import Dict, Any, Optional, Callable, List
from dataclasses import dataclass, asdict
from enum import Enum

log = logging.getLogger(__name__)

class ServiceEventType(Enum):
    """Service-specific event types"""
    # Order events
    ORDER_CREATED = "order.created"
    ORDER_UPDATED = "order.updated"
    ORDER_CANCELLED = "order.cancelled"
    ORDER_COMPLETED = "order.completed"
    
    # Inventory events
    INVENTORY_UPDATED = "inventory.updated"
    INVENTORY_LOW = "inventory.low"
    INVENTORY_RESERVED = "inventory.reserved"
    INVENTORY_RELEASED = "inventory.released"
    
    # Pricing events
    PRICE_CALCULATED = "price.calculated"
    PRICE_RULE_APPLIED = "price.rule_applied"
    PROMOTION_APPLIED = "promotion.applied"
    
    # Billing events
    INVOICE_CREATED = "invoice.created"
    PAYMENT_PROCESSED = "payment.processed"
    PAYMENT_FAILED = "payment.failed"
    
    # User events
    USER_CREATED = "user.created"
    USER_UPDATED = "user.updated"
    USER_AUTHENTICATED = "user.authenticated"
    
    # System events
    SERVICE_HEALTH_CHECK = "service.health_check"
    SERVICE_STARTED = "service.started"
    SERVICE_STOPPED = "service.stopped"

@dataclass
class ServiceEvent:
    """Service event data structure"""
    event_type: ServiceEventType
    service_name: str
    correlation_id: str
    data: Dict[str, Any]
    metadata: Dict[str, Any]
    timestamp: datetime
    event_id: Optional[str] = None
    
    def __post_init__(self):
        if self.event_id is None:
            self.event_id = f"{self.service_name}_{self.event_type.value}_{self.timestamp.isoformat()}"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for Redis storage"""
        return {
            "event_type": self.event_type.value,
            "service_name": self.service_name,
            "correlation_id": self.correlation_id,
            "data": json.dumps(self.data),
            "metadata": json.dumps(self.metadata),
            "timestamp": self.timestamp.isoformat(),
            "event_id": self.event_id
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, str]) -> "ServiceEvent":
        """Create from Redis data"""
        return cls(
            event_type=ServiceEventType(data["event_type"]),
            service_name=data["service_name"],
            correlation_id=data["correlation_id"],
            data=json.loads(data["data"]),
            metadata=json.loads(data["metadata"]),
            timestamp=datetime.fromisoformat(data["timestamp"]),
            event_id=data["event_id"]
        )

class ServiceBus:
    """Enhanced service bus for microservice communication"""
    
    def __init__(self, redis_url: str = None, service_name: str = None):
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:4000/0")
        self.redis_client = redis.from_url(self.redis_url, decode_responses=True)
        self.service_name = service_name or os.getenv("SERVICE_NAME", "unknown")
        
        # Service-specific streams
        self.service_streams = {
            "provisioning": "zeroque:provisioning:events",
            "catalog": "zeroque:catalog:events", 
            "orders": "zeroque:orders:events",
            "pricing": "zeroque:pricing:events",
            "billing": "zeroque:billing:events",
            "inventory": "zeroque:inventory:events",
            "identity": "zeroque:identity:events",
            "entry": "zeroque:entry:events",
            "notifications": "zeroque:notifications:events"
        }
        
        # Event handlers
        self._handlers: Dict[ServiceEventType, List[Callable]] = {}
        self._running = False
        
        log.info(f"ServiceBus initialized for service: {self.service_name}")
    
    async def publish_event(self, event: ServiceEvent) -> str:
        """Publish an event to the service bus"""
        try:
            stream_name = self.service_streams.get(event.service_name, f"zeroque:{event.service_name}:events")
            event_data = event.to_dict()
            
            message_id = self.redis_client.xadd(stream_name, event_data)
            
            log.info(f"Event published: {event.event_type.value} from {event.service_name} (ID: {message_id})")
            return message_id
            
        except Exception as e:
            log.error(f"Failed to publish event {event.event_type.value}: {str(e)}")
            raise
    
    async def publish_to_service(self, target_service: str, event_type: ServiceEventType, 
                                data: Dict[str, Any], correlation_id: str = None) -> str:
        """Publish an event to a specific service"""
        if correlation_id is None:
            correlation_id = f"{self.service_name}_{datetime.now().isoformat()}"
        
        event = ServiceEvent(
            event_type=event_type,
            service_name=target_service,
            correlation_id=correlation_id,
            data=data,
            metadata={"source_service": self.service_name},
            timestamp=datetime.now()
        )
        
        return await self.publish_event(event)
    
    def subscribe_to_event(self, event_type: ServiceEventType, handler: Callable[[ServiceEvent], None]):
        """Subscribe to events of a specific type"""
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)
        log.info(f"Subscribed handler to event type: {event_type.value}")
    
    def subscribe_to_service(self, service_name: str, handler: Callable[[ServiceEvent], None]):
        """Subscribe to all events from a specific service"""
        stream_name = self.service_streams.get(service_name, f"zeroque:{service_name}:events")
        consumer_group = f"{self.service_name}_consumers"
        
        async def service_handler():
            # Create consumer group
            try:
                self.redis_client.xgroup_create(stream_name, consumer_group, id="0", mkstream=True)
            except redis.exceptions.ResponseError:
                pass  # Group already exists
            
            log.info(f"Subscribed to service: {service_name}")
            
            while self._running:
                try:
                    messages = self.redis_client.xreadgroup(
                        consumer_group,
                        f"consumer_{os.getpid()}",
                        {stream_name: ">"},
                        count=10,
                        block=1000
                    )
                    
                    for stream, msgs in messages:
                        for msg_id, fields in msgs:
                            try:
                                event = ServiceEvent.from_dict(fields)
                                await self._process_event(event)
                                self.redis_client.xack(stream_name, consumer_group, msg_id)
                            except Exception as e:
                                log.error(f"Failed to process message {msg_id}: {str(e)}")
                                
                except Exception as e:
                    log.error(f"Error consuming events from {service_name}: {str(e)}")
                    await asyncio.sleep(1)
        
        # Start the handler
        asyncio.create_task(service_handler())
    
    async def _process_event(self, event: ServiceEvent):
        """Process an incoming event"""
        handlers = self._handlers.get(event.event_type, [])
        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(event)
                else:
                    handler(event)
            except Exception as e:
                log.error(f"Handler error for event {event.event_type.value}: {str(e)}")
    
    async def start_consumer(self):
        """Start consuming events from all subscribed services"""
        self._running = True
        log.info(f"Starting event consumer for service: {self.service_name}")
        
        # Start consuming from all service streams
        for service_name in self.service_streams.keys():
            if service_name != self.service_name:  # Don't consume our own events
                self.subscribe_to_service(service_name, self._process_event)
    
    def stop_consumer(self):
        """Stop the event consumer"""
        self._running = False
        log.info(f"Event consumer stopped for service: {self.service_name}")
    
    def get_service_metrics(self) -> Dict[str, Any]:
        """Get metrics for all service streams"""
        metrics = {}
        for service_name, stream_name in self.service_streams.items():
            try:
                info = self.redis_client.xinfo_stream(stream_name)
                metrics[service_name] = {
                    "length": info.get("length", 0),
                    "first_entry": info.get("first-entry"),
                    "last_entry": info.get("last-entry"),
                    "groups": info.get("groups", 0)
                }
            except redis.exceptions.ResponseError:
                metrics[service_name] = {"error": "Stream not found"}
        return metrics

# Global service bus instance
service_bus = ServiceBus()
