import time
import uuid
from typing import Dict, Any, List

from fastapi import HTTPException
from sqlalchemy import text

from services.identity.models import OutboxEvent, AuditLog, UserNew, RoleAssignmentNew, RoleNew
from services.identity.schemas import UserCreateRequest, UserResponse
from services.identity.utils.identity_logger import logger


class UserCreationSaga:
    """Saga for user creation operations with compensation"""

    def __init__(self, db):
        self.db = db
        self.compensation_steps = []

    def execute_create_user(self, payload: UserCreateRequest, user_context: Dict[str, Any]) -> UserResponse:
        """Execute user creation saga"""
        saga_start = time.time()

        try:
            # Step 1: Validate tenant exists
            self._validate_tenant(payload.tenant_id)
            self.compensation_steps.append(("validate_tenant", None))

            # Step 2: Create user
            user = self._create_user(payload, user_context)
            self.compensation_steps.append(("create_user", user.id))

            # Step 3: Assign roles
            roles = self._assign_roles(user.id, payload.role_ids, payload.tenant_id, user_context)
            self.compensation_steps.append(("assign_roles", {"user_id": user.id, "role_ids": payload.role_ids}))

            # Step 4: Publish USER_CREATED event
            self._publish_user_created_event(user, roles, user_context)
            self.compensation_steps.append(("publish_event", None))

            # Step 5: Audit log
            self._audit_log("CREATE_USER", payload, user_context)

            # Metrics temporarily disabled
            pass

            return user

        except Exception as e:
            logger.error(f"User creation saga failed: {str(e)}")
            # Metrics temporarily disabled
            pass
            self._compensate()
            raise

    def _validate_tenant(self, tenant_id: str):
        """Validate tenant exists"""
        query = text("SELECT tenant_id FROM tenants WHERE tenant_id = :tenant_id")
        result = self.db.execute(query, {"tenant_id": tenant_id})
        if not result.first():
            raise HTTPException(status_code=400, detail="Tenant not found")

    def _create_user(self, payload: UserCreateRequest, user_context: Dict[str, Any]) -> UserNew:
        """Create user in database"""
        user = UserNew(
            tenant_id=uuid.UUID(payload.tenant_id),
            email=payload.email,
            name=payload.name,
            primary_cost_centre_id=uuid.UUID(
                payload.primary_cost_centre_id) if payload.primary_cost_centre_id else None,
            user_metadata=payload.user_metadata
        )

        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)

        return user

    def _assign_roles(self, user_id: uuid.UUID, role_ids: List[str], tenant_id: str, user_context: Dict[str, Any]) -> \
    List[RoleNew]:
        """Assign roles to user"""
        roles = []
        for role_id in role_ids:
            # Verify role exists and belongs to tenant
            role_query = text("""
                              SELECT id, name, description, permissions
                              FROM roles_new
                              WHERE id = :role_id
                                AND tenant_id = :tenant_id
                              """)
            result = self.db.execute(role_query, {"role_id": role_id, "tenant_id": tenant_id})
            role_row = result.first()

            if not role_row:
                raise HTTPException(status_code=400, detail=f"Role {role_id} not found")

            # Create role assignment
            assignment = RoleAssignmentNew(
                tenant_id=uuid.UUID(tenant_id),
                user_id=user_id,
                role_id=uuid.UUID(role_id)
            )

            self.db.add(assignment)
            roles.append(role_row)

        self.db.commit()
        return roles

    async def _publish_user_created_event(self, user: UserNew, roles: List[Any], user_context: Dict[str, Any]):
        """Publish USER_CREATED event"""
        event_data = {
            "user_id": str(user.id),
            "tenant_id": str(user.tenant_id),
            "email": user.email,
            "name": user.name,
            "roles": [{"id": str(role[0]), "name": role[1], "permissions": role[3]} for role in roles],
            "created_at": user.created_at.isoformat()
        }

        # Store in outbox for reliable delivery
        outbox_event = OutboxEvent(
            tenant_id=user.tenant_id,
            event_type="USER_CREATED",
            event_data=event_data
        )

        self.db.add(outbox_event)
        await self.db.commit()

    async def _audit_log(self, action: str, payload: Any, user_context: Dict[str, Any]):
        """Create audit log entry"""
        audit_log = AuditLog(
            tenant_id=uuid.UUID(user_context["tenant_id"]),
            user_id=uuid.UUID(user_context["user_id"]),
            action=action,
            resource_type="user",
            resource_id=getattr(payload, 'email', str(uuid.uuid4())),
            details=payload.dict() if hasattr(payload, 'dict') else {}
        )

        self.db.add(audit_log)
        await self.db.commit()

    async def _compensate(self):
        """Execute compensation steps in reverse order"""
        for step_name, step_data in reversed(self.compensation_steps):
            try:
                if step_name == "assign_roles" and step_data:
                    # Remove role assignments
                    delete_query = text("DELETE FROM role_assignments_new WHERE user_id = :user_id")
                    await self.db.execute(delete_query, {"user_id": step_data["user_id"]})
                    await self.db.commit()

                elif step_name == "create_user" and step_data:
                    # Delete user
                    delete_query = text("DELETE FROM users_new WHERE id = :id")
                    await self.db.execute(delete_query, {"id": step_data})
                    await self.db.commit()

                # Add more compensation steps as needed

            except Exception as e:
                logger.error(f"Compensation step {step_name} failed: {str(e)}")