import time
import uuid
from datetime import datetime
from sqlalchemy import text

from .db_handler import audit
from ..services.subscription_service import get_limits
from ..utils.provisioning_logger import logger
from ..models import UserV2, TenantV2
from .outbox_repository import store_outbox
from ..tasks.celery_tasks import publish_outbox_events
from ..utils.user_auth import gen_api_key
from ..utils.metrics import saga_total, saga_duration


class UserSaga:
    def __init__(self, db):
        self.db = db
        self.u = None
        self.eid = None

    async def exec(self, uid, req, uctx):
        start = time.time()
        try:
            tid = uuid.UUID(req.tenant_id)
            t = self.db.query(TenantV2).filter(TenantV2.tenant_id == tid).first()
            if not t:
                raise ValueError("Tenant not found")
            lims = await get_limits(str(tid))
            cnt = self.db.query(UserV2).filter(UserV2.tenant_id == tid).count()
            if cnt >= lims.get("max_users", 100):
                raise ValueError("Limit reached")
            if self.db.query(UserV2).filter(UserV2.email == req.email).first():
                raise ValueError("Email exists")
            self.u = UserV2(
                user_id=uid,
                tenant_id=tid,
                email=req.email,
                display_name=req.display_name,
                active=True,
                api_key=gen_api_key() if req.generate_api_key else None,
                api_key_created_at=datetime.now() if req.generate_api_key else None,
                permissions=req.permissions or []
            )
            self.db.add(self.u)
            self.db.commit()
            self.db.refresh(self.u)
            self.eid = store_outbox(self.db, "USER_CREATED", str(tid), str(uid),
                                    {"user_id": str(uid), "email": req.email})
            publish_outbox_events.delay()
            audit(self.db, str(tid), uctx["user_id"], "CREATE", "user", str(uid), {"email": req.email})
            saga_total.labels(type="user", status="ok").inc()
            saga_duration.labels(type="user").observe(time.time() - start)
            return {"user_id": str(uid), "email": self.u.email, "api_key": self.u.api_key, "created": True}
        except Exception as e:
            await self.comp()
            saga_total.labels(type="user", status="fail").inc()
            raise

    async def comp(self):
        try:
            if self.eid:
                self.db.execute(text("DELETE FROM outbox_events WHERE event_id = :id"), {"id": self.eid})
                self.db.commit()
            if self.u:
                self.db.delete(self.u)
                self.db.commit()
        except Exception as e:
            logger.error(f"Compensation failed: {e}")
            self.db.rollback()

    async def getall(self):
        try:
            us = self.db.query(UserV2).filter(UserV2.active == True).all()
            return [{"user_id": str(u.user_id), "tenant_id": str(u.tenant_id), "email": u.email} for u in us]
        except Exception as e:
            raise