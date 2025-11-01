from typing import Any, Dict, Optional
from sqlalchemy.orm.session import Session
from datetime import datetime, timezone
import uuid
import json
from fastapi import HTTPException
from sqlalchemy import text

from services.notifications.schemas import SendNotificationRequest
from ..utils.notifications_logger import logger
from ..repositories.notification_provider import create_provider
from services.notifications.utils.metrics import saga_duration

class SendNotificationSaga:
    """Saga for reliable notification delivery"""

    def __init__(self, db: Session):
        self.db = db
        self.compensation_steps = []

    async def execute(self, request: SendNotificationRequest, user_context: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the notification send saga"""
        start_time = datetime.now()

        try:
            # Step 1: Validate request and get provider
            provider_config = await self._get_provider_config(request.tenant_id, request.provider, request.channel)
            self.compensation_steps.append(("validate_provider", None))

            # Step 2: Create delivery record
            delivery_id = await self._create_delivery_record(request, provider_config)
            self.compensation_steps.append(("create_delivery", delivery_id))

            # Step 3: Send notification
            result = await self._send_notification(request, provider_config)
            self.compensation_steps.append(("send_notification", delivery_id))

            # Step 4: Update delivery status
            await self._update_delivery_status(delivery_id, "sent", result)

            # Step 5: Publish event
            await self._publish_notification_sent_event(delivery_id, request, result)

            # Step 6: Audit log
            await self._audit_notification_send(delivery_id, request, user_context)

            duration = (datetime.now() - start_time).total_seconds()
            if saga_duration:
                saga_duration.labels(saga_type="send_notification", status="success").observe(duration)

            return {
                "delivery_id": str(delivery_id),
                "status": "sent",
                "provider": provider_config["name"],
                "result": result
            }

        except Exception as e:
            # Compensation logic
            await self._compensate()
            duration = (datetime.now() - start_time).total_seconds()
            if saga_duration:
                saga_duration.labels(saga_type="send_notification", status="failed").observe(duration)

            logger.error("Send notification saga failed", error=str(e), compensation_steps=self.compensation_steps)
            raise HTTPException(status_code=500, detail=f"Notification send failed: {str(e)}")

    async def _get_provider_config(self, tenant_id: str, provider: Optional[str], channel: str) -> Dict[str, Any]:
        """Get provider configuration from rails"""
        if not provider:
            # Auto-select provider based on channel
            if channel == "email":
                provider = "sendgrid"
            elif channel == "sms":
                provider = "twilio"
            else:
                provider = "internal"

        # Get provider config from zeroque_rails
        result = self.db.execute(text("""
                                      SELECT config
                                      FROM zeroque_rails
                                      WHERE tenant_id = :tenant_id
                                        AND type = 'notification'
                                        AND name = :name
                                        AND active = true
                                      """), {"tenant_id": tenant_id, "name": provider}).first()

        if not result:
            # Fallback to internal provider
            provider = "internal"
            result = self.db.execute(text("""
                                          SELECT config
                                          FROM zeroque_rails
                                          WHERE tenant_id = :tenant_id
                                            AND type = 'notification'
                                            AND name = 'internal'
                                            AND active = true
                                          """), {"tenant_id": tenant_id}).first()

            if not result:
                # Default internal config
                config = {"fallback": True}
            else:
                config = result[0]
        else:
            config = result[0]

        return {"name": provider, "config": config}

    async def _create_delivery_record(self, request: SendNotificationRequest,
                                      provider_config: Dict[str, Any]) -> uuid.UUID:
        """Create notification delivery record"""
        delivery_id = uuid.uuid4()

        payload = {
            "to": str(request.to),
            "subject": request.subject,
            "body": request.body,
            "data": request.data,
            "priority": request.priority
        }

        next_attempt_at = request.delay_until or datetime.now(timezone.utc)

        self.db.execute(text("""
                             INSERT INTO notification_deliveries_new (id, tenant_id, user_id, channel, provider, status,
                                                                      template_id,
                                                                      payload, next_attempt_at, retry_count,
                                                                      max_retries, created_at)
                             VALUES (:id, :tenant_id, :user_id, :channel, :provider, 'queued', :template_id,
                                     :payload, :next_attempt_at, 0, 3, NOW())
                             """), {
                            "id": delivery_id,
                            "tenant_id": request.tenant_id,
                            "user_id": request.user_id,
                            "channel": request.channel,
                            "provider": provider_config["name"],
                            "template_id": request.template_id,
                            "payload": json.dumps(payload),
                            "next_attempt_at": next_attempt_at
                        })

        self.db.commit()
        return delivery_id

    async def _send_notification(self, request: SendNotificationRequest, provider_config: Dict[str, Any]) -> Dict[
        str, Any]:
        """Send notification via provider"""
        provider = create_provider(provider_config["name"], provider_config["config"])

        if request.channel == "email":
            result = await provider.send_email(
                to=str(request.to),
                subject=request.subject or "Notification",
                body=request.body or ""
            )
        elif request.channel == "sms":
            result = await provider.send_sms(
                to=str(request.to),
                message=request.body or "Notification"
            )
        elif request.channel == "push":
            result = await provider.send_push(
                to=str(request.to),
                title=request.subject or "Notification",
                body=request.body or ""
            )
        else:
            raise ValueError(f"Unsupported channel: {request.channel}")

        return result

    async def _update_delivery_status(self, delivery_id: uuid.UUID, status: str, result: Dict[str, Any]):
        """Update delivery status"""
        self.db.execute(text("""
                             UPDATE notification_deliveries_new
                             SET status     = :status,
                                 updated_at = NOW()
                             WHERE id = :id
                             """), {"id": delivery_id, "status": status})
        self.db.commit()

    async def _publish_notification_sent_event(self, delivery_id: uuid.UUID, request: SendNotificationRequest,
                                               result: Dict[str, Any]):
        """Publish NOTIFICATION_SENT event"""
        event_data = {
            "delivery_id": str(delivery_id),
            "tenant_id": request.tenant_id,
            "user_id": request.user_id,
            "channel": request.channel,
            "to": str(request.to),
            "status": "sent",
            "result": result
        }

        # Store in outbox_events for reliable publishing
        self.db.execute(text("""
                             INSERT INTO outbox_events (tenant_id, event_type, event_data, status, created_at)
                             VALUES (:tenant_id, 'NOTIFICATION_SENT', :event_data, 'pending', NOW())
                             """), {
                            "tenant_id": request.tenant_id,
                            "event_data": json.dumps(event_data)
                        })
        self.db.commit()

    async def _audit_notification_send(self, delivery_id: uuid.UUID, request: SendNotificationRequest,
                                       user_context: Dict[str, Any]):
        """Audit notification send"""
        self.db.execute(text("""
                             INSERT INTO audit_logs (tenant_id, user_id, action, resource_type, resource_id, details,
                                                     created_at)
                             VALUES (:tenant_id, :user_id, 'SEND_NOTIFICATION', 'notification_delivery', :resource_id,
                                     :details, NOW())
                             """), {
                            "tenant_id": request.tenant_id,
                            "user_id": user_context.get("user_id"),
                            "resource_id": str(delivery_id),
                            "details": json.dumps({
                                "channel": request.channel,
                                "to": str(request.to),
                                "template_id": request.template_id
                            })
                        })
        self.db.commit()

    async def _compensate(self):
        """Compensation logic for saga failures"""
        for step, delivery_id in reversed(self.compensation_steps):
            try:
                if step == "create_delivery" and delivery_id:
                    # Mark delivery as failed
                    self.db.execute(text("""
                                         UPDATE notification_deliveries_new
                                         SET status     = 'failed',
                                             updated_at = NOW()
                                         WHERE id = :id
                                         """), {"id": delivery_id})
                    self.db.commit()
                # Add more compensation steps as needed
            except Exception as e:
                logger.error("Compensation step failed", step=step, error=str(e))