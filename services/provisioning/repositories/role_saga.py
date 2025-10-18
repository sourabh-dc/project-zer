import time
from sqlalchemy import text
from prometheus_client import Counter, Histogram

from .db_handler import audit
from ..utils.provisioning_logger import logger
from ..models import RoleV2
from outbox_repository import store_outbox
from ..tasks.celery_tasks import publish_outbox_events


req_total = Counter('prov_requests_total', 'Requests', ['op', 'status'])
req_duration = Histogram('prov_duration_seconds', 'Duration', ['op'])
saga_total = Counter('prov_saga_total', 'Sagas', ['type', 'status'])
saga_duration = Histogram('prov_saga_duration_seconds', 'Saga duration', ['type'])


class RoleSaga:
    def __init__(self, db):
        self.db = db
        self.r = None
        self.eid = None

    async def exec(self, rid, req, uctx):
        start = time.time()
        try:
            if self.db.query(RoleV2).filter(RoleV2.code == req.code).first():
                raise ValueError("Code exists")
            self.r = RoleV2(role_id=rid, code=req.code, name=req.name, description=req.description)
            self.db.add(self.r)
            self.db.commit()
            self.db.refresh(self.r)
            self.eid = store_outbox(self.db, "ROLE_CREATED", uctx["tenant_id"], str(rid),
                                    {"role_id": str(rid), "code": req.code})
            publish_outbox_events.delay()
            audit(self.db, uctx["tenant_id"], uctx["user_id"], "CREATE", "role", str(rid), {"code": req.code})
            saga_total.labels(type="role", status="ok").inc()
            saga_duration.labels(type="role").observe(time.time() - start)
            return {"role_id": str(rid), "code": req.code, "created": True}
        except Exception as e:
            await self.comp()
            saga_total.labels(type="role", status="fail").inc()
            raise

    async def comp(self):
        try:
            if self.eid:
                self.db.execute(text("DELETE FROM outbox_events WHERE event_id = :id"), {"id": self.eid})
                self.db.commit()
            if self.r:
                self.db.delete(self.r)
                self.db.commit()
        except Exception as e:
            logger.error(f"Compensation failed: {e}")
            self.db.rollback()