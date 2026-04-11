from __future__ import annotations

from typing import Any, Optional

import httpx
from fastapi import Depends, HTTPException, Request

from supply_v2.auth import AuthContext, get_auth_context
from supply_v2.config import get_settings


def _resource_type_to_path(resource_type: str) -> str:
    explicit = {
        "vendor": "vendors/manage",
        "order": "orders/manage",
        "purchase_order": "purchase_orders/manage",
        "shipment": "shipments/manage",
        "dispute": "disputes/manage",
        "invoice": "invoices/manage",
        "ops": "ops/manage",
    }
    return explicit.get(resource_type, f"{resource_type}s/manage")


async def check_policy(
    action: str,
    resource_type: str,
    user: dict[str, Any],
    resource: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    settings = get_settings()
    if settings.policy_mode == "disabled":
        return {"allow": True, "reasons": []}

    payload = {
        "input": {
            "user": user,
            "action": action,
            "resource": resource or {"type": resource_type},
        }
    }

    if settings.policy_mode == "local":
        return _evaluate_local_policy(action, resource_type, user, resource or {})

    url = f"{settings.opa_url}/v1/data/{_resource_type_to_path(resource_type)}"
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        result = response.json().get("result", {})
        return {
            "allow": result.get("allow", False),
            "reasons": list(result.get("reasons", [])),
        }


async def _extract_resource(request: Request) -> dict[str, Any]:
    resource: dict[str, Any] = {}
    if request.method in {"POST", "PUT", "PATCH"}:
        try:
            body = await request.json()
            if isinstance(body, dict):
                resource["attributes"] = body
                if "tenant_id" in body:
                    resource["tenant_id"] = body["tenant_id"]
                if "customer_id" in body:
                    resource["customer_id"] = body["customer_id"]
                if "vendor_id" in body:
                    resource["vendor_id"] = body["vendor_id"]
                if "new_vendor_id" in body:
                    resource["new_vendor_id"] = body["new_vendor_id"]
        except Exception:
            pass
    for key in ("tenant_id", "order_id", "po_id", "vendor_id", "dispute_id"):
        if key in request.path_params:
            resource[key] = request.path_params[key]
    return resource


def _load_policy_resource(container: Any, resource_type: str, resource: dict[str, Any]) -> dict[str, Any]:
    if not container or not getattr(container, "platform", None):
        return resource
    store = container.platform.store

    vendor_id = resource.get("vendor_id")
    if vendor_id and vendor_id in getattr(store, "vendors", {}):
        vendor = store.vendors[vendor_id]
        resource.setdefault("tenant_id", vendor.tenant_id)
        resource.setdefault("vendor_owner_id", vendor.vendor_id)

    order_id = resource.get("order_id")
    if order_id and order_id in getattr(store, "orders", {}):
        order = store.orders[order_id]
        resource.setdefault("tenant_id", order.tenant_id)
        resource.setdefault("customer_id", order.customer_id)
        resource.setdefault("order_status", order.status)

    po_id = resource.get("po_id")
    if po_id and po_id in getattr(store, "purchase_orders", {}):
        po = store.purchase_orders[po_id]
        resource.setdefault("tenant_id", po.tenant_id)
        resource.setdefault("vendor_id", po.vendor_id)
        resource.setdefault("order_id", po.order_id)
        resource.setdefault("po_status", po.status)

    dispute_id = resource.get("dispute_id")
    if dispute_id and dispute_id in getattr(store, "disputes", {}):
        dispute = store.disputes[dispute_id]
        resource.setdefault("tenant_id", dispute.tenant_id)
        resource.setdefault("vendor_id", dispute.vendor_id)
        resource.setdefault("order_id", dispute.order_id)
        resource.setdefault("po_id", dispute.po_id)
        resource.setdefault("dispute_source", dispute.source)
        resource.setdefault("dispute_status", dispute.status)

    return resource


def require_policy(container: Any, action: str, resource_type: str):
    async def dependency(request: Request, auth: AuthContext = Depends(get_auth_context)) -> AuthContext:
        if hasattr(container, "reload"):
            container.reload()
        resource = await _extract_resource(request)
        resource = _load_policy_resource(container, resource_type, resource)
        resource.setdefault("tenant_id", auth.tenant_id)
        resource.setdefault("type", resource_type)
        result = await check_policy(
            action=action,
            resource_type=resource_type,
            user={
                "user_id": auth.user_id,
                "tenant_id": auth.tenant_id,
                "roles": auth.roles or [auth.role],
                "permissions": auth.permissions or [],
            },
            resource=resource,
        )
        if not result["allow"]:
            raise HTTPException(403, f"policy denied: {'; '.join(result.get('reasons', []))}")
        return auth

    return dependency


def _evaluate_local_policy(
    action: str,
    resource_type: str,
    user: dict[str, Any],
    resource: dict[str, Any],
) -> dict[str, Any]:
    tenant_id = resource.get("tenant_id") or user.get("tenant_id")
    if tenant_id and tenant_id != user.get("tenant_id"):
        return {"allow": False, "reasons": ["cross_tenant_denied"]}

    roles = set(user.get("roles") or [])
    permissions = set(user.get("permissions") or [])
    if "*" in permissions or roles.intersection({"admin", "tenant_admin"}):
        return {"allow": True, "reasons": []}

    if "vendor" in roles:
        vendor_id = resource.get("vendor_id")
        if vendor_id and vendor_id != user.get("user_id"):
            return {"allow": False, "reasons": ["vendor_scope_denied"]}

    if "customer" in roles and resource_type == "order":
        customer_id = resource.get("customer_id")
        if customer_id and customer_id != user.get("user_id"):
            return {"allow": False, "reasons": ["customer_scope_denied"]}

    allowed = {
        ("vendor", "read"): {"vendor", "ops"},
        ("vendor", "create"): {"ops"},
        ("order", "create"): {"customer", "ops"},
        ("order", "read"): {"customer", "ops", "vendor"},
        ("order", "update"): {"ops"},
        ("order", "cancel"): {"ops"},
        ("order", "reallocate"): {"ops"},
        ("purchase_order", "read"): {"vendor", "ops"},
        ("purchase_order", "acknowledge"): {"vendor", "ops"},
        ("shipment", "create"): {"vendor", "ops", "customer"},
        ("shipment", "read"): {"vendor", "ops", "customer"},
        ("dispute", "read"): {"vendor", "ops", "customer"},
        ("dispute", "resolve"): {"ops"},
        ("invoice", "create"): {"vendor", "ops"},
        ("invoice", "read"): {"vendor", "ops"},
        ("ops", "read"): {"ops"},
        ("ops", "run"): {"ops"},
        ("ops", "update"): {"ops"},
        ("ops", "replay"): {"ops"},
    }

    if resource_type == "purchase_order" and action == "acknowledge" and resource.get("po_status") in {"cancelled", "completed"}:
        return {"allow": False, "reasons": ["po_terminal_state_denied"]}
    if resource_type == "shipment" and action == "create" and resource.get("po_status") not in {None, "accepted", "accepted_with_changes"}:
        return {"allow": False, "reasons": ["po_not_shippable"]}
    if resource_type == "invoice" and action == "create" and resource.get("po_status") not in {None, "accepted", "accepted_with_changes", "shipped", "received"}:
        return {"allow": False, "reasons": ["po_not_invoiceable"]}
    if resource_type == "dispute" and action == "resolve" and resource.get("dispute_status") == "resolved":
        return {"allow": False, "reasons": ["dispute_already_resolved"]}

    if roles.intersection(allowed.get((resource_type, action), set())):
        return {"allow": True, "reasons": []}
    return {"allow": False, "reasons": ["role_action_denied"]}
