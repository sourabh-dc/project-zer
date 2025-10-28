import time
from sqlalchemy import text

from services.usage.models import UsageEvent
from services.usage.repositories.database_ops import store_outbox_event, audit_log
from services.usage.utils.user_auth import check_permission
from ..utils.usage_logger import logger
from ..utils.rabbitmq import publish_to_rabbitmq
from ..utils.metrics import saga_total, saga_duration

class UsageRecordSaga:
    """Saga for usage event recording with compensation"""

    def __init__(self, db):
        self.db = db
        self.event = None
        self.eid = None

    async def exec(self, event_id, tenant_id, req, uctx):
        """Execute usage recording saga"""
        start = time.time()
        try:
            # Check permissions
            if not check_permission(uctx, "usage.create"):
                raise ValueError("Insufficient permissions")

            # Create usage event
            self.event = UsageEvent(
                event_id=event_id,
                tenant_id=tenant_id,
                user_id=uctx.get("user_id"),
                meter_code=req.meter_code,
                quantity=req.quantity,
                metadata_json=req.metadata
            )
            self.db.add(self.event)
            self.db.commit()
            self.db.refresh(self.event)

            # Create outbox event
            self.eid = store_outbox_event(self.db, "USAGE_RECORDED", tenant_id, event_id, {
                "event_id": event_id,
                "meter_code": req.meter_code,
                "quantity": req.quantity
            })

            # Publish event
            publish_to_rabbitmq("USAGE_RECORDED", {
                "event_id": event_id,
                "meter_code": req.meter_code,
                "quantity": req.quantity
            }, tenant_id)

            # Audit log
            audit_log(self.db, tenant_id, uctx.get("user_id"), "CREATE", "usage_event", event_id, {
                "meter_code": req.meter_code,
                "quantity": req.quantity
            })

            saga_total.labels(type="usage", status="ok").inc()
            saga_duration.labels(type="usage").observe(time.time() - start)
            return {"event_id": event_id, "recorded": True}

        except Exception as e:
            await self.comp()
            saga_total.labels(type="usage", status="fail").inc()
            raise

    async def comp(self):
        """Compensation logic"""
        try:
            if self.eid:
                self.db.execute(text("DELETE FROM outbox_events WHERE event_id = :id"), {"id": self.eid})
                self.db.commit()
            if self.event:
                self.db.delete(self.event)
                self.db.commit()
        except Exception as e:
            logger.error(f"Usage compensation failed: {e}")
            self.db.rollback()