# packages/zeroque_common/zeroque_common/events/tasks.py
"""
Celery tasks for ZeroQue event processing
"""
import logging
import json
from typing import Dict, Any
from celery import current_task
from zeroque_common.events.celery_app import celery_app
from zeroque_common.events.bus import Event, EventType
from zeroque_common.db.session import SessionLocal
from sqlalchemy import text

log = logging.getLogger("event_tasks")

@celery_app.task(bind=True, max_retries=3)
def process_order_event(self, event_data: Dict[str, Any]):
    """Process order-related events"""
    try:
        event_type = EventType(event_data["event_type"])
        tenant_id = event_data["tenant_id"]
        order_id = event_data["data"]["order_id"]
        
        log.info("Processing order event: %s for order %s", event_type.value, order_id)
        
        if event_type == EventType.ORDER_CREATED:
            # Update inventory
            celery_app.send_task(
                "zeroque_common.events.tasks.update_inventory_from_order",
                args=[event_data],
                queue="inventory"
            )
            
            # Send notifications
            celery_app.send_task(
                "zeroque_common.events.notification_tasks.send_order_notification",
                args=[event_data],
                queue="notifications"
            )
            
            # Update usage metrics
            celery_app.send_task(
                "zeroque_common.events.tasks.update_usage_metrics",
                args=[event_data],
                queue="analytics"
            )
        
        elif event_type == EventType.ORDER_COMPLETED:
            # Update ledger
            celery_app.send_task(
                "zeroque_common.events.tasks.update_ledger_from_order",
                args=[event_data],
                queue="billing"
            )
            
            # Trigger webhooks
            celery_app.send_task(
                "zeroque_common.events.webhook_tasks.trigger_order_webhooks",
                args=[event_data],
                queue="webhooks"
            )
        
        return {"status": "success", "event_type": event_type.value}
        
    except Exception as exc:
        log.error("Order event processing failed: %s", str(exc))
        raise self.retry(exc=exc, countdown=60)

@celery_app.task(bind=True, max_retries=3)
def process_inventory_event(self, event_data: Dict[str, Any]):
    """Process inventory-related events"""
    try:
        event_type = EventType(event_data["event_type"])
        tenant_id = event_data["tenant_id"]
        store_id = event_data["store_id"]
        sku = event_data["data"]["sku"]
        
        log.info("Processing inventory event: %s for SKU %s", event_type.value, sku)
        
        if event_type == EventType.INVENTORY_LOW_STOCK:
            # Send low stock alerts
            celery_app.send_task(
                "zeroque_common.events.notification_tasks.send_low_stock_alert",
                args=[event_data],
                queue="notifications"
            )
            
            # Update pricing (low stock might affect pricing)
            celery_app.send_task(
                "zeroque_common.events.pricing_tasks.recalculate_pricing",
                args=[event_data],
                queue="pricing"
            )
        
        elif event_type == EventType.INVENTORY_OUT_OF_STOCK:
            # Send out of stock alerts
            celery_app.send_task(
                "zeroque_common.events.notification_tasks.send_out_of_stock_alert",
                args=[event_data],
                queue="notifications"
            )
            
            # Disable product if needed
            celery_app.send_task(
                "zeroque_common.events.tasks.disable_out_of_stock_product",
                args=[event_data],
                queue="catalog"
            )
        
        return {"status": "success", "event_type": event_type.value}
        
    except Exception as exc:
        log.error("Inventory event processing failed: %s", str(exc))
        raise self.retry(exc=exc, countdown=60)

@celery_app.task(bind=True, max_retries=3)
def process_budget_event(self, event_data: Dict[str, Any]):
    """Process budget-related events"""
    try:
        event_type = EventType(event_data["event_type"])
        tenant_id = event_data["tenant_id"]
        cost_centre_id = event_data["data"]["cost_centre_id"]
        
        log.info("Processing budget event: %s for cost centre %s", event_type.value, cost_centre_id)
        
        if event_type == EventType.BUDGET_EXCEEDED:
            # Send budget exceeded notifications
            celery_app.send_task(
                "zeroque_common.events.notification_tasks.send_budget_exceeded_alert",
                args=[event_data],
                queue="notifications"
            )
            
            # Block new orders if hard limit
            celery_app.send_task(
                "zeroque_common.events.tasks.block_cost_centre_orders",
                args=[event_data],
                queue="orders"
            )
        
        elif event_type == EventType.APPROVAL_REQUESTED:
            # Send approval request notifications
            celery_app.send_task(
                "zeroque_common.events.notification_tasks.send_approval_request",
                args=[event_data],
                queue="notifications"
            )
        
        return {"status": "success", "event_type": event_type.value}
        
    except Exception as exc:
        log.error("Budget event processing failed: %s", str(exc))
        raise self.retry(exc=exc, countdown=60)

@celery_app.task(bind=True, max_retries=3)
def update_inventory_from_order(self, event_data: Dict[str, Any]):
    """Update inventory levels from order completion"""
    try:
        order_id = event_data["data"]["order_id"]
        tenant_id = event_data["tenant_id"]
        
        with SessionLocal() as db:
            # Get order items
            items = db.execute(text("""
                SELECT oi.sku, oi.qty, o.store_id
                FROM order_items oi
                JOIN orders o ON oi.order_id = o.order_id
                WHERE oi.order_id = :order_id AND o.tenant_id = :tenant_id
            """), {"order_id": order_id, "tenant_id": tenant_id}).all()
            
            for item in items:
                sku, qty, store_id = item
                
                # Update inventory
                db.execute(text("""
                    UPDATE inventory 
                    SET quantity = quantity - :qty,
                        updated_at = NOW()
                    WHERE store_id = :store_id AND sku = :sku
                """), {"qty": qty, "store_id": store_id, "sku": sku})
                
                # Check if low stock
                current_qty = db.execute(text("""
                    SELECT quantity FROM inventory 
                    WHERE store_id = :store_id AND sku = :sku
                """), {"store_id": store_id, "sku": sku}).scalar()
                
                if current_qty <= 0:
                    # Trigger out of stock event
                    celery_app.send_task(
                        "zeroque_common.events.tasks.publish_inventory_event",
                        args=[tenant_id, store_id, sku, "out_of_stock", {"quantity": current_qty}],
                        queue="events"
                    )
                elif current_qty <= 10:  # Low stock threshold
                    # Trigger low stock event
                    celery_app.send_task(
                        "zeroque_common.events.tasks.publish_inventory_event",
                        args=[tenant_id, store_id, sku, "low_stock", {"quantity": current_qty}],
                        queue="events"
                    )
            
            db.commit()
        
        return {"status": "success", "order_id": order_id}
        
    except Exception as exc:
        log.error("Inventory update failed: %s", str(exc))
        raise self.retry(exc=exc, countdown=60)

@celery_app.task(bind=True, max_retries=3)
def update_ledger_from_order(self, event_data: Dict[str, Any]):
    """Update ledger entries from order completion"""
    try:
        order_id = event_data["data"]["order_id"]
        tenant_id = event_data["tenant_id"]
        
        with SessionLocal() as db:
            # Get order details
            order = db.execute(text("""
                SELECT total_minor, currency, cost_centre_id, site_id, store_id
                FROM orders
                WHERE order_id = :order_id AND tenant_id = :tenant_id
            """), {"order_id": order_id, "tenant_id": tenant_id}).first()
            
            if order:
                total_minor, currency, cost_centre_id, site_id, store_id = order
                
                # Create ledger entry for cost centre spend
                db.execute(text("""
                    INSERT INTO ledger_entries (
                        tenant_id, account, entry_type, amount_minor, currency,
                        cost_centre_id, site_id, store_id, reference_type, reference_id,
                        description, occurred_at
                    ) VALUES (
                        :tenant_id, 'CostCentreSpend', 'debit', :amount, :currency,
                        :cost_centre_id, :site_id, :store_id, 'order', :order_id,
                        'Order completion', NOW()
                    )
                """), {
                    "tenant_id": tenant_id,
                    "amount": total_minor,
                    "currency": currency,
                    "cost_centre_id": cost_centre_id,
                    "site_id": site_id,
                    "store_id": store_id,
                    "order_id": order_id
                })
                
                db.commit()
        
        return {"status": "success", "order_id": order_id}
        
    except Exception as exc:
        log.error("Ledger update failed: %s", str(exc))
        raise self.retry(exc=exc, countdown=60)

@celery_app.task(bind=True, max_retries=3)
def update_usage_metrics(self, event_data: Dict[str, Any]):
    """Update usage metrics for subscription tracking"""
    try:
        tenant_id = event_data["tenant_id"]
        site_id = event_data.get("site_id")
        
        with SessionLocal() as db:
            # Update order count usage
            db.execute(text("""
                INSERT INTO usage_events (
                    tenant_id, site_id, event_type, event_data, occurred_at
                ) VALUES (
                    :tenant_id, :site_id, 'order_created', :data, NOW()
                )
            """), {
                "tenant_id": tenant_id,
                "site_id": site_id,
                "data": json.dumps(event_data["data"])
            })
            
            db.commit()
        
        return {"status": "success"}
        
    except Exception as exc:
        log.error("Usage metrics update failed: %s", str(exc))
        raise self.retry(exc=exc, countdown=60)

@celery_app.task(bind=True, max_retries=3)
def publish_inventory_event(self, tenant_id: str, store_id: str, sku: str, event_type: str, data: Dict[str, Any]):
    """Publish inventory events to the event bus"""
    try:
        from zeroque_common.events.integration import event_publisher
        from zeroque_common.events.bus import EventType
        import asyncio
        
        event_type_enum = EventType.INVENTORY_LOW_STOCK if event_type == "low_stock" else EventType.INVENTORY_OUT_OF_STOCK
        
        # Run async function in sync context
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(event_publisher.publish_inventory_event(
                event_type=event_type_enum,
                tenant_id=tenant_id,
                store_id=store_id,
                sku=sku,
                **data
            ))
            return {"status": "success", "event_type": event_type, "result": result}
        finally:
            loop.close()
        
    except Exception as exc:
        log.error("Inventory event publishing failed: %s", str(exc))
        raise self.retry(exc=exc, countdown=60)

@celery_app.task(bind=True, max_retries=3)
def block_cost_centre_orders(self, event_data: Dict[str, Any]):
    """Block new orders for cost centre when budget exceeded"""
    try:
        cost_centre_id = event_data["data"]["cost_centre_id"]
        tenant_id = event_data["tenant_id"]
        
        with SessionLocal() as db:
            # Update cost centre to block orders
            db.execute(text("""
                UPDATE cost_centres 
                SET hard_block = true, updated_at = NOW()
                WHERE cost_centre_id = :cost_centre_id AND tenant_id = :tenant_id
            """), {"cost_centre_id": cost_centre_id, "tenant_id": tenant_id})
            
            db.commit()
        
        return {"status": "success", "cost_centre_id": cost_centre_id}
        
    except Exception as exc:
        log.error("Cost centre blocking failed: %s", str(exc))
        raise self.retry(exc=exc, countdown=60)
