"""
Policy client — procurement_service.

Gate 2: OPA policy enforcement via the shared in-process policy engine.
No HTTP call to a separate service — evaluation happens in-process.

Usage in endpoints:

    # Gate 1: RBAC
    ctx = Depends(check_user_authorization("vendors.manage"))

    # Gate 2: Policy (OPA Rego enforcement)
    policy = Depends(require_policy("vendor.update"))
"""
from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session
from starlette import status

from procurement_service.core.config import SETTINGS
from procurement_service.core.user_auth import UserContext, get_user_context
from procurement_service.utils.logger import logger
from shared.policy_engine import evaluate as _evaluate, get_policy_db

POLICY_ENGINE_BYPASS = bool(SETTINGS.POLICY_ENGINE_BYPASS)


def _subject_from_ctx(ctx: UserContext) -> Dict[str, Any]:
    return {
        "user_id":     ctx.user_id,
        "tenant_id":   ctx.tenant_id,
        "roles":       [ctx.role] if ctx.role else [],
        "permissions": ctx.permissions,
    }


def _handle_decision(result: Dict[str, Any]) -> Dict[str, Any]:
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
):
    """Gate 2 dependency — enforces an OPA Rego policy in-process."""

    async def dependency(
        request: Request,
        ctx: UserContext = Depends(get_user_context),
        db: Session = Depends(get_policy_db),
    ) -> Dict[str, Any]:
        if POLICY_ENGINE_BYPASS:
            logger.debug(f"Policy bypass — auto-allow for action={action}")
            return {"decision": "allow", "allowed": True, "reason": "bypass", "matched_policies": []}

        subject = _subject_from_ctx(ctx)
        tenant_id = ctx.tenant_id

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
        return _handle_decision(result)

    return dependency
