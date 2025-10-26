import time
from typing import Dict

from sqlalchemy import text

from services.pricing.models import PricebookV2, PriceRuleV2
from services.pricing.repositories.database_ops import store_outbox_event
from services.pricing.utils.metrics import saga_total, saga_duration
from services.pricing.utils.pricing_logger import logger
from services.pricing.utils.rabbitmq import publish_to_rabbitmq
from services.pricing.utils.user_auth import check_permission


class PriceRuleSaga:
    """Saga for price rule creation with compensation"""

    def __init__(self, db):
        self.db = db
        self.rule = None
        self.eid = None

    async def exec(self, rule_id: str, pricebook_id: str, req: Dict, uctx: Dict):
        """Execute price rule creation saga"""
        start = time.time()
        try:
            # Validate pricebook exists and belongs to tenant
            pricebook = self.db.query(PricebookV2).filter(PricebookV2.pricebook_id == pricebook_id).first()
            if not pricebook:
                raise ValueError("Pricebook not found")

            # Check permissions
            if not check_permission("pricing.create", uctx):
                raise ValueError("Insufficient permissions")

            # Create price rule
            self.rule = PriceRuleV2(
                rule_id=rule_id,
                pricebook_id=pricebook_id,
                rule_type=req['rule_type'],
                rule_value=req['rule_value']
            )
            self.db.add(self.rule)
            self.db.commit()
            self.db.refresh(self.rule)

            # Create outbox event
            self.eid = store_outbox_event(self.db, "PRICE_RULE_CREATED", str(pricebook.tenant_id), rule_id, {
                "rule_id": rule_id,
                "pricebook_id": pricebook_id,
                "rule_type": req['rule_type']
            })

            # Publish event
            publish_to_rabbitmq("PRICE_RULE_CREATED", {
                "rule_id": rule_id,
                "pricebook_id": pricebook_id,
                "rule_type": req['rule_type']
            }, str(pricebook.tenant_id))

            saga_total.labels(type="price_rule", status="ok").inc()
            saga_duration.labels(type="price_rule").observe(time.time() - start)
            return {"rule_id": rule_id, "created": True}

        except Exception as e:
            await self.comp()
            saga_total.labels(type="price_rule", status="fail").inc()
            raise

    async def comp(self):
        """Compensation logic"""
        try:
            if self.eid:
                self.db.execute(text("DELETE FROM outbox_events WHERE event_id = :id"), {"id": self.eid})
                self.db.commit()
            if self.rule:
                self.db.delete(self.rule)
                self.db.commit()
        except Exception as e:
            logger.error(f"Price rule compensation failed: {e}")
            self.db.rollback()