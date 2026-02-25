import uuid
from sqlalchemy.orm import Session
from provisioning_service.Models import OutboxEvent, User
from provisioning_service.utils.logger import logger

# Import external service helper (AiFi)
from provisioning_service.core.helpers.aifi_services import cv_create_customer

async def handle_user_created(db: Session, payload_id: str) -> None:
    """Handle post-create processing for a user (e.g., AiFi customer creation, welcome email).

    - payload_id is the OutboxEvent.id (uuid string)
    - Loads OutboxEvent and runs post-processing using the stored event_data
    - On success commits changes (e.g., updates user's aifi_customer_id)
    """
    outbox = db.query(OutboxEvent).filter(OutboxEvent.id == uuid.UUID(payload_id)).first()
    if not outbox:
        raise ValueError(f"Outbox event {payload_id} not found")

    payload = outbox.event_data or {}
    user_id = payload.get("user_id")
    if not user_id:
        raise ValueError("user_id missing in outbox payload")

    user = db.query(User).filter(User.user_id == uuid.UUID(user_id)).first()
    if not user:
        raise ValueError(f"User {user_id} not found")

    # Try AiFi sync (best-effort) and update user record
    try:
        result = await cv_create_customer({
            "externalId": str(user.user_id),
            "email": user.email,
            "firstName": user.first_name,
            "lastName": user.last_name
        })
        # Example: result may contain an id
        user.aifi_customer_id = result.get("id") if isinstance(result, dict) else None
        db.commit()
        logger.info(f"AiFi sync succeeded for user {user.user_id}")
    except Exception as e:
        db.rollback()
        logger.warning(f"AiFi sync failed for user {user.user_id}: {e}")
        # Raise to trigger retry logic in worker
        raise

    # Optionally send welcome email or other actions here
    return

