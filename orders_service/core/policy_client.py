"""
Policy client — orders_service.

Gate 2: OPA policy enforcement via the shared in-process policy engine.
No HTTP call to a separate service — evaluation happens in-process.

Usage in endpoints:

    # Gate 1: RBAC
    ctx = Depends(check_user_authorization("orders.place"))

    # Gate 2: Policy
    policy = Depends(require_policy("order.create"))

    # Gate 2: Policy with pre-loaded resource context
    policy = Depends(require_policy("purchase_request.create",
                                    resource_loader=pr_resource,
                                    pass_on_require_approval=True))
"""
from typing import Any, Callable, Dict, Optional

from fastapi import Depends, HTTPException, Request, Security
from sqlalchemy.orm import Session
from starlette import status

from orders_service.core.auth import decode_jwt_with_settings
from orders_service.core.config import SETTINGS
from orders_service.utils.logger import logger
from shared.policy_engine import evaluate as _evaluate, get_policy_db

POLICY_ENGINE_BYPASS = bool(getattr(SETTINGS, "POLICY_ENGINE_BYPASS", False))


def _subject_from_claims(claims: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "user_id":     claims.get("sub"),
        "tenant_id":   claims.get("tenant_id"),
        "roles":       claims.get("roles", []),
        "permissions": claims.get("permissions", []),
        "email":       claims.get("email"),
    }


def _handle_decision(result: Dict[str, Any], pass_on_require_approval: bool) -> Dict[str, Any]:
    decision = result.get("decision", "allow")

    if decision == "deny":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "policy_decision":  "deny",
                "reason":           result.get("reason", "Denied by policy"),
                "matched_policies": result.get("matched_policies", []),
            },
        )

    if decision == "require_approval":
        if pass_on_require_approval:
            return result
        raise HTTPException(
            status_code=202,
            detail={
                "policy_decision":   "require_approval",
                "reason":            result.get("reason", "Approval required"),
                "matched_policies":  result.get("matched_policies", []),
                "approval_required": True,
            },
        )

    return result


def require_policy(
    action: str,
    *,
    resource_from: str = "body",
    resource_fields: Optional[list] = None,
    resource_loader: Optional[Callable] = None,
    pass_on_require_approval: bool = False,
):
    """Gate 2 dependency — enforces an OPA Rego policy in-process."""

    if resource_loader is not None:

        async def _with_loader(
            request: Request,
            claims: Dict[str, Any] = Security(decode_jwt_with_settings),
            loaded_resource: Dict[str, Any] = Depends(resource_loader),
            db: Session = Depends(get_policy_db),
        ) -> Dict[str, Any]:
            if POLICY_ENGINE_BYPASS:
                return {"decision": "allow", "allowed": True, "reason": "bypass", "matched_policies": []}

            subject = _subject_from_claims(claims)
            tenant_id = claims.get("tenant_id", "")

            resource = dict(loaded_resource)
            resource.setdefault("tenant_id", tenant_id)

            result = await _evaluate(
                db, action, subject, resource, tenant_id,
                correlation_id=request.headers.get("x-correlation-id"),
            )
            return _handle_decision(result, pass_on_require_approval)

        return _with_loader

    async def _from_body(
        request: Request,
        claims: Dict[str, Any] = Security(decode_jwt_with_settings),
        db: Session = Depends(get_policy_db),
    ) -> Dict[str, Any]:
        if POLICY_ENGINE_BYPASS:
            return {"decision": "allow", "allowed": True, "reason": "bypass", "matched_policies": []}

        subject = _subject_from_claims(claims)
        tenant_id = claims.get("tenant_id", "")

        resource: Dict[str, Any] = {}
        if resource_from == "body":
            try:
                body = await request.json()
                if isinstance(body, dict):
                    resource = (
                        {k: body.get(k) for k in resource_fields if k in body}
                        if resource_fields
                        else body
                    )
            except Exception:
                pass

        resource.setdefault("tenant_id", tenant_id)

        result = await _evaluate(
            db, action, subject, resource, tenant_id,
            correlation_id=request.headers.get("x-correlation-id"),
        )
        return _handle_decision(result, pass_on_require_approval)

    return _from_body
