import time

from sqlalchemy import text

from services.catalog.models import ProductV2, ProductVariantV2
from services.catalog.repositories.outbox_repository import store_outbox_event
from ..utils.metrics import saga_total, saga_duration
from ..utils.cataog_logger import logger
from ..utils.rabbitmq import publish_to_rabbitmq
from ..utils.user_auth import check_permission


class VariantSaga:
    """Saga for product variant creation with compensation"""

    def __init__(self, db):
        self.db = db
        self.variant = None
        self.eid = None

    async def exec(self, variant_id, product_id, req, uctx):
        """Execute variant creation saga"""
        start = time.time()
        try:
            # Validate product exists
            product = self.db.query(ProductV2).filter(ProductV2.product_id == product_id).first()
            if not product:
                raise ValueError("Product not found")

            # Check permissions
            if not check_permission(uctx, "catalog.create"):
                raise ValueError("Insufficient permissions")

            # Create variant
            self.variant = ProductVariantV2(
                variant_id=variant_id,
                product_id=product_id,
                name=req.name,
                sku=req.sku,
                price_adjustment_minor=req.price_adjustment_minor,
                attributes=req.attributes,
                is_active=True
            )
            self.db.add(self.variant)
            self.db.commit()
            self.db.refresh(self.variant)

            # Create outbox event
            self.eid = store_outbox_event(self.db, "VARIANT_CREATED", str(product.tenant_id), str(variant_id), {
                "variant_id": str(variant_id),
                "product_id": str(product_id),
                "name": req.name
            })

            # Publish event
            publish_to_rabbitmq("VARIANT_CREATED", {
                "variant_id": str(variant_id),
                "product_id": str(product_id),
                "name": req.name
            }, str(product.tenant_id))

            saga_total.labels(type="variant", status="ok").inc()
            saga_duration.labels(type="variant").observe(time.time() - start)
            return {"variant_id": str(variant_id), "name": req.name, "created": True}

        except Exception as e:
            await self.comp()
            saga_total.labels(type="variant", status="fail").inc()
            raise

    async def comp(self):
        """Compensation logic"""
        try:
            if self.eid:
                self.db.execute(text("DELETE FROM outbox_events WHERE event_id = :id"), {"id": self.eid})
                self.db.commit()
            if self.variant:
                self.db.delete(self.variant)
                self.db.commit()
        except Exception as e:
            logger.error(f"Variant compensation failed: {e}")
            self.db.rollback()