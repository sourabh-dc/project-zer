import time

from sqlalchemy import text

from services.catalog.models import CategoryV2
from services.catalog.repositories.outbox_repository import store_outbox_event
from ..utils.metrics import saga_total, saga_duration
from ..utils.cataog_logger import logger
from ..utils.rabbitmq import publish_to_rabbitmq
from ..utils.user_auth import check_permission


class CategorySaga:
    """Saga for category creation with compensation"""

    def __init__(self, db):
        self.db = db
        self.category = None
        self.eid = None

    async def exec(self, category_id, tenant_id, req, uctx):
        """Execute category creation saga"""
        start = time.time()
        try:
            # Check permissions
            if not check_permission(uctx, "catalog.create"):
                raise ValueError("Insufficient permissions")

            # Check if category name already exists
            existing = self.db.query(CategoryV2).filter(
                CategoryV2.tenant_id == tenant_id,
                CategoryV2.name == req.name
            ).first()
            if existing:
                raise ValueError("Category name already exists")

            # Create category
            self.category = CategoryV2(
                category_id=category_id,
                tenant_id=tenant_id,
                name=req.name,
                description=req.description,
                is_active=True
            )
            self.db.add(self.category)
            self.db.commit()
            self.db.refresh(self.category)

            # Create outbox event
            self.eid = store_outbox_event(self.db, "CATEGORY_CREATED", str(tenant_id), str(category_id), {
                "category_id": str(category_id),
                "name": req.name
            })

            # Publish event
            publish_to_rabbitmq("CATEGORY_CREATED", {
                "category_id": str(category_id),
                "name": req.name
            }, str(tenant_id))

            saga_total.labels(type="category", status="ok").inc()
            saga_duration.labels(type="category").observe(time.time() - start)
            return {"category_id": str(category_id), "name": req.name, "created": True}

        except Exception as e:
            await self.comp()
            saga_total.labels(type="category", status="fail").inc()
            raise

    async def comp(self):
        """Compensation logic"""
        try:
            if self.eid:
                self.db.execute(text("DELETE FROM outbox_events WHERE event_id = :id"), {"id": self.eid})
                self.db.commit()
            if self.category:
                self.db.delete(self.category)
                self.db.commit()
        except Exception as e:
            logger.error(f"Category compensation failed: {e}")
            self.db.rollback()