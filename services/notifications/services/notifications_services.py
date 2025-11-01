# ---- Event Handlers ----
from typing import Dict, Any

from sqlalchemy.orm import Session

from services.notifications.repositories.send_notification_saga import SendNotificationSaga
from services.notifications.schemas import SendNotificationRequest
from services.notifications.utils.notifications_logger import logger


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