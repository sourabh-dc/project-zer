# services/cv_gateway/enhanced_webhook.py
import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum
import httpx
from sqlalchemy import text
from zeroque_common.db.session import SessionLocal
import redis

log = logging.getLogger("enhanced_webhook")

class ProcessingStatus(Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    DLQ = "dlq"

@dataclass
class WebhookMessage:
    id: str
    payload: Dict[str, Any]
    status: ProcessingStatus
    retry_count: int = 0
    max_retries: int = 3
    created_at: datetime = None
    updated_at: datetime = None
    error_message: Optional[str] = None
    processing_attempts: List[Dict] = None

class ProductNormalizer:
    """Normalize AiFi products to internal format"""
    
    def __init__(self):
        self.sku_mappings = {}  # Cache for SKU mappings
    
    def normalize_product(self, aifi_product: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize AiFi product to internal format"""
        normalized = {
            "sku": self._extract_sku(aifi_product),
            "name": aifi_product.get("name", ""),
            "description": aifi_product.get("description", ""),
            "category": aifi_product.get("category", "general"),
            "brand": aifi_product.get("brand", ""),
            "barcode": aifi_product.get("barcode", ""),
            "weight": aifi_product.get("weight", 0),
            "dimensions": aifi_product.get("dimensions", {}),
            "images": aifi_product.get("images", []),
            "tags": aifi_product.get("tags", []),
            "active": aifi_product.get("active", True),
            "metadata": {
                "aifi_product_id": aifi_product.get("id"),
                "aifi_store_id": aifi_product.get("storeId"),
                "normalized_at": datetime.utcnow().isoformat(),
                "source": "aifi_webhook"
            }
        }
        
        # Extract pricing information
        pricing = aifi_product.get("pricing", {})
        if pricing:
            normalized["base_price_minor"] = int(pricing.get("price", 0) * 100)  # Convert to minor units
            normalized["currency"] = pricing.get("currency", "GBP")
        
        # Extract inventory information
        inventory = aifi_product.get("inventory", {})
        if inventory:
            normalized["stock_quantity"] = inventory.get("quantity", 0)
            normalized["reorder_level"] = inventory.get("reorderLevel", 0)
        
        return normalized
    
    def _extract_sku(self, aifi_product: Dict[str, Any]) -> str:
        """Extract SKU from AiFi product"""
        # Try multiple fields for SKU
        sku_fields = ["sku", "productCode", "id", "externalId"]
        
        for field in sku_fields:
            if field in aifi_product and aifi_product[field]:
                return str(aifi_product[field])
        
        # Generate SKU from name if no SKU found
        name = aifi_product.get("name", "unknown")
        return f"AIFI-{name.upper().replace(' ', '-')[:20]}"

class EnhancedWebhookProcessor:
    """Enhanced webhook processor with retries, DLQ, and product normalization"""
    
    def __init__(self, redis_url: str = "redis://localhost:4000/0"):
        self.redis_client = redis.from_url(redis_url, decode_responses=True)
        self.product_normalizer = ProductNormalizer()
        self.max_retries = 3
        self.retry_delays = [1, 5, 15]  # seconds
        self.dlq_threshold = 3
        
    async def process_webhook(self, message_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Process webhook with retry logic and DLQ"""
        message = WebhookMessage(
            id=message_id,
            payload=payload,
            status=ProcessingStatus.PENDING,
            created_at=datetime.utcnow()
        )
        
        # Store message in Redis
        await self._store_message(message)
        
        # Process with retry logic
        for attempt in range(self.max_retries + 1):
            try:
                message.status = ProcessingStatus.PROCESSING
                message.retry_count = attempt
                message.updated_at = datetime.utcnow()
                
                await self._store_message(message)
                
                # Process the webhook
                result = await self._process_payload(payload)
                
                message.status = ProcessingStatus.COMPLETED
                message.updated_at = datetime.utcnow()
                await self._store_message(message)
                
                return result
                
            except Exception as e:
                log.error(f"Webhook processing attempt {attempt + 1} failed: {str(e)}")
                message.error_message = str(e)
                
                if attempt < self.max_retries:
                    # Wait before retry
                    await asyncio.sleep(self.retry_delays[attempt])
                else:
                    # Move to DLQ
                    message.status = ProcessingStatus.DLQ
                    message.updated_at = datetime.utcnow()
                    await self._store_message(message)
                    await self._move_to_dlq(message)
                    
                    return {
                        "ok": False,
                        "status": "dlq",
                        "reason": f"Max retries exceeded: {str(e)}",
                        "message_id": message_id
                    }
    
    async def _process_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Process the actual webhook payload"""
        event_type = payload.get("type", "unknown")
        
        if event_type == "product.created" or event_type == "product.updated":
            return await self._process_product_event(payload)
        elif event_type == "order.completed":
            return await self._process_order_event(payload)
        elif event_type == "inventory.updated":
            return await self._process_inventory_event(payload)
        else:
            log.warning(f"Unknown event type: {event_type}")
            return {"ok": True, "status": "ignored", "reason": f"Unknown event type: {event_type}"}
    
    async def _process_product_event(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Process product creation/update event"""
        product_data = payload.get("data", {})
        normalized_product = self.product_normalizer.normalize_product(product_data)
        
        # Store in database
        with SessionLocal() as db:
            # Upsert product
            db.execute(text("""
                INSERT INTO products (sku, name, description, category, brand, barcode, 
                                   weight, dimensions, images, tags, active, metadata)
                VALUES (:sku, :name, :description, :category, :brand, :barcode,
                       :weight, :dimensions, :images, :tags, :active, :metadata)
                ON CONFLICT (sku) DO UPDATE SET
                    name = EXCLUDED.name,
                    description = EXCLUDED.description,
                    category = EXCLUDED.category,
                    brand = EXCLUDED.brand,
                    barcode = EXCLUDED.barcode,
                    weight = EXCLUDED.weight,
                    dimensions = EXCLUDED.dimensions,
                    images = EXCLUDED.images,
                    tags = EXCLUDED.tags,
                    active = EXCLUDED.active,
                    metadata = EXCLUDED.metadata,
                    updated_at = NOW()
            """), normalized_product)
            
            # Upsert global price if provided
            if "base_price_minor" in normalized_product:
                db.execute(text("""
                    INSERT INTO prices (sku, unit_minor, currency, active)
                    VALUES (:sku, :price, :currency, TRUE)
                    ON CONFLICT (sku, currency) DO UPDATE SET
                        unit_minor = EXCLUDED.unit_minor,
                        active = EXCLUDED.active,
                        updated_at = NOW()
                """), {
                    "sku": normalized_product["sku"],
                    "price": normalized_product["base_price_minor"],
                    "currency": normalized_product.get("currency", "GBP")
                })
            
            # Upsert inventory if provided
            if "stock_quantity" in normalized_product:
                store_id = normalized_product["metadata"].get("aifi_store_id")
                if store_id:
                    db.execute(text("""
                        INSERT INTO inventory (store_id, sku, quantity, reorder_level)
                        VALUES (:store_id, :sku, :quantity, :reorder_level)
                        ON CONFLICT (store_id, sku) DO UPDATE SET
                            quantity = EXCLUDED.quantity,
                            reorder_level = EXCLUDED.reorder_level,
                            updated_at = NOW()
                    """), {
                        "store_id": store_id,
                        "sku": normalized_product["sku"],
                        "quantity": normalized_product["stock_quantity"],
                        "reorder_level": normalized_product.get("reorder_level", 0)
                    })
            
            db.commit()
        
        # Trigger price calculation hook
        await self._trigger_price_hook(normalized_product["sku"], store_id)
        
        return {
            "ok": True,
            "status": "processed",
            "product_sku": normalized_product["sku"],
            "normalized": normalized_product
        }
    
    async def _process_order_event(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Process order completion event"""
        # This would integrate with the existing order processing logic
        # For now, just log and return success
        log.info(f"Order event received: {payload}")
        return {"ok": True, "status": "processed", "event": "order"}
    
    async def _process_inventory_event(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Process inventory update event"""
        inventory_data = payload.get("data", {})
        
        with SessionLocal() as db:
            db.execute(text("""
                INSERT INTO inventory_movements (store_id, sku, movement_type, quantity, 
                                               reference_type, reference_id, description)
                VALUES (:store_id, :sku, :movement_type, :quantity, 
                       :reference_type, :reference_id, :description)
            """), {
                "store_id": inventory_data.get("storeId"),
                "sku": inventory_data.get("sku"),
                "movement_type": "adjustment",
                "quantity": inventory_data.get("quantityChange", 0),
                "reference_type": "aifi_webhook",
                "reference_id": payload.get("id"),
                "description": f"AiFi inventory update: {inventory_data.get('reason', 'unknown')}"
            })
            db.commit()
        
        return {"ok": True, "status": "processed", "event": "inventory"}
    
    async def _trigger_price_hook(self, sku: str, store_id: Optional[str] = None):
        """Trigger price calculation hook for new/updated products"""
        try:
            # Call pricing service to calculate effective prices
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "http://localhost:8209/pricing/calculate",
                    json={
                        "store_id": store_id or "default",
                        "sku": sku,
                        "user_id": "system",
                        "currency": "GBP",
                        "quantity": 1,
                        "force_recalculate": True
                    },
                    timeout=10.0
                )
                
                if response.status_code == 200:
                    pricing_data = response.json()
                    log.info(f"Price hook triggered for SKU {sku}: {pricing_data['final_price_minor']} {pricing_data['currency']}")
                else:
                    log.warning(f"Price hook failed for SKU {sku}: {response.status_code}")
                    
        except Exception as e:
            log.error(f"Price hook error for SKU {sku}: {str(e)}")
    
    async def _store_message(self, message: WebhookMessage):
        """Store message in Redis"""
        message_data = {
            "id": message.id,
            "payload": message.payload,
            "status": message.status.value,
            "retry_count": message.retry_count,
            "max_retries": message.max_retries,
            "created_at": message.created_at.isoformat() if message.created_at else None,
            "updated_at": message.updated_at.isoformat() if message.updated_at else None,
            "error_message": message.error_message,
            "processing_attempts": message.processing_attempts or []
        }
        
        self.redis_client.hset(
            f"webhook_message:{message.id}",
            mapping=message_data
        )
    
    async def _move_to_dlq(self, message: WebhookMessage):
        """Move failed message to Dead Letter Queue"""
        dlq_data = {
            "id": message.id,
            "payload": json.dumps(message.payload),
            "error_message": message.error_message,
            "retry_count": message.retry_count,
            "created_at": message.created_at.isoformat() if message.created_at else None,
            "moved_to_dlq_at": datetime.utcnow().isoformat()
        }
        
        self.redis_client.lpush("webhook_dlq", json.dumps(dlq_data))
        log.error(f"Message {message.id} moved to DLQ after {message.retry_count} retries")
    
    async def get_dlq_messages(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get messages from Dead Letter Queue"""
        messages = []
        for _ in range(limit):
            message_json = self.redis_client.rpop("webhook_dlq")
            if not message_json:
                break
            messages.append(json.loads(message_json))
        return messages
    
    async def reprocess_dlq_message(self, message_id: str) -> Dict[str, Any]:
        """Reprocess a message from DLQ"""
        message_data = self.redis_client.hgetall(f"webhook_message:{message_id}")
        if not message_data:
            return {"ok": False, "reason": "Message not found"}
        
        payload = json.loads(message_data["payload"])
        return await self.process_webhook(message_id, payload)
