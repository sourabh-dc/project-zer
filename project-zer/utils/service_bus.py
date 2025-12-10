"""
Azure Service Bus integration for event publishing
"""
import os
import json
from typing import Dict, Any, Optional
from utils.logger import logger

# Initialize Azure Service Bus client if connection string is available
SERVICE_BUS_CONN = os.getenv("SERVICE_BUS_CONNECTION_STRING")
service_bus_client = None

if SERVICE_BUS_CONN:
    try:
        from azure.servicebus import ServiceBusClient, ServiceBusMessage
        service_bus_client = ServiceBusClient.from_connection_string(SERVICE_BUS_CONN)
        logger.info("✅ Azure Service Bus client initialized")
    except ImportError:
        logger.warning("⚠️  azure-servicebus package not installed. Install with: pip install azure-servicebus")
    except Exception as e:
        logger.warning(f"⚠️  Service Bus initialization failed: {e}")
else:
    logger.warning("⚠️  SERVICE_BUS_CONNECTION_STRING not set. Service Bus disabled.")


def publish_event(topic: str, data: Dict[str, Any], correlation_id: Optional[str] = None) -> bool:
    """
    Publish an event to Azure Service Bus topic
    
    Args:
        topic: Topic name (e.g., "spending.events", "order.events")
        data: Event payload dictionary
        correlation_id: Optional correlation ID for tracking
    
    Returns:
        True if published successfully, False otherwise
    """
    if not service_bus_client:
        logger.warning(f"Service Bus not available. Event not published to {topic}: {data}")
        return False
    
    try:
        from azure.servicebus import ServiceBusMessage
        
        message_body = json.dumps(data)
        message = ServiceBusMessage(message_body)
        
        if correlation_id:
            message.correlation_id = correlation_id
        
        # Add custom properties
        message.application_properties = {
            "event_type": data.get("event_type", "unknown"),
            "tenant_id": data.get("tenant_id"),
        }
        
        with service_bus_client:
            sender = service_bus_client.get_topic_sender(topic_name=topic)
            with sender:
                sender.send_messages(message)
                logger.info(f"✅ Published event to {topic}: {data.get('event_type')}")
                return True
                
    except Exception as e:
        logger.error(f"❌ Failed to publish event to {topic}: {e}")
        return False


def publish_spending_event(
    event_type: str,
    user_id: str,
    cost_centre_id: str,
    amount_minor: int,
    order_id: Optional[str] = None,
    approval_request_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> bool:
    """
    Convenience method to publish spending-related events
    
    Args:
        event_type: Type of spending event (budget_allocated, budget_spent, order_created)
        user_id: User UUID
        cost_centre_id: Cost centre UUID
        amount_minor: Amount in minor units
        order_id: Optional order UUID
        approval_request_id: Optional approval request UUID
        metadata: Optional additional metadata
    
    Returns:
        True if published successfully
    """
    from datetime import datetime, timezone
    
    event_data = {
        "event_type": event_type,
        "user_id": user_id,
        "cost_centre_id": cost_centre_id,
        "amount_minor": amount_minor,
        "order_id": order_id,
        "approval_request_id": approval_request_id,
        "metadata": metadata or {},
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    
    return publish_event("spending.events", event_data, correlation_id=order_id or approval_request_id)


def publish_order_event(
    event_type: str,
    order_id: str,
    tenant_id: str,
    customer_id: str,
    total_amount_minor: int,
    currency: str,
    metadata: Optional[Dict[str, Any]] = None
) -> bool:
    """
    Convenience method to publish order-related events
    
    Args:
        event_type: Type of order event (order_created, order_fulfilled, order_cancelled)
        order_id: Order UUID
        tenant_id: Tenant UUID
        customer_id: Customer/User UUID
        total_amount_minor: Total amount in minor units
        currency: Currency code
        metadata: Optional additional metadata
    
    Returns:
        True if published successfully
    """
    from datetime import datetime, timezone
    
    event_data = {
        "event_type": event_type,
        "order_id": order_id,
        "tenant_id": tenant_id,
        "customer_id": customer_id,
        "total_amount_minor": total_amount_minor,
        "currency": currency,
        "metadata": metadata or {},
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    
    return publish_event("order.events", event_data, correlation_id=order_id)

