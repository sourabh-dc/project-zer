from datetime import datetime, timezone
import time
from typing import Dict

from sqlalchemy import text

from services.pricing.models import CalculatedPriceV2, ProductV2, PricebookV2
from services.pricing.repositories.database_ops import store_outbox_event
from services.pricing.utils.metrics import saga_total, saga_duration
from services.pricing.utils.pricing_logger import logger
from services.pricing.utils.rabbitmq import publish_to_rabbitmq
from services.pricing.utils.user_auth import check_permission


class PriceCalculationSaga:
    """Saga for price calculation with compensation"""

    def __init__(self, db):
        self.db = db
        self.calculation = None
        self.eid = None

    async def exec(self, calculation_id: str, tenant_id: str, req: Dict, uctx: Dict):
        """Execute price calculation saga"""
        start = time.time()
        try:
            # Check permissions
            if not check_permission("pricing.calculate", uctx):
                raise ValueError("Insufficient permissions")

            # Get product and pricebook
            product = self.db.query(ProductV2).filter(ProductV2.product_id == req['product_id']).first()
            if not product:
                raise ValueError("Product not found")

            pricebook = self.db.query(PricebookV2).filter(PricebookV2.pricebook_id == req['pricebook_id']).first()
            if not pricebook:
                raise ValueError("Pricebook not found")

            # Calculate price using pricing rules
            base_price = product.base_price_minor
            final_price = base_price  # Simplified calculation

            # Create price calculation record
            self.calculation = CalculatedPriceV2(
                price_id=calculation_id,
                tenant_id=tenant_id,
                product_id=req['product_id'],
                pricebook_id=req['pricebook_id'],
                base_price_minor=base_price,
                calculated_price_minor=final_price,
                quantity=req['quantity'],
                calculated_at=datetime.now(timezone.utc)
            )
            self.db.add(self.calculation)
            self.db.commit()
            self.db.refresh(self.calculation)

            # Create outbox event
            self.eid = store_outbox_event(self.db, "PRICE_CALCULATED", tenant_id, calculation_id, {
                "calculation_id": calculation_id,
                "product_id": req['product_id'],
                "final_price_minor": final_price
            })

            # Publish event
            publish_to_rabbitmq("PRICE_CALCULATED", {
                "calculation_id": calculation_id,
                "product_id": req['product_id'],
                "final_price_minor": final_price
            }, tenant_id)

            saga_total.labels(type="price_calculation", status="ok").inc()
            saga_duration.labels(type="price_calculation").observe(time.time() - start)
            return {"calculation_id": calculation_id, "final_price_minor": final_price}

        except Exception as e:
            await self.comp()
            saga_total.labels(type="price_calculation", status="fail").inc()
            raise

    async def comp(self):
        """Compensation logic"""
        try:
            if self.eid:
                self.db.execute(text("DELETE FROM outbox_events WHERE event_id = :id"), {"id": self.eid})
                self.db.commit()
            if self.calculation:
                self.db.delete(self.calculation)
                self.db.commit()
        except Exception as e:
            logger.error(f"Price calculation compensation failed: {e}")
            self.db.rollback()