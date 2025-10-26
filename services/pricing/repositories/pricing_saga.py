import time

from sqlalchemy import text

from services.pricing.models import PricebookV2
from services.pricing.utils.metrics import saga_total, saga_duration
from ..utils.pricing_logger import logger


class PricebookSaga:
    """Saga for pricebook creation with compensation"""

    def __init__(self, db):
        self.db = db
        self.pricebook = None
        self.eid = None

    async def exec(self, pricebook_id, tenant_id, req, uctx):
        """Execute pricebook creation saga"""
        start = time.time()
        try:
            # Create pricebook
            self.pricebook = PricebookV2(
                pricebook_id=pricebook_id,
                tenant_id=tenant_id,
                name=req.name,
                description=req.description,
                currency=req.currency
            )
            self.db.add(self.pricebook)
            self.db.commit()
            self.db.refresh(self.pricebook)

            # Store outbox event (DISABLED - fix core functionality first)
            # self.eid = store_outbox(self.db, "PRICEBOOK_CREATED", str(tenant_id), str(pricebook_id), {
            #     "pricebook_id": str(pricebook_id),
            #     "name": req.name,
            #     "currency": req.currency
            # })

            # Publish event
            # publish_outbox_events.delay()

            # Audit log (DISABLED - fix core functionality first)
            # audit(self.db, str(tenant_id), uctx["user_id"], "CREATE", "pricebook", str(pricebook_id), {
            #     "name": req.name,
            #     "currency": req.currency
            # })

            saga_total.labels(type="pricebook", status="ok").inc()
            saga_duration.labels(type="pricebook").observe(time.time() - start)

            return {
                "pricebook_id": str(pricebook_id),
                "name": req.name,
                "currency": req.currency,
                "created": True
            }

        except Exception as e:
            await self.comp()
            saga_total.labels(type="pricebook", status="fail").inc()
            raise

    async def comp(self):
        """Compensation logic"""
        try:
            if self.eid:
                self.db.execute(text("DELETE FROM outbox_events WHERE event_id = :id"), {"id": self.eid})
                self.db.commit()

            if self.pricebook:
                self.db.delete(self.pricebook)
                self.db.commit()

        except Exception as e:
            logger.error("Compensation failed", error=str(e))
            self.db.rollback()