import time
import uuid
from sqlalchemy import text
from prometheus_client import Counter, Histogram

from .db_handler import audit
from ..utils.provisioning_logger import logger
from ..models import VendorV2, TenantV2
from ..services.subscription_service import get_limits
from outbox_repository import store_outbox
from ..tasks.celery_tasks import publish_outbox_events


req_total = Counter('prov_requests_total', 'Requests', ['op', 'status'])
req_duration = Histogram('prov_duration_seconds', 'Duration', ['op'])
saga_total = Counter('prov_saga_total', 'Sagas', ['type', 'status'])
saga_duration = Histogram('prov_saga_duration_seconds', 'Saga duration', ['type'])

class VendorSaga:
    def __init__(self, db):
        self.db = db
        self.v = None
        self.eid = None

    async def exec(self, vid, req, uctx):
        start = time.time()
        try:
            tid = uuid.UUID(req.tenant_id)
            t = self.db.query(TenantV2).filter(TenantV2.tenant_id == tid).first()
            if not t:
                raise ValueError("Tenant not found")
            lims = await get_limits(str(tid))
            cnt = self.db.query(VendorV2).filter(VendorV2.tenant_id == tid).count()
            if cnt >= lims.get("max_vendors", 20):
                raise ValueError("Limit reached")
            self.v = VendorV2(
                vendor_id=vid,
                tenant_id=tid,
                name=req.name,
                contact_email=req.contact_email,
                description=req.description,
                status="active"
            )
            self.db.add(self.v)
            self.db.commit()
            self.db.refresh(self.v)
            self.eid = store_outbox(self.db, "VENDOR_CREATED", str(tid), str(vid),
                                    {"vendor_id": str(vid), "name": req.name})
            publish_outbox_events.delay()
            audit(self.db, str(tid), uctx["user_id"], "CREATE", "vendor", str(vid), {"name": req.name})
            saga_total.labels(type="vendor", status="ok").inc()
            saga_duration.labels(type="vendor").observe(time.time() - start)
            return {"vendor_id": str(vid), "name": req.name, "created": True}
        except Exception as e:
            await self.comp()
            saga_total.labels(type="vendor", status="fail").inc()
            raise

    async def comp(self):
        try:
            if self.eid:
                self.db.execute(text("DELETE FROM outbox_events WHERE event_id = :id"), {"id": self.eid})
                self.db.commit()
            if self.v:
                self.db.delete(self.v)
                self.db.commit()
        except Exception as e:
            logger.error(f"Compensation failed: {e}")
            self.db.rollback()