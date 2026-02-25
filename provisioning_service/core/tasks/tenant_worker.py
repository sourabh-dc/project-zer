import uuid
from datetime import datetime, timezone
from typing import Any

from provisioning_service.Models import User, Role, Permission, RolePermission, UserRole, OutboxEvent
from sqlalchemy.orm import Session
import bcrypt
from provisioning_service.utils.logger import logger


async def handle_tenant_provisioning(db: Session, payload_id: str) -> None:
    """Handle tenant provisioning for given outbox event id (payload_id).

    This will:
    - Load OutboxEvent by id
    - Create admin user, ensure role and permission mappings, and assign user role
    - Update OutboxEvent 'event_data' if necessary (e.g., add generated password)

    The function raises exceptions on failure so the caller can implement retry logic.
    """
    # Load event
    outbox = db.query(OutboxEvent).filter(OutboxEvent.id == uuid.UUID(payload_id)).first()
    if not outbox:
        raise ValueError(f"Outbox event {payload_id} not found")

    payload = outbox.event_data or {}
    tenant_id = payload.get("tenant_id")
    if not tenant_id:
        raise ValueError("tenant_id missing in outbox payload")

    logger.info(f"Tenant worker: provisioning tenant {tenant_id} for outbox {payload_id}")

    password_raw = payload.get("password")
    if not password_raw:
        password_raw = uuid.uuid4().hex[:12]
        # store generated password back into event_data for auditing if desired
        payload["generated_password"] = password_raw
        outbox.event_data = payload
        db.commit()

    password_hash = bcrypt.hashpw(password_raw.encode("utf-8"), bcrypt.gensalt(12)).decode("utf-8")

    # create user
    user = User(
        user_id=uuid.uuid4(),
        tenant_id=tenant_id,
        first_name=payload.get("admin_firstname") or payload.get("first_name") or "Admin",
        last_name=payload.get("admin_lastname") or payload.get("last_name") or "",
        display_name=(f"{payload.get('admin_firstname','')} {payload.get('admin_lastname','')}").strip(),
        email=payload.get("admin_email") or payload.get("email"),
        password_hash=password_hash
    )
    db.add(user)

    # ensure tenant_admin role exists
    role = db.query(Role).filter(Role.code == "tenant_admin").first()
    if not role:
        role = Role(role_id=uuid.uuid4(), code="tenant_admin", description="Super admin for tenant")
        db.add(role)
        db.flush()

    # ensure core permissions exist and role-permission mappings
    core_permissions = [
        ("tenant.admin", "Full tenant administration"),
        ("users.manage", "Create and manage users"),
        ("sites.manage", "Create and manage sites"),
        ("stores.manage", "Create and manage stores"),
        ("vendors.manage", "Create and manage vendors"),
        ("budgets.manage", "Manage budgets and cost centres"),
        ("approvals.manage", "Manage approval chains and requests"),
        ("catalog.manage", "Manage products and catalog"),
    ]

    for perm_code, perm_desc in core_permissions:
        perm = db.query(Permission).filter(Permission.code == perm_code).first()
        if not perm:
            perm = Permission(permission_id=uuid.uuid4(), code=perm_code, description=perm_desc)
            db.add(perm)
            db.flush()

        existing_rp = db.query(RolePermission).filter(
            RolePermission.role_code == role.code,
            RolePermission.permission_code == perm_code
        ).first()
        if not existing_rp:
            db.add(RolePermission(id=uuid.uuid4(), role_code=role.code, permission_code=perm_code))

    # assign role to user
    user_role = UserRole(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        user_id=user.user_id,
        role_id=role.role_id
    )
    db.add(user_role)

    # commit all
    db.commit()

    logger.info(f"Tenant worker: provisioning complete for tenant {tenant_id} (outbox {payload_id})")

