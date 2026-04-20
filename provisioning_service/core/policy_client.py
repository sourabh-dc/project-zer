"""
Policy Engine HTTP Client — used by provisioning_service to call the
standalone policy engine's /evaluate endpoint over HTTP.

Provides:
  - PolicyClient: async httpx client (singleton) with evaluate()
  - require_policy(): FastAPI dependency factory usable with Depends()

Usage in endpoints:

    # Gate 1: RBAC
    ctx = Depends(check_user_authorization("orders.place"))

    # Gate 2: Policy (body as resource)
    policy = Depends(require_policy("order.create"))

    # Gate 2: Policy with DB-enriched resource context
    policy = Depends(require_policy("purchase_request.create",
                                    resource_loader=purchase_request_create_resource,
                                    pass_on_require_approval=True))
"""
import time
from typing import Any, Callable, Dict, Optional

import httpx
from fastapi import Depends, HTTPException, Request, Security
from starlette import status

from provisioning_service.core.config import SETTINGS
from provisioning_service.core.user_auth import decode_jwt_with_settings
from provisioning_service.utils.logger import logger

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
POLICY_ENGINE_URL      = getattr(SETTINGS, "POLICY_ENGINE_URL", "http://localhost:8004")
POLICY_EVALUATE_TIMEOUT = float(getattr(SETTINGS, "POLICY_EVALUATE_TIMEOUT", 5.0))


# ---------------------------------------------------------------------------
# HTTP Client (singleton, reusable connection pool)
# ---------------------------------------------------------------------------
class PolicyClient:
    """Async HTTP client for the Policy Engine /evaluate endpoint."""

    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=POLICY_ENGINE_URL,
                timeout=POLICY_EVALUATE_TIMEOUT,
            )
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def evaluate(
        self,
        action: str,
        subject: Dict[str, Any],
        resource: Dict[str, Any],
        tenant_id: str,
        correlation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Call POST /evaluate on the policy engine and return the response dict.

        Returns:
            {
                "decision": "allow" | "deny" | "require_approval",
                "allowed": bool,
                "reason": str | None,
                "matched_policies": [...],
                "evaluation_ms": int,
                ...
            }

        Raises:
            HTTPException 403 on deny / 502 on policy engine error / 504 on timeout.
        """
        payload = {
            "action":         action,
            "subject":        subject,
            "resource":       resource,
            "tenant_id":      tenant_id,
            "correlation_id": correlation_id,
        }

        try:
            start = time.perf_counter()
            resp  = await self.client.post("/evaluate", json=payload)
            elapsed_ms = int((time.perf_counter() - start) * 1000)

            if resp.status_code != 200:
                logger.error(f"Policy engine returned {resp.status_code}: {resp.text}")
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Policy engine error: {resp.status_code}",
                )

            result = resp.json()
            logger.debug(f"Policy evaluate [{action}] → {result.get('decision')} ({elapsed_ms}ms)")
            return result

        except httpx.TimeoutException:
            logger.error(f"Policy engine timeout for action={action}")
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Policy engine timed out",
            )
        except HTTPException:
            raise
        except Exception as exc:
            logger.error(f"Policy engine call failed: {exc}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Policy engine unreachable: {str(exc)}",
            )


# Singleton instance
policy_client = PolicyClient()


# ---------------------------------------------------------------------------
# Internal helper — build subject dict from JWT claims
# ---------------------------------------------------------------------------

def _subject_from_claims(claims: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "user_id":     claims.get("sub"),
        "tenant_id":   claims.get("tenant_id"),
        "roles":       claims.get("roles", []),
        "permissions": claims.get("permissions", []),
        "email":       claims.get("email"),
    }


# ---------------------------------------------------------------------------
# FastAPI dependency factory
# ---------------------------------------------------------------------------

def require_policy(
    action: str,
    *,
    resource_from: str = "body",
    resource_fields: Optional[list] = None,
    resource_loader: Optional[Callable] = None,
    pass_on_require_approval: bool = False,
):
    """
    Dependency factory for Gate 2 (Policy Engine).

    Parameters
    ----------
    action : str
        Policy action code, e.g. ``"purchase_request.create"``.
    resource_from : str
        When ``resource_loader`` is None: ``"body"`` extracts from the
        request JSON body; ``"none"`` sends an empty resource dict.
    resource_fields : list | None
        Optional subset of body fields to forward as resource context.
    resource_loader : callable | None
        A FastAPI dependency (async or sync function) that returns a
        ``Dict[str, Any]`` to use as the OPA resource context.  When
        provided, ``resource_from`` and ``resource_fields`` are ignored.
        FastAPI's DI cache ensures the loader is executed only once per
        request even if it appears in multiple ``Depends()``.
    pass_on_require_approval : bool
        When ``True``, a ``require_approval`` OPA decision does **not**
        raise an exception — the result dict is returned so the route
        body can branch on ``result["decision"]``.  Use this for actions
        like ``purchase_request.create`` where ``require_approval`` means
        "proceed, but create an approval workflow".

    The dependency:
      1. Extracts subject from JWT claims
      2. Extracts/computes resource context
      3. Calls policy engine POST /evaluate
      4. ``deny``              → raises HTTPException 403
      5. ``require_approval``  → raises HTTPException 202 **unless**
                                 ``pass_on_require_approval=True``
      6. ``allow``             → returns the full evaluation result dict
    """

    # ------------------------------------------------------------------
    # Branch A: caller supplies a resource_loader dependency
    # ------------------------------------------------------------------
    if resource_loader is not None:

        async def _with_loader(
            request: Request,
            claims: Dict[str, Any] = Security(decode_jwt_with_settings),
            loaded_resource: Dict[str, Any] = Depends(resource_loader),
        ) -> Dict[str, Any]:
            subject   = _subject_from_claims(claims)
            tenant_id = claims.get("tenant_id", "")

            resource = dict(loaded_resource)
            if "tenant_id" not in resource and tenant_id:
                resource["tenant_id"] = tenant_id

            result = await policy_client.evaluate(
                action=action,
                subject=subject,
                resource=resource,
                tenant_id=tenant_id,
                correlation_id=request.headers.get("x-correlation-id"),
            )

            return _handle_decision(result, pass_on_require_approval)

        return _with_loader

    # ------------------------------------------------------------------
    # Branch B: extract resource from request body (original behaviour)
    # ------------------------------------------------------------------

    async def _from_body(
        request: Request,
        claims: Dict[str, Any] = Security(decode_jwt_with_settings),
    ) -> Dict[str, Any]:
        subject   = _subject_from_claims(claims)
        tenant_id = claims.get("tenant_id", "")

        resource: Dict[str, Any] = {}
        if resource_from == "body":
            try:
                body = await request.json()
                if isinstance(body, dict):
                    if resource_fields:
                        resource = {k: body.get(k) for k in resource_fields if k in body}
                    else:
                        resource = body
            except Exception:
                pass  # no body or not JSON — resource stays empty

        if "tenant_id" not in resource and tenant_id:
            resource["tenant_id"] = tenant_id

        result = await policy_client.evaluate(
            action=action,
            subject=subject,
            resource=resource,
            tenant_id=tenant_id,
            correlation_id=request.headers.get("x-correlation-id"),
        )

        return _handle_decision(result, pass_on_require_approval)

    return _from_body


# ---------------------------------------------------------------------------
# Shared decision handler
# ---------------------------------------------------------------------------

def _handle_decision(result: Dict[str, Any], pass_on_require_approval: bool) -> Dict[str, Any]:
    decision = result.get("decision", "allow")

    if decision == "deny":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "policy_decision":   "deny",
                "reason":            result.get("reason", "Denied by policy"),
                "matched_policies":  result.get("matched_policies", []),
            },
        )

    if decision == "require_approval":
        if pass_on_require_approval:
            # Caller handles routing — return result so route can branch.
            return result
        raise HTTPException(
            status_code=202,
            detail={
                "policy_decision": "require_approval",
                "reason":          result.get("reason", "Approval required"),
                "matched_policies": result.get("matched_policies", []),
                "approval_required": True,
            },
        )

    # "allow"
    return result
