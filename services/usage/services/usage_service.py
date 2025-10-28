import uuid
from typing import Dict

from fastapi import HTTPException
from sqlalchemy.orm import Session

from services.usage.repositories.database_ops import insert_usage, get_usage_events
from services.usage.schemas import UsageEventRequest
from services.usage.utils.usage_logger import logger
from services.usage.utils.user_auth import check_permission


async def record_usage(request: UsageEventRequest, db: Session):
    """Record a usage event"""
    try:
        event_id = f"usage_{uuid.uuid4().hex[:12]}"
        insert_usage(db, request, event_id)
        logger.info(f"Usage recorded: {event_id}")

        return {
            "event_id": event_id,
            "tenant_id": request.tenant_id,
            "meter_code": request.meter_code,
            "quantity": request.quantity,
            "recorded": True
        }

    except Exception as e:
        logger.error(f"Usage recording failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def fetch_usage_events(tenant_id: str, limit: int, uctx: Dict, db: Session):
    """Get usage events for a tenant"""
    try:
        if not check_permission(uctx, "usage.view"):
            raise HTTPException(status_code=403, detail="Insufficient permissions")

        events = get_usage_events(db, tenant_id, limit)

        return [{
            "event_id": e.event_id,
            "meter_code": e.meter_code,
            "quantity": e.quantity,
            "recorded_at": e.recorded_at.isoformat()
        } for e in events]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))