import time
import uuid
from sqlalchemy import text
from prometheus_client import Counter, Histogram

from .db_handler import audit
from ..utils.provisioning_logger import logger
from ..models import TenantV2, CostCentre
from outbox_repository import store_outbox
from ..tasks.celery_tasks import publish_outbox_events

req_total = Counter('prov_requests_total', 'Requests', ['op', 'status'])
req_duration = Histogram('prov_duration_seconds', 'Duration', ['op'])
saga_total = Counter('prov_saga_total', 'Sagas', ['type', 'status'])
saga_duration = Histogram('prov_saga_duration_seconds', 'Saga duration', ['type'])


class CostCentreSaga:
    def __init__(self, db):
        self.db = db
        self.cc = None
        self.eid = None

    async def exec(self, req, uctx):
        start = time.time()
        try:
            tid = req.tenant_id
            t = self.db.query(TenantV2).filter(TenantV2.tenant_id == uuid.UUID(tid)).first()
            if not t:
                raise ValueError("Tenant not found")
            self.cc = CostCentre(
                cost_centre_id=f"cc_{uuid.uuid4().hex[:12]}",
                tenant_id=tid,
                name=req.name,
                budget_minor=req.budget_minor,
                spent_minor=0,
                currency_code="GBP",
                status="active"
            )
            self.db.add(self.cc)
            self.db.commit()
            self.db.refresh(self.cc)
            self.eid = store_outbox(self.db, "COST_CENTRE_CREATED", tid, self.cc.cost_centre_id, {
                "cost_centre_id": self.cc.cost_centre_id,
                "name": req.name
            })
            publish_outbox_events.delay()
            audit(self.db, tid, uctx["user_id"], "CREATE", "cost_centre", self.cc.cost_centre_id, {"name": req.name})
            saga_total.labels(type="cost_centre", status="ok").inc()
            saga_duration.labels(type="cost_centre").observe(time.time() - start)
            return {"cost_centre_id": self.cc.cost_centre_id, "name": req.name, "budget_minor": req.budget_minor,
                    "created": True}
        except Exception as e:
            await self.comp()
            saga_total.labels(type="cost_centre", status="fail").inc()
            raise

    async def comp(self):
        try:
            if self.eid:
                self.db.execute(text("DELETE FROM outbox_events WHERE event_id = :id"), {"id": self.eid})
                self.db.commit()
            if self.cc:
                self.db.delete(self.cc)
                self.db.commit()
        except Exception as e:
            logger.error(f"Compensation failed: {e}")
            self.db.rollback()