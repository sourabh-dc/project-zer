"""
policy_engine.middleware
------------------------
FastAPI dependencies that combine **authentication** (auth_service)
with **authorization** (OPA policy engine) in a single Depends() call.

Usage::

    from policy_engine.middleware import require_policy

    @router.post("/sites")
    async def create_site(
        body: SiteCreate,
        user: UserContext = Depends(require_policy("create", "site")),
    ):
        ...

    @router.get("/vendors")
    async def list_vendors(
        user: UserContext = Depends(require_policy("read", "vendor")),
    ):
        ...

Flow:
  1. ``require_auth`` validates the JWT and returns a ``UserContext``
  2. The resource's ``org_id`` is extracted from the request body or path
  3. ``check_policy(action, resource_type, user, resource)`` queries OPA
  4. If denied → 403  ·  if allowed → return the ``UserContext``
"""
import json
import logging
from typing import Any, Callable, Dict, Optional

from fastapi import Depends, HTTPException, Request

from auth_service.middleware import require_auth
from auth_service.schemas import UserContext
from policy_engine.client import check_policy

logger = logging.getLogger("policy_engine.middleware")


async def _extract_resource(request: Request) -> Dict[str, Any]:
    """Best-effort extraction of the resource document from the request.

    Looks for ``org_id`` in (priority order):
      1. Request body JSON
      2. Path parameters
      3. Query parameters
    """
    resource: Dict[str, Any] = {}

    if request.method in ("POST", "PUT", "PATCH"):
        try:
            body = await request.json()
            if isinstance(body, dict):
                resource["attributes"] = body
                if "org_id" in body:
                    resource["org_id"] = body["org_id"]
                if "user_id" in body:
                    resource["user_id"] = body["user_id"]
        except Exception:
            pass

    for key in ("org_id", "tenant_id", "user_id"):
        if key in request.path_params:
            resource[key] = request.path_params[key]

    if "org_id" not in resource:
        q_org = request.query_params.get("org_id")
        if q_org:
            resource["org_id"] = q_org

    return resource


def _user_to_dict(user: UserContext, extra_attributes: Optional[Dict] = None) -> Dict[str, Any]:
    d = {
        "user_id": user.user_id,
        "org_id": user.org_id or "",
        "roles": user.roles,
        "email": user.email or "",
        "permissions": user.permissions,
    }
    if extra_attributes:
        d["attributes"] = extra_attributes
    return d


def require_policy(
    action: str,
    resource_type: str,
    *,
    user_attributes: Optional[Dict[str, Any]] = None,
) -> Callable:
    """Create a FastAPI dependency that enforces an OPA policy.

    Parameters
    ----------
    action : str
        The action being performed (create, read, update, delete, approve, ...).
    resource_type : str
        The resource type (user, site, budget, product, vendor, ...).
    user_attributes : dict, optional
        Extra user attributes (e.g. ``approval_limit``) injected at the route
        level.  These are merged into ``input.user.attributes``.
    """

    async def _enforce(
        request: Request,
        user: UserContext = Depends(require_auth),
    ) -> UserContext:
        resource = await _extract_resource(request)

        if not resource.get("org_id"):
            resource["org_id"] = user.org_id or ""

        resource["type"] = resource_type

        user_dict = _user_to_dict(user, user_attributes)

        result = await check_policy(
            action=action,
            resource_type=resource_type,
            user=user_dict,
            resource=resource,
        )

        if not result["allow"]:
            reasons = "; ".join(result.get("reasons", ["policy denied"]))
            raise HTTPException(status_code=403, detail=f"Policy denied: {reasons}")

        return user

    return _enforce
