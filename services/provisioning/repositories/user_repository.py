from typing import Optional
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

    def create_user(self, db: Session, email: str, display_name: str, active: bool = True) -> UserV2:
        """Create user with email validation"""
        # Check if email already exists
        existing = self.get_by_email(db, email)
        if existing:
            raise DuplicateError(f"User with email '{email}' already exists")

        return self.create(
            db,
            user_id=str(uuid4()),
            email=email,
            display_name=display_name,
            active=active
        )