"""
User event worker — handles async side-effects for user events.

Engineering Lock v1.1 §0.5: Workers MUST NOT mutate outbox payload.
"""

import uuid
from sqlalchemy.orm import Session

from provisioning_service.Models import OutboxEvent, User
from provisioning_service.utils.logger import logger
from provisioning_service.core.helpers.aifi_services import cv_create_customer


async def handle_user_created(db: Session, payload_id: str) -> None:
    """Handle post-create processing for a user (AiFi sync, welcome email).

    The user record already exists (created synchronously in the endpoint).
    This handler only performs retryable async side-effects.
    """
    outbox = db.query(OutboxEvent).filter(OutboxEvent.id == uuid.UUID(payload_id)).first()
    if not outbox:
        raise ValueError(f"Outbox event {payload_id} not found")

    payload = outbox.payload or {}
    user_id = payload.get("user_id")
    if not user_id:
        raise ValueError("user_id missing in outbox payload")

    user = db.query(User).filter(User.user_id == uuid.UUID(user_id)).first()
    if not user:
        raise ValueError(f"User {user_id} not found")

    try:
        result = await cv_create_customer({
            "externalId": str(user.user_id),
            "email": user.email,
            "firstName": user.first_name,
            "lastName": user.last_name,
        })
        if isinstance(result, dict) and result.get("id"):
            user.aifi_customer_id = result["id"]
            db.commit()
        logger.info(f"AiFi sync succeeded for user {user.user_id}")
    except Exception as e:
        db.rollback()
        logger.warning(f"AiFi sync failed for user {user.user_id}: {e}")
        raise

    # TODO: Send welcome email
    # TODO: Graph projection — create User node + HAS_USER edge
