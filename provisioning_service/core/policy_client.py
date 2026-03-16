"""
Policy Engine HTTP Client — used by provisioning_service to call the
standalone policy engine's /evaluate endpoint over HTTP.

Provides:
  - PolicyClient: async httpx client (singleton) with evaluate()
  - require_policy(): FastAPI dependency factory usable with Depends()

Usage in endpoints:
    @router.post("/orders")
    async def create_order(
        req: OrderRequest,
        ctx = Depends(check_user_authorization("orders.create")),          # Gate 1: RBAC
        policy = Depends(require_policy("order.create", resource_from="body")),  # Gate 2: Policy
    ):
        ...
"""
import time
from typing import Any, Dict, Optional

import httpx
from fastapi import HTTPException, Request, Security
from starlette import status

from provisioning_service.core.config import SETTINGS
from provisioning_service.core.user_auth import decode_jwt_with_settings
from provisioning_service.utils.logger import logger

# ---------------------------------------------------------------------------
# Settings — policy engine URL
# ---------------------------------------------------------------------------
POLICY_ENGINE_URL = getattr(SETTINGS, "POLICY_ENGINE_URL", "http://localhost:8004")
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
            "action": action,
            "subject": subject,
            "resource": resource,
            "tenant_id": tenant_id,
            "correlation_id": correlation_id,
        }

        try:
            start = time.perf_counter()
            resp = await self.client.post("/evaluate", json=payload)
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
# FastAPI dependency factory
# ---------------------------------------------------------------------------

def require_policy(
    action: str,
    *,
    resource_from: str = "body",
    resource_fields: Optional[list] = None,
):
    """Dependency factory for Gate 2 (Policy Engine).

    Usage:
        policy = Depends(require_policy("order.create"))
        policy = Depends(require_policy("order.create", resource_fields=["order_total", "quantity"]))

    Args:
        action: Policy action code, e.g. "order.create", "cost_centre.create"
        resource_from: Where to extract resource context from.
                       "body" → uses the parsed request body (req)
                       "none" → empty resource dict
        resource_fields: Optional list of field names to extract from the request body.
                         If None, the entire body dict is sent as resource context.

    The dependency:
        1. Extracts subject from JWT claims (user_id, tenant_id, roles, permissions)
        2. Extracts resource from request body
        3. Calls policy engine POST /evaluate
        4. If decision == "deny" → raises HTTPException 403
        5. If decision == "require_approval" → raises HTTPException 202 with approval info
        6. If decision == "allow" → returns the full evaluation result dict
    """

    async def dependency(
        request: Request,
        claims: Dict[str, Any] = Security(decode_jwt_with_settings),
    ) -> Dict[str, Any]:
        # Build subject from JWT claims
        subject = {
            "user_id": claims.get("sub"),
            "tenant_id": claims.get("tenant_id"),
            "roles": claims.get("roles", []),
            "permissions": claims.get("permissions", []),
            "email": claims.get("email"),
        }

        tenant_id = claims.get("tenant_id", "")

        # Build resource from request body
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

        # Ensure tenant_id is in resource for cross-tenant checks
        if "tenant_id" not in resource and tenant_id:
            resource["tenant_id"] = tenant_id

        # Call policy engine
        result = await policy_client.evaluate(
            action=action,
            subject=subject,
            resource=resource,
            tenant_id=tenant_id,
            correlation_id=request.headers.get("x-correlation-id"),
        )

        decision = result.get("decision", "allow")

        if decision == "deny":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "policy_decision": "deny",
                    "reason": result.get("reason", "Denied by policy"),
                    "matched_policies": result.get("matched_policies", []),
                },
            )

        if decision == "require_approval":
            raise HTTPException(
                status_code=202,
                detail={
                    "policy_decision": "require_approval",
                    "reason": result.get("reason", "Approval required"),
                    "matched_policies": result.get("matched_policies", []),
                    "approval_required": True,
                },
            )

        # "allow" — return result so the endpoint can inspect if needed
        return result

    return dependency

