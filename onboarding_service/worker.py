"""
onboarding_service.worker
--------------------------
Admin provisioning — creates User record, role, permissions in Postgres.
Authentication (passwords, OTP, email verification) is handled entirely by Auth0.
"""
import logging
import uuid
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from onboarding_service.models import User, Role, Permission, RolePermission, UserRole

logger = logging.getLogger("onboarding_service.worker")

CORE_PERMISSIONS = [
    ("tenant.admin", "Full tenant administration"),
    ("users.manage", "Create and manage users"),
    ("sites.manage", "Create and manage sites"),
    ("stores.manage", "Create and manage stores"),
    ("vendors.manage", "Create and manage vendors"),
    ("budgets.manage", "Manage budgets and cost centres"),
    ("approvals.manage", "Manage approval chains and requests"),
    ("catalog.manage", "Manage products and catalog"),
]


def provision_admin(
    db: Session,
    tenant_id: str,
    admin_email: str,
    admin_firstname: str,
    admin_lastname: str,
    auth0_user_id: Optional[str] = None,
    emit_fn=None,
) -> Dict[str, Any]:
    """Create admin user record, roles, permissions, and emit events.

    Parameters
    ----------
    db : Session
        Active SQLAlchemy session (caller manages commit/rollback).
    tenant_id : str
        UUID of the new tenant.
    admin_email, admin_firstname, admin_lastname : str
        Admin user profile details.
    auth0_user_id : str, optional
        Auth0 user_id — links this Postgres record to Auth0.
    emit_fn : callable, optional
        ``(db, tenant_id, event_type, payload)`` to emit events.

    Returns
    -------
    dict with ``user_id``, ``role_code``, ``permissions`` keys.
    """
    tid = uuid.UUID(tenant_id) if isinstance(tenant_id, str) else tenant_id

    user = User(
        user_id=uuid.uuid4(),
        tenant_id=tid,
        auth0_user_id=auth0_user_id,
        email=admin_email,
        first_name=admin_firstname,
        last_name=admin_lastname,
        display_name=f"{admin_firstname} {admin_lastname}".strip(),
        status="active",
        is_active=True,
    )
    db.add(user)
    db.flush()

    role = db.query(Role).filter(Role.code == "tenant_admin").first()
    if not role:
        role = Role(role_id=uuid.uuid4(), code="tenant_admin",
                    description="Super admin for tenant — full access")
        db.add(role)
        db.flush()

    perm_codes = []
    for perm_code, perm_desc in CORE_PERMISSIONS:
        perm = db.query(Permission).filter(Permission.code == perm_code).first()
        if not perm:
            perm = Permission(permission_id=uuid.uuid4(), code=perm_code, description=perm_desc)
            db.add(perm)
            db.flush()

        existing = db.query(RolePermission).filter(
            RolePermission.role_code == role.code,
            RolePermission.permission_code == perm_code,
        ).first()
        if not existing:
            db.add(RolePermission(id=uuid.uuid4(), role_code=role.code, permission_code=perm_code))
        perm_codes.append(perm_code)

    db.add(UserRole(
        id=uuid.uuid4(),
        tenant_id=tid,
        user_id=user.user_id,
        role_id=role.role_id,
    ))
    db.flush()

    if emit_fn:
        try:
            emit_fn(
                db, str(tid), "user.created",
                {
                    "user_id": str(user.user_id),
                    "tenant_id": str(tid),
                    "auth0_user_id": auth0_user_id,
                    "email": user.email,
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "display_name": user.display_name,
                    "roles": ["tenant_admin"],
                },
            )
        except Exception as exc:
            logger.warning(f"Failed to emit user.created event: {exc}")

    logger.info(f"Admin provisioned: {admin_email} for tenant {tid}")

    return {
        "user_id": str(user.user_id),
        "role_code": "tenant_admin",
        "permissions": perm_codes,
    }
