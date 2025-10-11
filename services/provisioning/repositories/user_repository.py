from typing import Optional, Any
from sqlalchemy.orm import Session
from uuid import uuid4
import logging

from services.provisioning.models import UserV2
from services.provisioning.repositories.base_repository import BaseRepository
from services.provisioning.utils.custom_exceptions import DuplicateError

logger = logging.getLogger(__name__)


# ============================================================================
# USER REPOSITORY
# ============================================================================

class UserRepository(BaseRepository):
    """Repository for User operations"""

    def __init__(self):
        super().__init__(UserV2)

    def get_by_email(self, db: Session, email: str) -> Optional[UserV2]:
        """Get user by email"""
        try:
            return db.query(UserV2).filter(UserV2.email == email).first()
        except Exception as e:
            logger.error(f"Error getting user by email {email}: {e}")
            return None

    def get_by_id(self, db: Session, entity_id: str) -> Optional[Any]:
        """Get a user by its ID"""
        try:
            return db.query(UserV2).filter(UserV2.user_id == entity_id).one_or_none()
        except Exception as e:
            logger.error(f"Error getting user by id {entity_id}: {e}")
            return None

    def create_user(self, db: Session, user_id: str, email: str, display_name: str, active: bool = True) -> UserV2:
        """Create user with email validation"""
        # Check if email already exists
        existing = self.get_by_email(db, email)
        if existing:
            raise DuplicateError(f"User with email '{email}' already exists")

        return self.create(
            db,
            user_id=user_id,
            email=email,
            display_name=display_name,
            active=active
        )

    def update_user(self, db: Session, user, email: Optional[str] = None, display_name: Optional[str] = None, active: Optional[bool] = None) -> Optional[UserV2]:
        """Update user fields by user_id"""
        if email is not None:
            user.email = email
        if display_name is not None:
            user.display_name = display_name
        if active is not None:
            user.active = active
        db.commit()
        return user