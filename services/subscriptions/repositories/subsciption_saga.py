import time
from datetime import datetime, timedelta
from typing import Dict, Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from services.subscriptions.models import TenantSubscription
from services.subscriptions.schemas import TenantSubscriptionPayload
from services.subscriptions.utils.metrics import saga_total, saga_duration
from .database_ops import store_outbox_event, audit_log
from ..utils.subsciptions_logger import logger
from ..services.celery_tasks import publish_outbox_events


# Saga for Subscription Creation
class SubscriptionSaga:
    def __init__(self, db: Session):
        self.db = db
        self.subscription = None
        self.outbox_id = None

    async def execute(self, tenant_id: str, payload: TenantSubscriptionPayload, user_context: Dict[str, Any]) -> Dict:
        start_time = time.time()
        try:
            # Step 1: Validate
            if self.db.query(TenantSubscription).filter(TenantSubscription.tenant_id == tenant_id).first():
                raise ValueError("Subscription exists")

            # Step 2: Create subscription
            self.subscription = TenantSubscription(
                tenant_id=tenant_id,
                plan_code=payload.plan_code,
                payment_method=payload.payment_method,
                status="active",
                external_id=payload.external_id or f"sub_{tenant_id}_{int(time.time())}",
                current_period_start=payload.current_period_start or datetime.now(),
                current_period_end=payload.current_period_end or (datetime.now() + timedelta(days=365)),
                trial_end=payload.trial_end
            )
            self.db.add(self.subscription)
            self.db.commit()
            self.db.refresh(self.subscription)

            # Step 3: Store outbox event
            self.outbox_id = store_outbox_event(self.db, "PLAN_CREATED", tenant_id, str(self.subscription.id), {
                "tenant_id": tenant_id,
                "plan_code": payload.plan_code,
                "subscription_id": str(self.subscription.id)
            })

            # Step 4: Publish event
            publish_outbox_events.delay()

            # Audit log
            audit_log(self.db, tenant_id, user_context.get("user_id"), "CREATE", "subscription",
                      str(self.subscription.id), payload.dict())

            saga_total.labels(type="subscription", status="success").inc()
            saga_duration.labels(type="subscription").observe(time.time() - start_time)

            return {"subscription_id": str(self.subscription.id), "plan_code": payload.plan_code, "created": True}

        except Exception as e:
            await self.compensate()
            saga_total.labels(type="subscription", status="failed").inc()
            raise

    async def compensate(self):
        try:
            if self.outbox_id:
                self.db.execute(text("DELETE FROM outbox_events WHERE id = :id"), {"id": self.outbox_id})
                self.db.commit()

            if self.subscription:
                self.db.delete(self.subscription)
                self.db.commit()
        except Exception as e:
            logger.error(f"Compensation failed: {e}")
            self.db.rollback()