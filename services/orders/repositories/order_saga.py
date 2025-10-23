import time
import uuid

from sqlalchemy import text
from ..models import OrderV2, OrderItemV2
from ..utils.metrics import saga_total, saga_duration
from ..utils.orders_logger import logger


class OrderSaga:
    """Saga for order creation with compensation"""

    def __init__(self, db):
        self.db = db
        self.order = None
        self.order_items = []
        self.eid = None

    async def exec(self, order_id, tenant_id, req, uctx):
        """Execute order creation saga"""
        start = time.time()
        try:
            # Validate and convert UUIDs
            customer_uuid = uuid.UUID(req.customer_id) if req.customer_id and req.customer_id.strip() else uctx.get(
                "user_id")
            if isinstance(customer_uuid, str):
                customer_uuid = uuid.UUID(customer_uuid) if customer_uuid and customer_uuid.strip() else uuid.uuid4()

            site_uuid = uuid.UUID(req.site_id) if req.site_id and req.site_id.strip() else None
            store_uuid = uuid.UUID(req.store_id) if req.store_id and req.store_id.strip() else None

            # Create order
            self.order = OrderV2(
                order_id=order_id,
                tenant_id=tenant_id,
                site_id=site_uuid,
                store_id=store_uuid,
                customer_id=customer_uuid,
                order_number=f"ORD-{int(time.time())}",
                order_type=req.order_type,
                shipping_address=req.shipping_address,
                billing_address=req.billing_address
            )
            self.db.add(self.order)
            self.db.flush()  # FLUSH order first to ensure it exists before adding items

            # Calculate total amount
            total_amount = 0
            for item_data in req.items:
                item = OrderItemV2(
                    order_id=order_id,
                    product_id=item_data['product_id'],
                    variant_id=item_data.get('variant_id'),
                    quantity=item_data['quantity'],
                    unit_price_minor=item_data['unit_price_minor'],
                    total_price_minor=item_data['quantity'] * item_data['unit_price_minor']
                )
                self.order_items.append(item)
                self.db.add(item)
                total_amount += item.total_price_minor

            self.order.total_amount_minor = total_amount
            self.db.commit()
            self.db.refresh(self.order)

            # Store outbox event (DISABLED for now to fix core functionality)
            # self.eid = store_outbox(self.db, "ORDER_CREATED", str(tenant_id), str(order_id), {
            #     "order_id": str(order_id),
            #     "customer_id": req.customer_id,
            #     "total_amount_minor": total_amount
            # })

            # Publish event
            # publish_outbox_events.delay()

            # Audit log (DISABLED for now to fix core functionality)
            # audit(self.db, str(tenant_id), uctx["user_id"], "CREATE", "order", str(order_id), {
            #     "order_number": self.order.order_number,
            #     "total_amount_minor": total_amount
            # })

            saga_total.labels(type="order", status="ok").inc()
            saga_duration.labels(type="order").observe(time.time() - start)

            return {
                "order_id": str(order_id),
                "order_number": self.order.order_number,
                "total_amount_minor": total_amount,
                "created": True
            }

        except Exception as e:
            await self.comp()
            saga_total.labels(type="order", status="fail").inc()
            raise

    async def comp(self):
        """Compensation logic"""
        try:
            if self.eid:
                self.db.execute(text("DELETE FROM outbox_events WHERE event_id = :id"), {"id": self.eid})
                self.db.commit()

            if self.order:
                self.db.delete(self.order)
                self.db.commit()

        except Exception as e:
            logger.error("Compensation failed", error=str(e))
            self.db.rollback()