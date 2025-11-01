from typing import Any, Dict
from sqlalchemy.orm.session import Session
from datetime import datetime, timezone, timedelta
import json
from fastapi import HTTPException
from sqlalchemy import text

from ..schemas import ReplayRequest
from ..utils.notifications_logger import logger
from services.notifications.utils.metrics import saga_duration


class ReplaySaga:
    """Saga for replaying failed notifications"""

    def __init__(self, db: Session):
        self.db = db

    async def execute(self, request: ReplayRequest, user_context: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the replay saga"""
        start_time = datetime.now()

        try:
            # Step 1: Get delivery record
            delivery = await self._get_delivery_record(request.delivery_id)

            # Step 2: Validate replay eligibility
            await self._validate_replay_eligibility(delivery, request.force)

            # Step 3: Reset delivery status
            await self._reset_delivery_status(delivery["id"])

            # Step 4: Schedule retry
            await self._schedule_retry(delivery["id"])

            # Step 5: Audit replay
            await self._audit_replay(delivery["id"], user_context)

            duration = (datetime.now() - start_time).total_seconds()
            saga_duration.labels(saga_type="replay_notification", status="success").observe(duration)

            return {"delivery_id": request.delivery_id, "status": "replayed",
                    "next_attempt_at": delivery["next_attempt_at"]}

        except Exception as e:
            duration = (datetime.now() - start_time).total_seconds()
            saga_duration.labels(saga_type="replay_notification", status="failed").observe(duration)

            logger.error("Replay saga failed", delivery_id=request.delivery_id, error=str(e))
            raise HTTPException(status_code=500, detail=f"Replay failed: {str(e)}")

    async def _get_delivery_record(self, delivery_id: str) -> Dict[str, Any]:
        """Get delivery record"""
        result = self.db.execute(text("""
                                      SELECT id,
                                             tenant_id,
                                             user_id,
                                             channel,
                                             provider,
                                             status,
                                             payload,
                                             retry_count,
                                             max_retries,
                                             next_attempt_at
                                      FROM notification_deliveries_new
                                      WHERE id = :id
                                      """), {"id": delivery_id}).first()

        if not result:
            raise HTTPException(status_code=404, detail="Delivery not found")

        return dict(result._mapping)

    async def _validate_replay_eligibility(self, delivery: Dict[str, Any], force: bool):
        """Validate if delivery can be replayed"""
        if delivery["status"] == "sent" and not force:
            raise HTTPException(status_code=400, detail="Delivery already sent")

        if delivery["retry_count"] >= delivery["max_retries"] and not force:
            raise HTTPException(status_code=400, detail="Max retries reached")

    async def _reset_delivery_status(self, delivery_id: str):
        """Reset delivery status to queued"""
        self.db.execute(text("""
                             UPDATE notification_deliveries_new
                             SET status     = 'queued',
                                 error      = NULL,
                                 updated_at = NOW()
                             WHERE id = :id
                             """), {"id": delivery_id})
        self.db.commit()

    async def _schedule_retry(self, delivery_id: str):
        """Schedule retry attempt"""
        next_attempt = datetime.now(timezone.utc) + timedelta(minutes=5)
        self.db.execute(text("""
                             UPDATE notification_deliveries_new
                             SET next_attempt_at = :next_attempt_at,
                                 retry_count     = retry_count + 1,
                                 updated_at      = NOW()
                             WHERE id = :id
                             """), {"id": delivery_id, "next_attempt_at": next_attempt})
        self.db.commit()

    async def _audit_replay(self, delivery_id: str, user_context: Dict[str, Any]):
        """Audit replay action"""
        self.db.execute(text("""
                             INSERT INTO audit_logs (tenant_id, user_id, action, resource_type, resource_id, details,
                                                     created_at)
                             VALUES (:tenant_id, :user_id, 'REPLAY_NOTIFICATION', 'notification_delivery', :resource_id,
                                     :details, NOW())
                             """), {
                            "tenant_id": user_context.get("tenant_id"),
                            "user_id": user_context.get("user_id"),
                            "resource_id": delivery_id,
                            "details": json.dumps({"action": "replay"})
                        })
        self.db.commit()