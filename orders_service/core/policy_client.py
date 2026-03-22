import time
from typing import Any, Dict, Optional

import httpx
from fastapi import HTTPException, Request, Security
from starlette import status

from orders_service.core.auth import decode_jwt_with_settings
from orders_service.core.config import SETTINGS
from orders_service.utils.logger import logger

POLICY_ENGINE_URL = SETTINGS.POLICY_ENGINE_URL
POLICY_EVALUATE_TIMEOUT = float(SETTINGS.POLICY_EVALUATE_TIMEOUT)


class PolicyClient:
    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(base_url=POLICY_ENGINE_URL, timeout=POLICY_EVALUATE_TIMEOUT)
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
            logger.debug(f"Policy evaluate [{action}] -> {result.get('decision')} ({elapsed_ms}ms)")
            return result
        except httpx.TimeoutException:
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Policy engine timed out",
            )
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Policy engine unreachable: {str(exc)}",
            )


policy_client = PolicyClient()


def require_policy(
    action: str,
    *,
    resource_from: str = "body",
    resource_fields: Optional[list] = None,
):
    async def dependency(
        request: Request,
        claims: Dict[str, Any] = Security(decode_jwt_with_settings),
    ) -> Dict[str, Any]:
        subject = {
            "user_id": claims.get("sub"),
            "tenant_id": claims.get("tenant_id"),
            "roles": claims.get("roles", []),
            "permissions": claims.get("permissions", []),
            "email": claims.get("email"),
        }
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
        if "tenant_id" not in resource and tenant_id:
            resource["tenant_id"] = tenant_id

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
        return result

    return dependency

