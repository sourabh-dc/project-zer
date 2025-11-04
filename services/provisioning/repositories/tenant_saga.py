import time
import uuid
from http.client import HTTPException
from sqlalchemy import text

from ..utils.provisioning_logger import logger
from ..models import TenantV2
from .outbox_repository import store_outbox
from services.provisioning.services.celery_tasks import publish_outbox_events
from ..utils.metrics import saga_total, saga_duration



class TenantSaga:
    def __init__(self, db):
        self.db = db
        self.t = None
        self.eid = None

    async def exec(self, req):
        start = time.time()
        sid = f"saga_t_{uuid.uuid4().hex[:8]}"
        try:
            if self.db.query(TenantV2).filter(TenantV2.name == req.name).first():
                raise ValueError("Name exists")
            self.t = TenantV2(tenant_id=uuid.uuid4(), name=req.name, type=req.tenant_type, active=True)
            self.db.add(self.t)
            self.db.commit()
            self.db.refresh(self.t)
            self.eid = store_outbox(self.db, "TENANT_CREATED", str(self.t.tenant_id), str(self.t.tenant_id),
                                    {"tenant_id": str(self.t.tenant_id), "name": self.t.name})
            publish_outbox_events.delay()
            saga_total.labels(type="tenant", status="ok").inc()
            saga_duration.labels(type="tenant").observe(time.time() - start)
            return {"tenant_id": str(self.t.tenant_id), "name": self.t.name, "status": "created", "saga_id": sid}
        except Exception as e:
            await self.comp()
            saga_total.labels(type="tenant", status="fail").inc()
            raise

    async def comp(self):
        try:
            if self.eid:
                self.db.execute(text("DELETE FROM outbox_events WHERE event_id = :id"), {"id": self.eid})
                self.db.commit()
            if self.t:
                self.db.delete(self.t)
                self.db.commit()
        except Exception as e:
            logger.error(f"Compensation failed: {e}")
            self.db.rollback()

    async def getall(self):
        try:
            tenants = self.db.query(TenantV2).filter(TenantV2.active == True).all()
            return [{"tenant_id": str(t.tenant_id), "name": t.name, "type": t.type} for t in tenants]
        except Exception as e:
            logger.error(f"Get all tenants failed: {e}")
            raise HTTPException