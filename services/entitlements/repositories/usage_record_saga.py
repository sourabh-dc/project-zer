# Saga for Usage Recording
from sqlalchemy.orm import Session
from typing import Dict, Any
import time
from datetime import datetime, timedelta
from sqlalchemy import text

from services.entitlements.utils.entitlements_logger import logger
from services.entitlements.utils.metrics import saga_total, saga_duration
from services.entitlements.utils.user_auth import check_permission
from services.entitlements.repositories.database_ops import store_outbox_event, audit_log
from services.entitlements.services.celery_task import publish_outbox_events
from services.entitlements.models import SubscriptionUsage
from services.entitlements.schemas import RecordUsageRequest


class UsageRecordSaga:
    def __init__(self, db: Session):
        self.db = db
        self.usage = None
        self.outbox_id = None

    async def execute(self, payload: RecordUsageRequest, user_context: Dict[str, Any]) -> Dict:
        start_time = time.time()
        try:
            # Step 1: Validate
            if not check_permission("entitlements.record_usage", user_context):
                raise ValueError("Insufficient permissions")
            if payload.count <= 0:
                raise ValueError("Count must be positive")

            # Step 2: Record usage
            now = datetime.now()
            month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            month_end = (month_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)

            self.usage = self.db.query(SubscriptionUsage).filter(
                SubscriptionUsage.tenant_id == payload.tenant_id,
                SubscriptionUsage.feature_code == payload.feature_code,
                SubscriptionUsage.usage_type == payload.usage_type,
                SubscriptionUsage.period_start >= month_start,
                SubscriptionUsage.period_start < month_end
            ).first()

            if self.usage:
                self.usage.usage_count += payload.count
                self.usage.updated_at = now
            else:
                self.usage = SubscriptionUsage(
                    tenant_id=payload.tenant_id,
                    feature_code=payload.feature_code,
                    usage_type=payload.usage_type,
                    usage_count=payload.count,
                    period_start=month_start,
                    period_end=month_end
                )
                self.db.add(self.usage)

            self.db.commit()
            self.db.refresh(self.usage)

            # Step 3: Store outbox event
            self.outbox_id = store_outbox_event(self.db, "USAGE_RECORDED", payload.tenant_id, payload.tenant_id, {
                "tenant_id": payload.tenant_id,
                "feature_code": payload.feature_code,
                "usage_type": payload.usage_type,
                "count": payload.count,
                "total": self.usage.usage_count
            })

            # Step 4: Publish event
            publish_outbox_events.delay()

            # Audit log
            audit_log(self.db, payload.tenant_id, user_context.get("user_id"), "RECORD_USAGE", "usage",
                      str(self.usage.id), payload.dict())

            saga_total.labels(type="usage_record", status="success").inc()
            saga_duration.labels(type="usage_record").observe(time.time() - start_time)

            return {"tenant_id": payload.tenant_id, "feature_code": payload.feature_code,
                    "usage_type": payload.usage_type, "count": payload.count, "total": self.usage.usage_count}

        except Exception as e:
            await self.compensate()
            saga_total.labels(type="usage_record", status="failed").inc()
            raise

    async def compensate(self):
        try:
            if self.outbox_id:
                self.db.execute(text("DELETE FROM outbox_events WHERE id = :id"), {"id": self.outbox_id})
                self.db.commit()

            if self.usage:
                self.db.delete(self.usage)
                self.db.commit()
        except Exception as e:
            logger.error(f"Compensation failed: {e}")
            self.db.rollback()