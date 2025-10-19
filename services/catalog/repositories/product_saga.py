import time

from sqlalchemy import text

from services.catalog.models import ProductV2
from services.catalog.repositories.outbox_repository import store_outbox_event
from ..utils.metrics import saga_total, saga_duration
from ..utils.cataog_logger import logger
from ..tasks.celery_tasks import publish_outbox_events
from .audit_repository import audit



class ProductSaga:
    """Saga for product creation with compensation"""

    def __init__(self, db):
        self.db = db
        self.product = None
        self.eid = None

    async def exec(self, product_id, tenant_id, req, uctx):
        """Execute product creation saga"""
        start = time.time()
        try:
            # Create product
            self.product = ProductV2(
                product_id=product_id,
                tenant_id=tenant_id,
                vendor_id=req.vendor_id,
                name=req.name,
                description=req.description,
                sku=req.sku,
                category_id=req.category_id,
                brand=req.brand,
                base_price_minor=req.base_price_minor,
                currency=req.currency,
                weight_grams=req.weight_grams,
                dimensions_cm=req.dimensions_cm,
                metadata=req.metadata
            )
            self.db.add(self.product)
            self.db.commit()
            self.db.refresh(self.product)

            # Store outbox event
            self.eid = store_outbox_event(self.db, "PRODUCT_CREATED", str(tenant_id), str(product_id), {
                "product_id": str(product_id),
                "name": req.name,
                "sku": req.sku,
                "vendor_id": req.vendor_id
            })

            # Publish event
            publish_outbox_events.delay()

            # Audit log
            audit(self.db, str(tenant_id), uctx["user_id"], "CREATE", "product", str(product_id), {
                "name": req.name,
                "sku": req.sku,
                "vendor_id": req.vendor_id
            })

            saga_total.labels(type="product", status="ok").inc()
            saga_duration.labels(type="product").observe(time.time() - start)

            return {
                "product_id": str(product_id),
                "name": req.name,
                "sku": req.sku,
                "vendor_id": req.vendor_id,
                "created": True
            }

        except Exception as e:
            await self.comp()
            saga_total.labels(type="product", status="fail").inc()
            raise

    async def comp(self):
        """Compensation logic"""
        try:
            if self.eid:
                self.db.execute(text("DELETE FROM outbox_events WHERE event_id = :id"), {"id": self.eid})
                self.db.commit()

            if self.product:
                self.db.delete(self.product)
                self.db.commit()

        except Exception as e:
            logger.error("Compensation failed", error=str(e))
            self.db.rollback()