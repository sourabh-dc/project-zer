import uuid
from datetime import datetime, timezone, timedelta
from typing import Any

from provisioning_service.Models import User, UserIdentity, Role, Permission, RolePermission, UserRole, OutboxEvent
from sqlalchemy.orm import Session
from provisioning_service.utils.logger import logger


async def handle_tenant_provisioning(db: Session, payload_id: str) -> None:
    """Handle tenant provisioning for given outbox event id (payload_id).

    This will:
    - Load OutboxEvent by id
    - Create admin user (User + UserIdentity), ensure role and permission mappings
    - Trigger welcome emails to admin and tenant contact via the communication module

    The function raises exceptions on failure so the caller can implement retry logic.
    """
    # Load event
    outbox = db.query(OutboxEvent).filter(OutboxEvent.id == uuid.UUID(payload_id)).first()
    if not outbox:
        raise ValueError(f"Outbox event {payload_id} not found")

    payload = outbox.payload or {}
    tenant_id = payload.get("tenant_id")
    if not tenant_id:
        raise ValueError("tenant_id missing in outbox payload")

    logger.info(f"Tenant worker: provisioning tenant {tenant_id} for outbox {payload_id}")

    # Get admin details from payload
    admin_firstname = payload.get("admin_firstname") or payload.get("first_name") or "Admin"
    admin_lastname = payload.get("admin_lastname") or payload.get("last_name") or ""
    admin_email = payload.get("admin_email") or payload.get("email")

    display_name = f"{admin_firstname} {admin_lastname}".strip()

    # Check if UserIdentity already exists (user signed in via Azure before onboarding)
    existing_identity = db.query(UserIdentity).filter(
        UserIdentity.email == admin_email
    ).first()

    if existing_identity:
        # Reuse existing identity — just update tenant_id and create User row
        new_user_id = existing_identity.user_id
        existing_identity.tenant_id = tenant_id
        existing_identity.first_name = admin_firstname or existing_identity.first_name
        existing_identity.last_name = admin_lastname or existing_identity.last_name
        logger.info(f"Reusing existing UserIdentity {new_user_id} for {admin_email}")
    else:
        new_user_id = uuid.uuid4()
        # Create UserIdentity record
        identity = UserIdentity(
            user_id=new_user_id,
            tenant_id=tenant_id,
            email=admin_email,
            first_name=admin_firstname,
            last_name=admin_lastname,
            auth_provider="azure_ad",
        )
        db.add(identity)

    # Create User record
    user = User(
        user_id=new_user_id,
        tenant_id=tenant_id,
        display_name=display_name,
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
        role_id=role.role_id,
    )
    db.add(user_role)

    # commit all DB changes
    db.commit()

    # ── Send welcome emails via communication module ────────────────
    try:
        from provisioning_service.core.config import SETTINGS
        from shared.communication import EmailService

        email_svc = EmailService(SETTINGS.EMAIL_CONNECTION_STRING)

        tenant_name = payload.get("tenant_name", "")
        plan_code = payload.get("plan_code", "")
        is_trial = payload.get("is_trial", False)
        trial_days = payload.get("trial_days", 7)
        trial_ends_at = ""
        if is_trial:
            trial_ends_at = (datetime.now(timezone.utc) + timedelta(days=trial_days)).strftime("%Y-%m-%d")

        # Welcome email to admin
        email_svc.send_welcome_admin(
            admin_email=admin_email,
            admin_name=f"{admin_firstname} {admin_lastname}".strip(),
            tenant_name=tenant_name,
            plan_name=plan_code,
            trial_ends_at=trial_ends_at,
        )

        # Welcome email to tenant contact
        tenant_email = payload.get("email", "")
        if tenant_email and tenant_email != admin_email:
            email_svc.send_welcome_tenant(
                tenant_email=tenant_email,
                tenant_name=tenant_name,
                admin_email=admin_email,
                plan_name=plan_code,
                trial_ends_at=trial_ends_at,
            )

        logger.info(f"Welcome emails sent for tenant {tenant_id}")
    except Exception as email_exc:
        # Email failure should not block provisioning
        logger.warning(f"Welcome email failed for tenant {tenant_id}: {email_exc}")

    logger.info(f"Tenant worker: provisioning complete for tenant {tenant_id} (outbox {payload_id})")

