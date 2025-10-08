from typing import Optional

from sqlalchemy import and_
from sqlalchemy.orm import Session
from uuid import uuid4
import logging

from services.provisioning.models import RoleV2, RoleAssignmentV2
from services.provisioning.repositories.base_repository import BaseRepository
from services.provisioning.repositories.user_repository import UserRepository
from services.provisioning.utils.custom_exceptions import DuplicateError, ValidationError

logger = logging.getLogger(__name__)


# ============================================================================
# ROLE & ROLE ASSIGNMENT REPOSITORY
# ============================================================================

class RoleRepository(BaseRepository):
    """Repository for Role operations"""

    def __init__(self):
        super().__init__(RoleV2)

    def get_by_code(self, db: Session, code: str) -> Optional[RoleV2]:
        """Get role by code"""
        try:
            return db.query(RoleV2).filter(RoleV2.code == code).first()
        except Exception as e:
            logger.error(f"Error getting role by code {code}: {e}")
            return None

    def create_role(self, db: Session, code: str, description: str = "") -> RoleV2:
        """Create role with code validation"""
        # Check if code already exists
        existing = self.get_by_code(db, code)
        if existing:
            raise DuplicateError(f"Role with code '{code}' already exists")

        return self.create(
            db,
            role_id=str(uuid4()),
            code=code,
            description=description
        )


class RoleAssignmentRepository(BaseRepository):
    """Repository for Role Assignment operations"""

    def __init__(self):
        super().__init__(RoleAssignmentV2)

    def get_by_user_and_role(self, db: Session, user_id: str, role_id: str, scope_type: str,
                             scope_id: Optional[str] = None) -> Optional[RoleAssignmentV2]:
        """Get role assignment by user, role, and scope"""
        try:
            query = db.query(RoleAssignmentV2).filter(
                and_(
                    RoleAssignmentV2.user_id == user_id,
                    RoleAssignmentV2.role_id == role_id,
                    RoleAssignmentV2.scope_type == scope_type
                )
            )

            if scope_id is None:
                query = query.filter(RoleAssignmentV2.scope_id.is_(None))
            else:
                query = query.filter(RoleAssignmentV2.scope_id == scope_id)

            return query.first()
        except Exception as e:
            logger.error(f"Error getting role assignment: {e}")
            return None

    def assign_role(self, db: Session, user_id: str, role_id: str, scope_type: str = "GLOBAL",
                    scope_id: Optional[str] = None) -> RoleAssignmentV2:
        """Assign role to user with validation"""
        # Validate user exists
        user_repo = UserRepository()
        if not user_repo.get_by_id(db, user_id):
            raise ValidationError(f"User {user_id} not found")

        # Validate role exists
        role_repo = RoleRepository()
        if not role_repo.get_by_id(db, role_id):
            raise ValidationError(f"Role {role_id} not found")

        # Check if assignment already exists
        existing = self.get_by_user_and_role(db, user_id, role_id, scope_type, scope_id)
        if existing:
            return existing

        return self.create(
            db,
            id=str(uuid4()),
            user_id=user_id,
            role_id=role_id,
            scope_type=scope_type,
            scope_id=scope_id
        )