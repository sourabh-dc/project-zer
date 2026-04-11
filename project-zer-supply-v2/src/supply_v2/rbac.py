from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, HTTPException
from sqlalchemy import Column, DateTime, ForeignKey, String, func

from supply_v2.auth import AuthContext, get_auth_context
from supply_v2.db import Base


class RoleRow(Base):
    __tablename__ = "auth_roles"

    code = Column(String(100), primary_key=True)
    description = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class PermissionRow(Base):
    __tablename__ = "auth_permissions"

    code = Column(String(150), primary_key=True)
    description = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class RolePermissionRow(Base):
    __tablename__ = "auth_role_permissions"

    id = Column(String(100), primary_key=True)
    role_code = Column(String(100), ForeignKey("auth_roles.code", ondelete="CASCADE"), nullable=False, index=True)
    permission_code = Column(String(150), ForeignKey("auth_permissions.code", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class UserRoleRow(Base):
    __tablename__ = "auth_user_roles"

    id = Column(String(100), primary_key=True)
    tenant_id = Column(String(100), nullable=False, index=True)
    user_id = Column(String(100), nullable=False, index=True)
    role_code = Column(String(100), ForeignKey("auth_roles.code", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


DEFAULT_PERMISSIONS: list[tuple[str, str]] = [
    ("vendors.manage", "Manage vendors"),
    ("vendors.view", "View vendors"),
    ("vendors.portal.view", "View vendor portal data"),
    ("orders.create", "Create orders"),
    ("orders.view", "View orders"),
    ("orders.finalize", "Finalize orders"),
    ("orders.cancel", "Cancel order lines"),
    ("orders.reallocate", "Reallocate order lines"),
    ("purchase_orders.view", "View purchase orders"),
    ("purchase_orders.acknowledge", "Acknowledge purchase orders"),
    ("shipments.create", "Create shipments"),
    ("receipts.create", "Create receipts"),
    ("disputes.view", "View disputes"),
    ("disputes.resolve", "Resolve disputes"),
    ("invoices.create", "Create invoices"),
    ("slas.view", "View slas"),
    ("ops.manage", "Run operations jobs"),
]

ROLE_PERMISSION_MAP = {
    "admin": {"*"},
    "tenant_admin": {"*"},
    "ops": {
        "vendors.manage",
        "vendors.view",
        "vendors.portal.view",
        "orders.create",
        "orders.view",
        "orders.finalize",
        "orders.cancel",
        "orders.reallocate",
        "purchase_orders.view",
        "purchase_orders.acknowledge",
        "shipments.create",
        "receipts.create",
        "disputes.view",
        "disputes.resolve",
        "invoices.create",
        "slas.view",
        "ops.manage",
    },
    "vendor": {
        "vendors.view",
        "vendors.portal.view",
        "purchase_orders.view",
        "purchase_orders.acknowledge",
        "shipments.create",
        "disputes.view",
        "invoices.create",
        "slas.view",
    },
    "customer": {
        "orders.create",
        "orders.view",
        "receipts.create",
    },
}


@dataclass
class RBACService:
    session_factory: Optional[object] = None

    def seed_defaults(self) -> None:
        if not self.session_factory:
            return
        session = self.session_factory()
        try:
            for code, description in DEFAULT_PERMISSIONS:
                if not session.query(PermissionRow).filter(PermissionRow.code == code).first():
                    session.add(PermissionRow(code=code, description=description))
            for role_code in ROLE_PERMISSION_MAP:
                if not session.query(RoleRow).filter(RoleRow.code == role_code).first():
                    session.add(RoleRow(code=role_code, description=f"{role_code} role"))
            session.flush()
            counter = 0
            for role_code, permissions in ROLE_PERMISSION_MAP.items():
                for permission in permissions:
                    if permission == "*":
                        continue
                    exists = session.query(RolePermissionRow).filter(
                        RolePermissionRow.role_code == role_code,
                        RolePermissionRow.permission_code == permission,
                    ).first()
                    if not exists:
                        counter += 1
                        session.add(
                            RolePermissionRow(
                                id=f"role_perm_{role_code}_{counter}",
                                role_code=role_code,
                                permission_code=permission,
                            )
                        )
            session.commit()
        finally:
            session.close()

    def resolve_permissions(self, auth: AuthContext) -> set[str]:
        perms = set(auth.permissions or [])
        roles = list(auth.roles or [])
        if auth.role and auth.role not in roles:
            roles.append(auth.role)
        for role in roles:
            perms.update(ROLE_PERMISSION_MAP.get(role, set()))

        if self.session_factory and auth.user_id and auth.tenant_id:
            session = self.session_factory()
            try:
                db_roles = session.query(UserRoleRow).filter(
                    UserRoleRow.tenant_id == auth.tenant_id,
                    UserRoleRow.user_id == auth.user_id,
                ).all()
                for item in db_roles:
                    roles.append(item.role_code)
                    perms.update(ROLE_PERMISSION_MAP.get(item.role_code, set()))
                    db_perms = session.query(RolePermissionRow).filter(
                        RolePermissionRow.role_code == item.role_code
                    ).all()
                    perms.update(row.permission_code for row in db_perms)
            finally:
                session.close()

        return perms


def require_permission(container, permission_code: str):
    service = RBACService(container.persistent.session_factory if container.persistent else None)

    def dependency(auth: AuthContext = Depends(get_auth_context)) -> AuthContext:
        permissions = service.resolve_permissions(auth)
        if "*" in permissions or permission_code in permissions:
            auth.permissions = list(permissions)
            return auth
        raise HTTPException(403, "insufficient permissions")

    return dependency
