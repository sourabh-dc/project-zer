import uuid
from sqlalchemy.orm import Session
from fastapi import HTTPException
import logging

from ..repositories.role_and_assignment_repository import RoleRepository, RoleAssignmentRepository

logger = logging.getLogger(__name__)

class RolesService:
    def __init__(self):
        self.role_repository = RoleRepository()
        self.assignment_repository = RoleAssignmentRepository()

    async def upsert_role_v2(self, role_id: str, payload, db: Session):
        # Check if role exists
        role = self.role_repository.get_by_id(db, role_id)
        if role:
            role = self.role_repository.update_role(db, role, payload.code, payload.description)
            logger.info("role_updated", extra={"role_id": str(role_id)})
            return {"role_id": str(role.role_id), "code": role.code, "description": role.description, "updated": True}

        r = self.role_repository.create_role(db, role_id, payload.code, payload.description)
        logger.info("role_created", extra={"role_id": str(role_id)})
        return {"role_id": str(r.role_id), "name": r.code, "permissions": r.description, "created": True}
