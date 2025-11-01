# ---- Event Handlers ----
import json
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from services.notifications.repositories.database_ops import get_deliveries, get_total_count, get_provider, \
    update_provider, create_provider
from services.notifications.repositories.db_config import set_rls_context
from services.notifications.repositories.reply_saga import ReplaySaga
from services.notifications.repositories.send_notification_saga import SendNotificationSaga
from services.notifications.schemas import SendNotificationRequest, NotificationResponse, ReplayRequest, \
    NotificationHistoryResponse, RailRequest
from services.notifications.utils.metrics import notification_operations_total, notification_failures_total
from services.notifications.utils.notifications_logger import logger
from services.notifications.utils.user_auth import check_permission


async def handle_entry_granted(event_data: Dict[str, Any], db: Session):
    """Handle ENTRY_GRANTED event"""
    try:
        user_id = event_data.get("user_id")
        tenant_id = event_data.get("tenant_id")
        entry_code = event_data.get("entry_code")

        if user_id and tenant_id:
            # Send SMS notification for entry granted
            request = SendNotificationRequest(
                tenant_id=tenant_id,
                user_id=user_id,
                channel="sms",
                to="+1234567890",  # This would come from user profile
                body=f"Entry code: {entry_code}. Use this code to enter the store.",
                subject="Entry Code"
            )

            saga = SendNotificationSaga(db)
            user_context = {"user_id": user_id, "tenant_id": tenant_id}
            await saga.execute(request, user_context)

            logger.info("Entry granted notification sent", user_id=user_id, entry_code=entry_code)

    except Exception as e:
        logger.error("Failed to handle ENTRY_GRANTED event", error=str(e), event_data=event_data)


async def handle_user_created(event_data: Dict[str, Any], db: Session):
    """Handle USER_CREATED event"""
    try:
        user_id = event_data.get("user_id")
        tenant_id = event_data.get("tenant_id")
        email = event_data.get("email")

        if user_id and tenant_id and email:
            # Send welcome email
            request = SendNotificationRequest(
                tenant_id=tenant_id,
                user_id=user_id,
                channel="email",
                to=email,
                subject="Welcome to ZeroQue",
                body="Welcome to the ZeroQue platform! Your account has been created successfully.",
                template_id="welcome_email"
            )

            saga = SendNotificationSaga(db)
            user_context = {"user_id": user_id, "tenant_id": tenant_id}
            await saga.execute(request, user_context)

            logger.info("Welcome email sent", user_id=user_id, email=email)

    except Exception as e:
        logger.error("Failed to handle USER_CREATED event", error=str(e), event_data=event_data)


async def handle_order_completed(event_data: Dict[str, Any], db: Session):
    """Handle ORDER_COMPLETED event"""
    try:
        order_id = event_data.get("order_id")
        tenant_id = event_data.get("tenant_id")
        customer_id = event_data.get("customer_id")

        if order_id and tenant_id:
            # Send order confirmation notification
            request = SendNotificationRequest(
                tenant_id=tenant_id,
                user_id=customer_id,
                channel="email",
                to="customer@example.com",  # This would come from customer profile
                subject=f"Order #{order_id} Confirmed",
                body=f"Your order #{order_id} has been completed successfully.",
                template_id="order_confirmation"
            )

            saga = SendNotificationSaga(db)
            user_context = {"user_id": customer_id, "tenant_id": tenant_id}
            await saga.execute(request, user_context)

            logger.info("Order confirmation sent", order_id=order_id, customer_id=customer_id)

    except Exception as e:
        logger.error("Failed to handle ORDER_COMPLETED event", error=str(e), event_data=event_data)


async def handle_invoice_posted(event_data: Dict[str, Any], db: Session):
    """Handle INVOICE_POSTED event"""
    try:
        invoice_id = event_data.get("invoice_id")
        tenant_id = event_data.get("tenant_id")
        customer_id = event_data.get("customer_id")
        amount = event_data.get("amount")

        if invoice_id and tenant_id:
            # Send billing notification
            request = SendNotificationRequest(
                tenant_id=tenant_id,
                user_id=customer_id,
                channel="email",
                to="customer@example.com",  # This would come from customer profile
                subject=f"Invoice #{invoice_id} Posted",
                body=f"Your invoice #{invoice_id} for {amount} has been posted.",
                template_id="invoice_notification"
            )

            saga = SendNotificationSaga(db)
            user_context = {"user_id": customer_id, "tenant_id": tenant_id}
            await saga.execute(request, user_context)

            logger.info("Invoice notification sent", invoice_id=invoice_id, customer_id=customer_id)

    except Exception as e:
        logger.error("Failed to handle INVOICE_POSTED event", error=str(e), event_data=event_data)


async def send_notification(
        request: SendNotificationRequest, db: Session, user_context: Dict[str, Any]):
    """Send notification via configured provider"""
    if not check_permission("notifications.send", user_context):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    # Set RLS context
    set_rls_context(db, request.tenant_id, request.user_id)

    try:
        saga = SendNotificationSaga(db)
        result = await saga.execute(request, user_context)

        # Update metrics
        if notification_operations_total:
            notification_operations_total.labels(
                channel=request.channel,
                provider=result["provider"],
                status="success"
            ).inc()

        return NotificationResponse(
            delivery_id=result["delivery_id"],
            status=result["status"],
            provider=result["provider"],
            channel=request.channel,
            created_at=datetime.now(timezone.utc)
        )

    except Exception as e:
        # Update failure metrics
        if notification_failures_total:
            notification_failures_total.labels(
                channel=request.channel,
                provider=request.provider or "unknown",
                error_type=type(e).__name__
            ).inc()

        logger.error("Notification send failed", error=str(e), request=request.dict())
        raise HTTPException(status_code=500, detail=f"Notification send failed: {str(e)}")


async def replay_notification(request: ReplayRequest, db: Session, user_context: Dict[str, Any]):
    """Replay failed notification"""
    if not check_permission("notifications.send", user_context):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    try:
        saga = ReplaySaga(db)
        result = await saga.execute(request, user_context)

        return result

    except Exception as e:
        logger.error("Notification replay failed", error=str(e), request=request.dict())
        raise HTTPException(status_code=500, detail=f"Notification replay failed: {str(e)}")


async def get_notification_history(tenant_id: str, status: Optional[str], channel: Optional[str], limit: int,
        page: int, db: Session, user_context: Dict[str, Any]):
    """Get notification delivery history"""
    if not check_permission("notifications.view", user_context):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    # Set RLS context
    set_rls_context(db, tenant_id)

    try:
        offset = (page - 1) * limit

        # Get deliveries
        deliveries = await get_deliveries(db, tenant_id, status, channel, limit, offset)

        # Get total count
        total_count = await get_total_count(db, tenant_id, status, channel)

        # Convert to dict format
        delivery_list = []
        for delivery in deliveries:
            delivery_dict = dict(delivery._mapping)
            delivery_dict["payload"] = json.loads(delivery_dict["payload"]) if delivery_dict["payload"] else {}
            delivery_dict["error"] = json.loads(delivery_dict["error"]) if delivery_dict["error"] else None
            delivery_list.append(delivery_dict)

        return NotificationHistoryResponse(
            deliveries=delivery_list,
            count=total_count,
            page=page,
            limit=limit
        )

    except Exception as e:
        logger.error("Failed to get notification history", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to get notification history")


async def configure_notification_provider(request: RailRequest, db: Session, user_context: Dict[str, Any]):
    """Configure notification provider"""
    if not check_permission("notifications.admin", user_context):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    try:
        tenant_id = user_context.get("tenant_id")

        # Check if provider already exists
        existing = await get_provider(db, tenant_id, request)

        if existing:
            # Update existing provider
            await update_provider(db, request, existing)
        else:
            # Create new provider
            await create_provider(db, tenant_id, request)

        return {"message": f"Provider {request.name} configured successfully", "active": request.active}

    except Exception as e:
        logger.error("Failed to configure provider", error=str(e), request=request.dict())
        raise HTTPException(status_code=500, detail="Failed to configure provider")


async def replay_legacy(delivery_id: str, db: Session, user_context: Dict[str, Any]):
    """Legacy replay endpoint - deprecated"""
    logger.warning("Legacy replay endpoint used", delivery_id=delivery_id)

    request = ReplayRequest(delivery_id=delivery_id)
    saga = ReplaySaga(db)
    result = await saga.execute(request, user_context)

    return {"replayed": delivery_id, "status": result["status"]}