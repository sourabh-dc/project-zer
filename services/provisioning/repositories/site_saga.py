import time
from sqlalchemy import text

from .db_handler import audit
from ..services.subscription_service import get_limits
from ..utils.provisioning_logger import logger
from ..models import TenantV2, SiteV2
from .outbox_repository import store_outbox
from services.provisioning.services.celery_tasks import publish_outbox_events
from ..utils.metrics import saga_total, saga_duration

class SiteSaga:
    def __init__(self, db):
        self.db = db
        self.s = None
        self.eid = None

    async def exec(self, sid, tid, req, uctx):
        start = time.time()
        try:
            t = self.db.query(TenantV2).filter(TenantV2.tenant_id == tid).first()
            if not t:
                raise ValueError("Tenant not found")
            lims = await get_limits(str(tid))
            cnt = self.db.query(SiteV2).filter(SiteV2.tenant_id == tid).count()
            if cnt >= lims.get("max_sites", 10):
                raise ValueError("Limit reached")
            self.s = SiteV2(
                site_id=sid,
                tenant_id=tid,
                name=req.name,
                site_type=req.site_type,
                geo=req.geo,
                device_metadata=req.device_metadata  # Phase 2: Site Registry
            )
            self.db.add(self.s)
            self.db.commit()
            self.db.refresh(self.s)
            self.eid = store_outbox(self.db, "SITE_CREATED", str(tid), str(sid), {
                "site_id": str(sid),
                "name": req.name,
                "device_metadata": req.device_metadata  # Include in event for CV Gateway
            })
            publish_outbox_events.delay()
            audit(self.db, str(tid), uctx["user_id"], "CREATE", "site", str(sid), {"name": req.name})
            saga_total.labels(type="site", status="ok").inc()
            saga_duration.labels(type="site").observe(time.time() - start)
            return {"site_id": str(sid), "name": req.name, "created": True}
        except Exception as e:
            await self.comp()
            saga_total.labels(type="site", status="fail").inc()
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

    async def getall(self):
        try:
            sites = self.db.query(SiteV2).all()
            return [{"site_id": str(s.site_id), "tenant_id": str(s.tenant_id), "name": s.name} for s in sites]
        except Exception as e:
            logger.error(f"Get all sites failed: {e}")
            raise