import time
from sqlalchemy import text
from prometheus_client import Counter, Histogram

from .db_handler import audit
from ..services.subscription_service import get_limits
from ..utils.provisioning_logger import logger
from ..models import SiteV2, StoreV2
from outbox_repository import store_outbox
from ..tasks.celery_tasks import publish_outbox_events

req_total = Counter('prov_requests_total', 'Requests', ['op', 'status'])
req_duration = Histogram('prov_duration_seconds', 'Duration', ['op'])
saga_total = Counter('prov_saga_total', 'Sagas', ['type', 'status'])
saga_duration = Histogram('prov_saga_duration_seconds', 'Saga duration', ['type'])


class StoreSaga:
    def __init__(self, db):
        self.db = db
        self.s = None
        self.eid = None

    async def exec(self, stid, sid, req, uctx):
        start = time.time()
        try:
            site = self.db.query(SiteV2).filter(SiteV2.site_id == sid).first()
            if not site:
                raise ValueError("Site not found")
            lims = await get_limits(str(site.tenant_id))
            cnt = self.db.query(StoreV2).filter(StoreV2.site_id == sid).count()
            if cnt >= lims.get("max_stores", 50):
                raise ValueError("Limit reached")
            self.s = StoreV2(store_id=stid, site_id=sid, name=req.name, store_type=req.store_type, geo=req.geo)
            self.db.add(self.s)
            self.db.commit()
            self.db.refresh(self.s)
            self.eid = store_outbox(self.db, "STORE_CREATED", str(site.tenant_id), str(stid),
                                    {"store_id": str(stid), "name": req.name})
            publish_outbox_events.delay()
            audit(self.db, str(site.tenant_id), uctx["user_id"], "CREATE", "store", str(stid), {"name": req.name})
            saga_total.labels(type="store", status="ok").inc()
            saga_duration.labels(type="store").observe(time.time() - start)
            return {"store_id": str(stid), "name": req.name, "created": True}
        except Exception as e:
            await self.comp()
            saga_total.labels(type="store", status="fail").inc()
            raise

    async def comp(self):
        try:
            if self.eid:
                self.db.execute(text("DELETE FROM outbox_events WHERE event_id = :id"), {"id": self.eid})
                self.db.commit()
            if self.s:
                self.db.delete(self.s)
                self.db.commit()
        except Exception as e:
            logger.error(f"Compensation failed: {e}")
            self.db.rollback()