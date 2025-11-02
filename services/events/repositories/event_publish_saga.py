from sqlalchemy import update, select
import time
import uuid
from datetime import datetime
from typing import Dict, Any
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from services.events.models import EventMetric, AuditLog, EventNew, EventSubscription
from services.events.schemas import EventPublishRequest, EventPublishResponse
from ..core.celery_config import celery_app
from ..utils.events_logger import logger


class EventPublishSaga:
    """Saga for reliable event publishing with compensation"""

    def __init__(self, db: AsyncSession, user_context: Dict[str, Any]):
        self.db = db
        self.user_context = user_context
        self.steps = []

    async def execute(self, payload: EventPublishRequest) -> EventPublishResponse:
        """Execute event publishing saga"""
        start_time = time.time()
        event_id = str(uuid.uuid4())

        try:
            # Step 1: Validate event
            await self._validate_event(payload)

            # Step 2: Store event in database
            event = await self._store_event(payload, event_id)

            # Step 3: Publish to RabbitMQ
            await self._publish_to_bus(payload, str(event.id))

            # Step 4: Update status to published
            await self._mark_published(event.id)

            # Step 5: Record metrics
            await self._record_metrics(payload.event_type, "success", time.time() - start_time)

            # Step 6: Audit log
            await self._audit_log("EVENT_PUBLISHED", payload, event_id)

            return EventPublishResponse(
                event_id=event_id,
                status="published",
                message="Event published successfully"
            )

        except Exception as e:
            logger.error(f"Event publishing saga failed: {str(e)}")

            # Compensation: Mark as failed
            await self._compensate(event_id, str(e))

            # Record failure metrics
            await self._record_metrics(payload.event_type, "failed", time.time() - start_time)

            raise HTTPException(status_code=500, detail=f"Event publishing failed: {str(e)}")

    async def _validate_event(self, payload: EventPublishRequest):
        """Validate event payload"""
        if not payload.event_type:
            raise ValueError("Event type is required")

        if not payload.tenant_id:
            raise ValueError("Tenant ID is required")

    async def _store_event(self, payload: EventPublishRequest, event_id: str) -> EventNew:
        """Store event in database"""
        event = EventNew(
            id=uuid.UUID(event_id),
            tenant_id=uuid.UUID(payload.tenant_id),
            event_type=payload.event_type,
            event_data=payload.event_data,
            status="pending"
        )

        self.db.add(event)
        await self.db.commit()
        await self.db.refresh(event)

        return event

    async def _publish_to_bus(self, payload: EventPublishRequest, event_id: str):
        """Publish event to RabbitMQ with subscription-based routing"""
        try:
            # Get event subscriptions for this event type and tenant
            subscription_query = select(EventSubscription).where(
                EventSubscription.tenant_id == uuid.UUID(payload.tenant_id),
                EventSubscription.event_type == payload.event_type,
                EventSubscription.active == True
            )

            result = await self.db.execute(subscription_query)
            subscriptions = result.scalars().all()

            if celery_app:
                # Use Celery task with subscription info
                celery_app.send_task('events_service.publish_to_rabbitmq',
                                     args=[payload.event_type, payload.event_data, payload.tenant_id, event_id,
                                           [{"service_name": sub.service_name, "queue_name": sub.queue_name} for sub in
                                            subscriptions]])
            else:
                # Fallback: Direct HTTP call (simulate)
                logger.info(f"Publishing event {payload.event_type} to {len(subscriptions)} subscriptions")

        except Exception as e:
            logger.error(f"Failed to publish to bus: {str(e)}")
            raise

    async def _mark_published(self, event_id: uuid.UUID):
        """Mark event as published"""
        query = update(EventNew).where(
            EventNew.id == event_id
        ).values(
            status="published",
            published_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        await self.db.execute(query)
        await self.db.commit()

    async def _record_metrics(self, event_type: str, status: str, duration: float):
        """Record event metrics"""
        metric = EventMetric(
            tenant_id=uuid.UUID(self.user_context["tenant_id"]),
            event_type=event_type,
            metric_type="publish_duration",
            metric_value=duration,
            metric_metadata={"status": status}
        )

        self.db.add(metric)
        await self.db.commit()

    async def _audit_log(self, action: str, payload: EventPublishRequest, event_id: str):
        """Create audit log entry"""
        audit_log = AuditLog(
            tenant_id=uuid.UUID(payload.tenant_id),
            user_id=uuid.UUID(self.user_context.get("user_id", "00000000-0000-0000-0000-000000000000")),
            action=action,
            resource_type="event",
            resource_id=event_id,
            details={"event_type": payload.event_type}
        )

        self.db.add(audit_log)
        await self.db.commit()

    async def _compensate(self, event_id: str, error: str):
        """Compensation logic for failed event publishing"""
        try:
            query = update(EventNew).where(
                EventNew.id == uuid.UUID(event_id)
            ).values(
                status="failed",
                updated_at=datetime.utcnow()
            )
            await self.db.execute(query)
            await self.db.commit()

            logger.info(f"Compensated event {event_id}: {error}")

        except Exception as e:
            logger.error(f"Compensation failed for event {event_id}: {str(e)}")