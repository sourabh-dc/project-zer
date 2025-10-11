import uuid
from sqlalchemy.orm import Session
from fastapi import HTTPException

from ..repositories.user_repository import UserRepository

import logging

logger = logging.getLogger(__name__)

class UserService:
    def __init__(self):
        self.repo = UserRepository()

    async def upsert_user_v2(self, user_id: str, payload, db: Session):
        try:
            user_uuid = uuid.UUID(user_id)
        except ValueError:
            user_uuid = uuid.uuid4()

        user = self.repo.get_by_id(db, str(user_uuid))
        if user:
            user = self.repo.update_user(db, user, payload.email, payload.display_name, payload.active)
            logger.info("user_updated", extra={"user_id": str(user_uuid)})
            return {"user_id": str(user.user_id), "email": user.email, "display_name": user.display_name, "updated": True}

        # Check if email already exists for a different user
        existing_user = self.repo.get_by_email(db, payload.email)
        if existing_user:
            raise HTTPException(status_code=400, detail=f"Email {payload.email} already exists for user {existing_user.user_id}")

        user = self.repo.create_user(db, user_id, payload.email, payload.display_name, payload.active)
        logger.info("user_created", extra={"user_id": str(user_uuid)})
        return {"user_id": str(user.user_id), "email": user.email, "display_name": user.display_name, "created": True}
