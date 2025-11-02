from sqlalchemy import update, select
import uuid
from datetime import datetime
from typing import Dict, Any, List
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from services.events.models import  EventNew
from ..core.celery_config import celery_app
from ..schemas import EventRetryRequest
from ..utils.events_logger import logger


class EventRetrySaga:
    """Saga for retrying failed events"""

    def __init__(self, db: AsyncSession, user_context: Dict[str, Any]):
        self.db = db
        self.user_context = user_context

    async def execute(self, payload: EventRetryRequest) -> Dict[str, Any]:
        """Execute event retry saga"""
        try:
            # Get pending events
            events = await self._get_pending_events(payload)

            retried_count = 0
            for event in events:
                try:
                    # Retry publishing
                    await self._retry_event(event)
                    retried_count += 1

                except Exception as e:
                    logger.error(f"Failed to retry event {event.id}: {str(e)}")
                    await self._mark_failed(event.id, str(e))

            return {
                "ok": True,
                "retried_count": retried_count,
                "total_events": len(events)
            }

        except Exception as e:
            logger.error(f"Event retry saga failed: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    async def _get_pending_events(self, payload: EventRetryRequest) -> List[EventNew]:
        """Get pending events to retry"""
        query = select(EventNew).where(
            EventNew.tenant_id == uuid.UUID(payload.tenant_id),
            EventNew.status == "pending",
            EventNew.retry_count < EventNew.max_retries
        )

        if payload.event_types:
            query = query.where(EventNew.event_type.in_(payload.event_types))

        query = query.order_by(EventNew.created_at.asc()).limit(payload.max_events)

        result = await self.db.execute(query)
        return result.scalars().all()

    async def _retry_event(self, event: EventNew):
        """Retry publishing a single event"""
        # Update retry count
        event.retry_count += 1
        event.updated_at = datetime.utcnow()

        # Try to publish again
        if celery_app:
            celery_app.send_task('events_service.publish_to_rabbitmq',
                                 args=[event.event_type, event.event_data, str(event.tenant_id)])
        else:
            logger.info(f"Retrying event {event.event_type}")

        # Mark as published if successful
        event.status = "published"
        event.published_at = datetime.utcnow()

        await self.db.commit()

    async def _mark_failed(self, event_id: uuid.UUID, error: str):
        """Mark event as failed"""
        query = update(EventNew).where(
            EventNew.id == event_id
        ).values(
            status="failed",
            updated_at=datetime.utcnow()
        )
        await self.db.execute(query)
        await self.db.commit()