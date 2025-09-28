# examples/enhanced_orders_service.py
"""
Enhanced Orders Service Example

This example shows how to integrate the enhanced communication patterns
into the existing orders service.
"""

import os
import asyncio
import logging
from fastapi import FastAPI, Body, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

from zeroque_common.communication import (
    ServiceBus, ServiceEvent, ServiceEventType, 
    CircuitBreaker, CircuitBreakerConfig
)
from zeroque_common.communication.service_bus import service_bus
from zeroque_common.communication.circuit_breaker import service_circuit_breaker

# Service configuration
SERVICE_NAME = "orders"
app = FastAPI(title="Enhanced ZeroQue Orders Service", version="1.0.0")

# Initialize enhanced communication
service_bus = ServiceBus(service_name=SERVICE_NAME)
circuit_breaker_config = CircuitBreakerConfig(
    failure_threshold=3,
    timeout=30,
    success_threshold=2
)

# Request models
class OrderItem(BaseModel):
    sku: str
    qty: int

class CreateOrderRequest(BaseModel):
    tenant_id: str
    site_id: str
    store_id: str
    shopper_id: str
    currency: str
    items: List[OrderItem]
    payment_method: str = "trade"

class OrderResponse(BaseModel):
    order_id: str
    status: str
    total_minor: int
    currency: str
    created_at: datetime

# Event handlers
@service_bus.subscribe_to_event(ServiceEventType.INVENTORY_UPDATED)
async def handle_inventory_update(event: ServiceEvent):
    """Handle inventory update events"""
    log.info(f"Received inventory update: {event.data}")
    # Update local inventory cache or trigger revalidation

@service_bus.subscribe_to_event(ServiceEventType.PRICE_CALCULATED)
async def handle_price_calculation(event: ServiceEvent):
    """Handle price calculation events"""
    log.info(f"Received price calculation: {event.data}")
    # Update local price cache

# Service startup
@app.on_event("startup")
async def startup():
    """Initialize service"""
    log.info(f"Starting enhanced {SERVICE_NAME} service")
    
    # Start event consumer
    await service_bus.start_consumer()
    
    # Publish service started event
    await service_bus.publish_to_service(
        target_service="observability",
        event_type=ServiceEventType.SERVICE_STARTED,
        data={
            "service_name": SERVICE_NAME,
            "version": "1.0.0",
            "startup_time": datetime.now().isoformat()
        }
    )

# Health check
@app.get("/health")
async def health():
    """Service health check"""
    return {
        "status": "ok",
        "service": SERVICE_NAME,
        "circuit_breakers": service_circuit_breaker.get_all_states(),
        "event_metrics": service_bus.get_service_metrics()
    }

# Enhanced order creation with saga pattern
@app.post("/orders", response_model=OrderResponse)
async def create_order(request: CreateOrderRequest = Body(...)):
    """Create order with enhanced communication patterns"""
    
    correlation_id = f"order_{datetime.now().isoformat()}"
    
    try:
        # Step 1: Validate inventory (with circuit breaker)
        inventory_valid = await validate_inventory_with_circuit_breaker(
            request.store_id, request.items, correlation_id
        )
        
        if not inventory_valid:
            raise HTTPException(status_code=400, detail="Insufficient inventory")
        
        # Step 2: Calculate pricing (with circuit breaker)
        pricing_data = await calculate_pricing_with_circuit_breaker(
            request.store_id, request.items, request.shopper_id, 
            request.currency, correlation_id
        )
        
        # Step 3: Reserve inventory
        await reserve_inventory(request.store_id, request.items, correlation_id)
        
        # Step 4: Create order
        order_id = f"ORD_{int(datetime.now().timestamp())}"
        total_minor = sum(item["total_minor"] for item in pricing_data["items"])
        
        # Step 5: Publish order created event
        await service_bus.publish_to_service(
            target_service="billing",
            event_type=ServiceEventType.ORDER_CREATED,
            data={
                "order_id": order_id,
                "tenant_id": request.tenant_id,
                "total_minor": total_minor,
                "currency": request.currency,
                "items": request.items,
                "correlation_id": correlation_id
            },
            correlation_id=correlation_id
        )
        
        # Step 6: Publish inventory update event
        await service_bus.publish_to_service(
            target_service="inventory",
            event_type=ServiceEventType.INVENTORY_RESERVED,
            data={
                "store_id": request.store_id,
                "items": request.items,
                "order_id": order_id,
                "correlation_id": correlation_id
            },
            correlation_id=correlation_id
        )
        
        return OrderResponse(
            order_id=order_id,
            status="created",
            total_minor=total_minor,
            currency=request.currency,
            created_at=datetime.now()
        )
        
    except Exception as e:
        # Compensate for any partial operations
        await compensate_order_creation(request.store_id, request.items, correlation_id)
        raise HTTPException(status_code=500, detail=str(e))

async def validate_inventory_with_circuit_breaker(store_id: str, items: List[OrderItem], correlation_id: str) -> bool:
    """Validate inventory with circuit breaker protection"""
    
    async def check_inventory():
        # Call inventory service
        response = await service_circuit_breaker.call_service(
            service_name="inventory",
            url=f"{os.getenv('INVENTORY_BASE_URL', 'http://localhost:8202')}/catalog/inventory/validate",
            payload={
                "store_id": store_id,
                "items": [{"sku": item.sku, "qty": item.qty} for item in items],
                "correlation_id": correlation_id
            },
            config=circuit_breaker_config
        )
        return response.get("valid", False)
    
    try:
        return await check_inventory()
    except Exception as e:
        log.error(f"Inventory validation failed: {str(e)}")
        # Fallback: assume inventory is available (for demo purposes)
        return True

async def calculate_pricing_with_circuit_breaker(store_id: str, items: List[OrderItem], 
                                               user_id: str, currency: str, correlation_id: str) -> dict:
    """Calculate pricing with circuit breaker protection"""
    
    async def calculate_prices():
        pricing_data = {"items": []}
        
        for item in items:
            response = await service_circuit_breaker.call_service(
                service_name="pricing",
                url=f"{os.getenv('PRICING_BASE_URL', 'http://localhost:8209')}/pricing/calculate",
                payload={
                    "store_id": store_id,
                    "sku": item.sku,
                    "user_id": user_id,
                    "currency": currency,
                    "quantity": item.qty,
                    "correlation_id": correlation_id
                },
                config=circuit_breaker_config
            )
            
            pricing_data["items"].append({
                "sku": item.sku,
                "qty": item.qty,
                "unit_price_minor": response["final_price_minor"],
                "total_minor": response["final_price_minor"] * item.qty,
                "applied_rules": response.get("applied_rules", []),
                "applied_promotions": response.get("applied_promotions", [])
            })
        
        return pricing_data
    
    try:
        return await calculate_prices()
    except Exception as e:
        log.error(f"Pricing calculation failed: {str(e)}")
        # Fallback: use default pricing
        return {
            "items": [
                {
                    "sku": item.sku,
                    "qty": item.qty,
                    "unit_price_minor": 1000,  # Default price
                    "total_minor": 1000 * item.qty,
                    "applied_rules": [],
                    "applied_promotions": []
                }
                for item in items
            ]
        }

async def reserve_inventory(store_id: str, items: List[OrderItem], correlation_id: str):
    """Reserve inventory for order"""
    # This would typically call the inventory service
    log.info(f"Reserving inventory for store {store_id}: {items}")

async def compensate_order_creation(store_id: str, items: List[OrderItem], correlation_id: str):
    """Compensate for failed order creation"""
    log.info(f"Compensating order creation for store {store_id}: {items}")
    
    # Release any reserved inventory
    await service_bus.publish_to_service(
        target_service="inventory",
        event_type=ServiceEventType.INVENTORY_RELEASED,
        data={
            "store_id": store_id,
            "items": [{"sku": item.sku, "qty": item.qty} for item in items],
            "correlation_id": correlation_id,
            "reason": "order_creation_failed"
        },
        correlation_id=correlation_id
    )

# Circuit breaker status endpoint
@app.get("/circuit-breakers")
async def get_circuit_breakers():
    """Get circuit breaker status"""
    return service_circuit_breaker.get_all_states()

# Event metrics endpoint
@app.get("/events/metrics")
async def get_event_metrics():
    """Get event system metrics"""
    return service_bus.get_service_metrics()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8208)
