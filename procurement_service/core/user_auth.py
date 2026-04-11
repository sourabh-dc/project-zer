from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import jwt
from fastapi import Depends, Header, HTTPException
from starlette import status

from procurement_service.core.config import SETTINGS


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
        "disputes.create",
        "disputes.resolve",
        "invoices.create",
        "invoices.view",
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
        "disputes.create",
        "invoices.create",
        "invoices.view",
        "slas.view",
    },
    "customer": {
        "orders.create",
        "orders.view",
        "receipts.create",
        "disputes.create",
        "disputes.view",
        "invoices.view",
    },
}


DEFAULT_PERMISSIONS = [
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
    ("disputes.create", "Raise disputes"),
    ("disputes.resolve", "Resolve disputes"),
    ("invoices.create", "Create invoices"),
    ("invoices.view", "View invoices"),
    ("slas.view", "View slas"),
    ("ops.manage", "Run operations jobs"),
]


_USER_ROLE_ASSIGNMENTS: dict[tuple[str, str], set[str]] = {}


@dataclass
class UserContext:
    tenant_id: str
    user_id: str
    role: str
    permissions: list[str]


def list_roles() -> list[dict[str, str]]:
    return [{"code": role, "description": f"{role} role"} for role in ROLE_PERMISSION_MAP.keys()]


def list_permissions() -> list[dict[str, str]]:
    return [{"code": code, "description": description} for code, description in DEFAULT_PERMISSIONS]


def assign_user_role(tenant_id: str, user_id: str, role_code: str) -> None:
    if role_code not in ROLE_PERMISSION_MAP:
        raise ValueError("role not found")
    key = (tenant_id, user_id)
    if key not in _USER_ROLE_ASSIGNMENTS:
        _USER_ROLE_ASSIGNMENTS[key] = set()
    _USER_ROLE_ASSIGNMENTS[key].add(role_code)


def _resolve_permissions(tenant_id: str, user_id: str, role: str) -> list[str]:
    roles = {role}
    roles.update(_USER_ROLE_ASSIGNMENTS.get((tenant_id, user_id), set()))
    permissions: set[str] = set()
    for item in roles:
        permissions.update(ROLE_PERMISSION_MAP.get(item, set()))
    return list(permissions)


def _decode_bearer_token(token: str) -> dict:
    if not SETTINGS.JWT_SECRET:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="JWT secret not configured")
    return jwt.decode(
        token,
        SETTINGS.JWT_SECRET,
        algorithms=[SETTINGS.JWT_ALGORITHM],
        audience=SETTINGS.JWT_AUDIENCE,
        issuer=SETTINGS.JWT_ISSUER,
    )


def get_user_context(
    x_tenant_id: str = Header(default="tenant_demo"),
    x_user_id: str = Header(default="user_demo"),
    x_role: str = Header(default="admin"),
    authorization: Optional[str] = Header(default=None),
) -> UserContext:
    if SETTINGS.AUTH_MODE == "jwt":
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing bearer token")
        claims = _decode_bearer_token(authorization.split(" ", 1)[1])
        role = claims.get("role", "viewer")
        permissions = list(set(claims.get("permissions", []) + _resolve_permissions(claims.get("tenant_id", ""), claims.get("sub", ""), role)))
        return UserContext(
            tenant_id=claims.get("tenant_id", ""),
            user_id=claims.get("sub", ""),
            role=role,
            permissions=permissions,
        )

    permissions = _resolve_permissions(x_tenant_id, x_user_id, x_role)
    return UserContext(tenant_id=x_tenant_id, user_id=x_user_id, role=x_role, permissions=permissions)


def check_user_authorization(permission: str):
    def dependency(ctx: UserContext = Depends(get_user_context)) -> UserContext:
        if "*" in ctx.permissions or permission in ctx.permissions:
            return ctx
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    return dependency


def require_internal_service(x_internal_api_key: Optional[str] = Header(default=None)) -> bool:
    if x_internal_api_key != SETTINGS.INTERNAL_API_KEY:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid internal api key")
    return True
